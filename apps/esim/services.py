"""eSIM iş kuralları: eşitleme, fiyat, sipariş, profil, iptal.

Para yine `apps.finans.services` üzerinden hareket eder; burası siparişi
kurar, sağlayıcıyla konuşur ve sonucu kayda yazar.
"""

import logging
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.esim.models import (
    Paket,
    Saglayici,
    Teslimat,
    TeslimatDurumu,
    Ulke,
    Yukleme,
    YuklemeDurumu,
    satis_fiyati_hesapla,
    tavsiye_fiyati_hesapla,
)
from apps.esim.saglayicilar import SaglayiciHatasi
from apps.esim.ulkeler import bayrak, turkce_ad
from apps.finans.services import (
    SiparisVerilemez,
    siparis_odemesini_geri_al,
    siparis_odemesini_isle,
)
from apps.magaza.models import Siparis, SiparisDurumu

logger = logging.getLogger(__name__)

# Aynı profil için sağlayıcıya bu aralıktan sık sorulmaz; bayinin sayfası
# birkaç saniyede bir yeniliyor, her yenileme bir API isteği olmasın.
SORGU_ARALIGI_SN = 3


class KurTanimsiz(SiparisVerilemez):
    """USD kuru girilmemiş; fiyat hesaplanamaz, satış kapalıdır."""


def kur_getir():
    """Genel Ayarlar'daki USD kuru. Sıfırsa `KurTanimsiz`."""
    from apps.bayi.models import GenelAyarlar

    kur = GenelAyarlar.getir().usd_kuru or Decimal(0)
    if kur <= 0:
        raise KurTanimsiz(
            "USD kuru tanımlı değil; eSIM satışı için Genel Ayarlar'dan kur girilmeli."
        )
    return kur


def kur_var_mi():
    try:
        kur_getir()
    except KurTanimsiz:
        return False
    return True


# -- Katalog ------------------------------------------------------------


def paketleri_esitle(saglayici):
    """Sağlayıcının kataloğunu `Paket` kayıtlarına yazar.

    Yeni paket sağlayıcının varsayılan kâr oranıyla ve **aktif** açılır —
    kapatmak eklemekten kolaydır, yönetici istemediği ülkeyi ya da paketi
    kapatır. Var olan paketin sağlayıcı verisi (ad, hacim, alış) güncellenir,
    yönetimin kararı (kâr oranı, aktif) **korunur**. Listeden düşen paket
    silinmez, `saglayicida_var` kapanır.

    Dönüş: (eklenen, güncellenen, düşen) sayıları.
    """
    veriler = saglayici.adaptor().paketleri_getir()
    simdi = timezone.now()

    with transaction.atomic():
        ulkeler = {u.kod: u for u in Ulke.objects.all()}
        for veri in veriler:
            for kod in veri.ulkeler:
                if kod not in ulkeler:
                    ulkeler[kod] = Ulke.objects.create(
                        kod=kod, ad=turkce_ad(kod, veri.ulke_adlari.get(kod, kod))
                    )

        mevcut = {p.kod: p for p in saglayici.paketler.all()}
        eklenen = guncellenen = 0
        gorulen = set()

        for veri in veriler:
            kodlar = sorted(set(veri.ulkeler))
            alanlar = {
                "slug": veri.slug,
                "ad": veri.ad,
                "aciklama": veri.aciklama,
                "kapsam": ",".join(kodlar),
                "ulke_sayisi": len(kodlar),
                "hacim_bayt": veri.hacim_bayt,
                "sure_gun": veri.sure_gun,
                "hiz": veri.hiz,
                "operatorler": veri.operatorler,
                "alis_usd": veri.alis_usd,
                "saglayicida_var": True,
                "son_gorulme": simdi,
            }
            paket = mevcut.get(veri.kod)
            if paket is None:
                paket = Paket.objects.create(
                    saglayici=saglayici,
                    kod=veri.kod,
                    kar_orani=saglayici.varsayilan_kar_orani,
                    **alanlar,
                )
                eklenen += 1
            else:
                degisti = any(getattr(paket, ad) != deger for ad, deger in alanlar.items())
                if degisti:
                    for ad, deger in alanlar.items():
                        setattr(paket, ad, deger)
                    paket.save()
                    guncellenen += 1
            gorulen.add(veri.kod)

            if set(paket.ulkeler.values_list("kod", flat=True)) != set(kodlar):
                paket.ulkeler.set([ulkeler[k] for k in kodlar])

        dusen = saglayici.paketler.filter(saglayicida_var=True).exclude(kod__in=gorulen)
        dusen_sayisi = dusen.update(saglayicida_var=False)

        saglayici.son_esitleme = simdi
        saglayici.save(update_fields=["son_esitleme", "guncelleme_tarihi"])

    return eklenen, guncellenen, dusen_sayisi


def bakiyeyi_sorgula(saglayici):
    bakiye = saglayici.adaptor().bakiye()
    saglayici.son_bakiye_usd = bakiye
    saglayici.son_bakiye_tarihi = timezone.now()
    saglayici.save(update_fields=["son_bakiye_usd", "son_bakiye_tarihi", "guncelleme_tarihi"])
    return bakiye


def kar_orani_uygula(paketler, oran):
    """Seçili paketlerin kâr oranını tek seferde değiştirir."""
    return paketler.update(kar_orani=Decimal(oran), guncelleme_tarihi=timezone.now())


def fiyatlari_guncelle(saglayici):
    """Sağlayıcının bütün paketlerini onun varsayılan kâr oranına çeker.

    İki bin paketi tek tek yönetmenin anlamı yok: yönetici sağlayıcıya bir
    oran yazar, **Fiyatları güncelle**'ye basar, hepsi o orana geçer.
    Paket başına farklı oran verilmişse o da ezilir — düğme bunu söyler.
    Dönüş: güncellenen paket sayısı.
    """
    return kar_orani_uygula(saglayici.paketler.all(), saglayici.varsayilan_kar_orani)


# -- Bayiye gösterilen liste --------------------------------------------


def bayi_kar_orani(bayi):
    """Bayinin fiyat kademesinden gelen eSIM kâr oranı; yoksa `None` (paketinki geçer).

    Kademe cüzdanda yaşar (`Cuzdan.grup`), başvuru fiyatlarıyla aynı yer.
    Cüzdanı ya da grubu olmayan bayi paket oranını görür.
    """
    cuzdan = getattr(bayi, "cuzdan", None)
    grup = getattr(cuzdan, "grup", None) if cuzdan else None
    if grup is None or grup.esim_kar_orani is None:
        return None
    return grup.esim_kar_orani


def tavsiye_orani():
    """Genel Ayarlar'daki tavsiye satış oranı; sıfırsa tavsiye gösterilmez."""
    from apps.bayi.models import GenelAyarlar

    return GenelAyarlar.getir().esim_tavsiye_kar_orani or Decimal(0)


def fiyatlandir(paketler, kur, kar_orani=None, tavsiye=None):
    """Her pakete `satis` (bayiye), oran varsa `tavsiye` (müşteriye) ve `kazanc` yazar."""
    if tavsiye is None:
        tavsiye = tavsiye_orani()
    for paket in paketler:
        paket.satis = paket.satis_fiyati(kur, kar_orani)
        paket.tavsiye = tavsiye_fiyati_hesapla(paket.satis, tavsiye) if tavsiye > 0 else None
        paket.kazanc = (paket.tavsiye - paket.satis) if paket.tavsiye is not None else None
    return paketler


def en_ucuzlar(paketler):
    """Aynı kapsam, hacim ve süredeki paketlerden yalnızca en ucuzunu bırakır.

    **Sağlayıcı seçimi budur.** İki sağlayıcı aynı ülkede aynı paketi
    veriyorsa bayi ucuz olanı görür ve sipariş oraya gider; hangisinin
    ucuz olduğu ülkeden ülkeye değişebilir. Sıralama alış fiyatına göredir
    (kâr oranı satışı değiştirir ama maliyeti değil).
    """
    secilen = {}
    for paket in sorted(paketler, key=lambda p: (p.hacim_bayt, p.sure_gun, p.alis_usd, p.pk)):
        anahtar = (paket.kapsam, paket.hacim_bayt, paket.sure_gun)
        secilen.setdefault(anahtar, paket)
    return list(secilen.values())


def ulke_paketleri(ulke, kur, kar_orani=None):
    """Bir ülke sayfası: ülkeye özel paketler ve o ülkeyi kapsayan bölgesel paketler."""
    paketler = en_ucuzlar(
        Paket.objects.satilabilir()
        .filter(ulkeler=ulke)
        .select_related("saglayici")
    )
    tavsiye = tavsiye_orani()
    tekil = fiyatlandir([p for p in paketler if not p.bolgesel], kur, kar_orani, tavsiye)
    bolgesel = fiyatlandir([p for p in paketler if p.bolgesel], kur, kar_orani, tavsiye)
    bolgesel.sort(key=lambda p: (p.ulke_sayisi, p.hacim_bayt, p.sure_gun))
    return tekil, bolgesel


def bolgesel_paketler(kur, kar_orani=None):
    paketler = en_ucuzlar(
        Paket.objects.satilabilir().filter(ulke_sayisi__gt=1).select_related("saglayici")
    )
    paketler.sort(key=lambda p: (p.ulke_sayisi, p.hacim_bayt, p.sure_gun))
    return fiyatlandir(paketler, kur, kar_orani)


def ulke_listesi(kur, kar_orani=None):
    """Satılabilir paketi olan ülkeler, en ucuz paketinin satış fiyatıyla."""
    ulkeler = {}
    paketler = (
        Paket.objects.satilabilir()
        .filter(ulkeler__aktif=True)
        .values_list("ulkeler__kod", "ulkeler__ad", "alis_usd", "kar_orani")
    )
    for kod, ad, alis, kar in paketler:
        fiyat = satis_fiyati_hesapla(alis, kar if kar_orani is None else kar_orani, kur)
        kayit = ulkeler.get(kod)
        if kayit is None:
            ulkeler[kod] = {"kod": kod, "ad": ad, "slug": kod.lower(), "en_dusuk": fiyat}
        elif fiyat < kayit["en_dusuk"]:
            kayit["en_dusuk"] = fiyat
    for kayit in ulkeler.values():
        kayit["bayrak"] = bayrak(kayit["kod"])
    return sorted(ulkeler.values(), key=lambda k: k["ad"])


# -- Sipariş ------------------------------------------------------------


def esim_siparisi_ver(bayi, paket, *, anahtar=None, olusturan=None):
    """eSIM siparişi: para düşer, sağlayıcıya iletilir, profil istenir.

    İki adım, iki transaction:
      1. Sipariş ve teslimat kaydı açılır, tutar bakiyeden düşer. Bakiye
         yetmezse hiçbir şey yazılmaz (`SiparisVerilemez`).
      2. Sağlayıcıya sipariş verilir. Reddederse sipariş **iptal edilir ve
         para kendiliğinden iade olur**; sebep teslimatta durur, bayi ekranda
         görür. Kabul ederse profil hemen bir kez sorulur; hazır değilse
         bayinin sayfası sorgulamaya devam eder.

    Sağlayıcı çağrısı transaction dışındadır: HTTP beklerken kilit tutulmaz
    ve "para düştü ama sipariş yok" durumu olmaz — ya iade edilir ya
    sağlayıcıda kaydı vardır.
    """
    if not paket.satilabilir:
        raise SiparisVerilemez("Bu paket şu an satışta değil.")

    kur = kur_getir()
    grup_orani = bayi_kar_orani(bayi)
    oran = paket.kar_orani if grup_orani is None else grup_orani
    satis = paket.satis_fiyati(kur, oran)
    if satis <= 0:
        raise SiparisVerilemez("Bu paketin fiyatı hesaplanamadı.")

    with transaction.atomic():
        if anahtar:
            mevcut = Siparis.objects.filter(islem_anahtari=anahtar).select_related("esim").first()
            if mevcut is not None:
                # Sayfa yenilendi; para zaten işlenmiş.
                return mevcut.esim

        siparis = Siparis.objects.create(
            bayi=bayi,
            urun=None,
            urun_adi=f"eSIM · {paket.ad}",
            adet=1,
            birim_fiyat=satis,
            tutar=satis,
            islem_anahtari=anahtar or None,
        )
        teslimat = Teslimat.objects.create(
            siparis=siparis,
            saglayici=paket.saglayici,
            paket=paket,
            paket_kodu=paket.kod,
            islem_no=uuid4().hex,
            alis_usd=paket.alis_usd,
            kur=kur,
            alis_tl=paket.alis_tl(kur),
            kar_orani=oran,
            tavsiye_fiyati=(
                tavsiye_fiyati_hesapla(satis, tavsiye) if (tavsiye := tavsiye_orani()) > 0 else 0
            ),
        )
        siparis_odemesini_isle(siparis, olusturan=olusturan or bayi)
        siparis.refresh_from_db()

    _saglayiciya_ilet(teslimat, olusturan=olusturan or bayi)
    if teslimat.durum == TeslimatDurumu.HAZIRLANIYOR:
        profili_getir(teslimat, zorla=True)
    return teslimat


def _saglayiciya_ilet(teslimat, *, olusturan=None):
    try:
        siparis_no, profil = teslimat.saglayici.adaptor().siparis_ver(
            teslimat.paket_kodu, teslimat.islem_no, teslimat.alis_usd
        )
    except SaglayiciHatasi as hata:
        logger.warning("eSIM siparişi reddedildi (%s): %s", teslimat.islem_no, hata)
        _hataya_dusur(teslimat, str(hata), olusturan=olusturan)
        return

    teslimat.saglayici_siparis_no = siparis_no
    teslimat.durum = TeslimatDurumu.HAZIRLANIYOR
    teslimat.save(
        update_fields=["saglayici_siparis_no", "durum", "guncelleme_tarihi"]
    )
    if profil is not None:
        # Sağlayıcı profili siparişle birlikte verdi; ikinci sorguya gerek yok.
        _profili_kaydet(teslimat, profil)


def _profili_kaydet(teslimat, profil):
    with transaction.atomic():
        teslimat.esim_no = profil.esim_no
        teslimat.iccid = profil.iccid
        teslimat.ac = profil.ac
        teslimat.qr_url = profil.qr_url
        teslimat.kisa_url = profil.kisa_url
        teslimat.apn = profil.apn
        teslimat.durum = TeslimatDurumu.HAZIR
        teslimat.save()

        siparis = teslimat.siparis
        if siparis.durum == SiparisDurumu.VERILDI:
            siparis.durum = SiparisDurumu.TESLIM
            siparis.save(update_fields=["durum", "guncelleme_tarihi"])


def _hataya_dusur(teslimat, sebep, *, olusturan=None):
    """Sağlayıcı reddetti: teslimat hataya, sipariş iptale, para bayiye."""
    with transaction.atomic():
        teslimat.durum = TeslimatDurumu.HATA
        teslimat.hata = sebep
        teslimat.save(update_fields=["durum", "hata", "guncelleme_tarihi"])

        siparis = teslimat.siparis
        siparis.durum = SiparisDurumu.IPTAL
        siparis.yonetim_notu = f"Sağlayıcı reddetti, tutar iade edildi: {sebep}"[:255]
        siparis.save(update_fields=["durum", "yonetim_notu", "guncelleme_tarihi"])
        siparis_odemesini_geri_al(siparis, olusturan=olusturan)
        siparis.refresh_from_db()


def profili_getir(teslimat, *, zorla=False):
    """Sağlayıcıdan profili sorar; hazırsa kaydeder ve siparişi teslim eder.

    `zorla` yoksa son sorgudan `SORGU_ARALIGI_SN` geçmeden tekrar sorulmaz.
    Hata durumunda teslimat bozulmaz: sorgu hatası geçicidir, bir sonraki
    yenilemede yeniden denenir.
    """
    if teslimat.durum != TeslimatDurumu.HAZIRLANIYOR or not teslimat.saglayici_siparis_no:
        return teslimat

    simdi = timezone.now()
    if (
        not zorla
        and teslimat.son_sorgu
        and (simdi - teslimat.son_sorgu).total_seconds() < SORGU_ARALIGI_SN
    ):
        return teslimat

    teslimat.son_sorgu = simdi
    teslimat.save(update_fields=["son_sorgu"])

    try:
        profil = teslimat.saglayici.adaptor().profil_getir(teslimat.saglayici_siparis_no)
    except SaglayiciHatasi as hata:
        logger.warning("eSIM profili sorgulanamadı (%s): %s", teslimat.islem_no, hata)
        return teslimat
    if profil is None:
        return teslimat

    _profili_kaydet(teslimat, profil)
    return teslimat


def teslimati_iptal_et(teslimat, *, olusturan=None):
    """Profili sağlayıcıda iptal eder, sonra parayı bayiye iade eder.

    Sıra önemli: sağlayıcı iptali reddederse (profil kurulmuş, veri
    kullanılmış) para da iade edilmez — bayi kullandığı paketin parasını
    geri alamaz, biz de sağlayıcıya ödediğimizi alamayız. Sağlayıcı kabul
    edince alış bedeli oradaki bakiyemize döner, satış bedeli bayinin
    cüzdanına.
    """
    if teslimat.durum == TeslimatDurumu.IPTAL:
        return teslimat
    if teslimat.hazir:
        if not teslimat.iptal_edilebilir:
            raise SaglayiciHatasi("Bu profilin sağlayıcı numarası yok; iptal edilemez.")
        teslimat.saglayici.adaptor().iptal_et(
            teslimat.esim_no, iccid=teslimat.iccid, paket_kodu=teslimat.paket_kodu
        )
    elif teslimat.bekliyor:
        raise SaglayiciHatasi(
            "Profil hâlâ hazırlanıyor; hazır olunca iptal edin ya da sağlayıcı panelinden bakın."
        )

    with transaction.atomic():
        teslimat.durum = TeslimatDurumu.IPTAL
        teslimat.save(update_fields=["durum", "guncelleme_tarihi"])
        siparis = teslimat.siparis
        siparis.durum = SiparisDurumu.IPTAL
        siparis.save(update_fields=["durum", "guncelleme_tarihi"])
        siparis_odemesini_geri_al(siparis, olusturan=olusturan)
        siparis.refresh_from_db()
    return teslimat


def esim_siparisi_iptal_et(siparis, *, olusturan=None):
    """`magaza.Siparis` üzerinden gelen iptal isteğini teslimata yönlendirir.

    Yönetici siparişi hangi ekrandan iptal ederse etsin sağlayıcı atlanmaz;
    aksi hâlde bayiye para iade edilir, sağlayıcıdaki profil çalışmaya
    devam ederdi.
    """
    return teslimati_iptal_et(siparis.esim, olusturan=olusturan)


def saglayici_var_mi():
    return Saglayici.objects.filter(aktif=True).exists()


# -- Yükleme (top-up) ----------------------------------------------------
#
# Satılmış eSIM'e yeni paket. Yükleme paketleri kataloğa yazılmaz: hangi
# paketin hangi eSIM'e uyduğunu sağlayıcı bilir, liste her açılışta ondan
# alınır (bir eSIM için birkaç satır). Fiyat kuralı satıştaki gibi: bayi
# grubunun oranı varsa o, yoksa asıl paketin oranı, o da yoksa sağlayıcının
# varsayılanı. Para yine önce düşer, sağlayıcı reddederse geri döner.


def yukleme_orani(teslimat, bayi):
    grup_orani = bayi_kar_orani(bayi)
    if grup_orani is not None:
        return grup_orani
    if teslimat.paket is not None:
        return teslimat.paket.kar_orani
    return teslimat.saglayici.varsayilan_kar_orani


def yukleme_paketleri(teslimat, bayi, kur):
    """Bu eSIM'e yüklenebilecek paketler, bayinin fiyatıyla. Desteklenmiyorsa `SaglayiciHatasi`."""
    veriler = teslimat.saglayici.adaptor().yukleme_paketleri(
        teslimat.esim_no, iccid=teslimat.iccid, paket_kodu=teslimat.paket_kodu
    )
    oran = yukleme_orani(teslimat, bayi)
    tavsiye = tavsiye_orani()
    for veri in veriler:
        veri.satis = satis_fiyati_hesapla(veri.alis_usd, oran, kur)
        veri.tavsiye = tavsiye_fiyati_hesapla(veri.satis, tavsiye) if tavsiye > 0 else None
    veriler.sort(key=lambda v: (v.hacim_bayt, v.sure_gun, v.alis_usd))
    return veriler


def _yukleme_paketi_bul(teslimat, bayi, kur, yukleme_kodu):
    for veri in yukleme_paketleri(teslimat, bayi, kur):
        if veri.kod == yukleme_kodu:
            return veri
    raise SiparisVerilemez("Bu yükleme paketi bu eSIM için geçerli değil.")


def esim_yukle(bayi, teslimat, yukleme_kodu, *, anahtar=None, olusturan=None):
    """Yükleme siparişi: para düşer, sağlayıcıya iletilir; reddederse iade.

    Fiyat sağlayıcının **o anki** listesinden alınır (elle gönderilen kod
    yeniden doğrulanır), bayinin gördüğü rakamla aynı kural.
    """
    if not teslimat.hazir:
        raise SiparisVerilemez("Yalnızca hazır (teslim edilmiş) eSIM'e yükleme yapılır.")
    if teslimat.siparis.bayi_id != bayi.pk:
        raise SiparisVerilemez("Bu eSIM sana ait değil.")

    kur = kur_getir()
    veri = _yukleme_paketi_bul(teslimat, bayi, kur, yukleme_kodu)
    if veri.satis <= 0:
        raise SiparisVerilemez("Bu paketin fiyatı hesaplanamadı.")

    with transaction.atomic():
        if anahtar:
            mevcut = Siparis.objects.filter(islem_anahtari=anahtar).select_related("esim_yukleme").first()
            if mevcut is not None:
                return mevcut.esim_yukleme

        siparis = Siparis.objects.create(
            bayi=bayi,
            urun=None,
            urun_adi=f"eSIM yükleme · {veri.ad}",
            adet=1,
            birim_fiyat=veri.satis,
            tutar=veri.satis,
            islem_anahtari=anahtar or None,
        )
        yukleme = Yukleme.objects.create(
            teslimat=teslimat,
            siparis=siparis,
            paket_kodu=veri.kod,
            paket_adi=veri.ad,
            hacim_bayt=veri.hacim_bayt,
            sure_gun=veri.sure_gun,
            islem_no=uuid4().hex,
            alis_usd=veri.alis_usd,
            kur=kur,
            alis_tl=(veri.alis_usd * kur).quantize(Decimal("0.01")),
            kar_orani=yukleme_orani(teslimat, bayi),
        )
        siparis_odemesini_isle(siparis, olusturan=olusturan or bayi)
        siparis.refresh_from_db()

    try:
        sonuc = teslimat.saglayici.adaptor().yukle(
            teslimat.esim_no, veri.kod, yukleme.islem_no, veri.alis_usd, iccid=teslimat.iccid
        )
    except SaglayiciHatasi as hata:
        logger.warning("eSIM yüklemesi reddedildi (%s): %s", yukleme.islem_no, hata)
        with transaction.atomic():
            yukleme.durum = YuklemeDurumu.HATA
            yukleme.hata = str(hata)
            yukleme.save(update_fields=["durum", "hata", "guncelleme_tarihi"])
            siparis.durum = SiparisDurumu.IPTAL
            siparis.yonetim_notu = f"Sağlayıcı reddetti, tutar iade edildi: {hata}"[:255]
            siparis.save(update_fields=["durum", "yonetim_notu", "guncelleme_tarihi"])
            siparis_odemesini_geri_al(siparis, olusturan=olusturan)
            siparis.refresh_from_db()
        return yukleme

    yukleme.saglayici_yukleme_no = sonuc.yukleme_no
    yukleme.toplam_hacim_bayt = sonuc.toplam_hacim_bayt
    yukleme.son_kullanma = sonuc.son_kullanma
    yukleme.durum = YuklemeDurumu.TAMAM
    yukleme.save()
    # Yükleme teslim edilmiş bir hizmet; sipariş de teslim sayılır.
    siparis.durum = SiparisDurumu.TESLIM
    siparis.save(update_fields=["durum", "guncelleme_tarihi"])
    return yukleme


def musteri_etiketle(teslimat, *, ad="", telefon=""):
    """Bayinin kendi notu: müşteri aradığında eSIM'i bulsun."""
    from apps.bayi.telefon import normalize

    teslimat.musteri_adi = (ad or "").strip()[:120]
    teslimat.musteri_telefonu = normalize(telefon or "")[:30] if telefon else ""
    teslimat.save(update_fields=["musteri_adi", "musteri_telefonu", "guncelleme_tarihi"])
    return teslimat

