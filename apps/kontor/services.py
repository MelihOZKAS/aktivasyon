"""Kontör iş kuralları: fiyat, işlem açma, gönderim, sonuç, iade.

Para `apps.finans.services` üzerinden hareket eder (`magaza.Siparis`);
burası işlemi kurar, sağlayıcıyla konuşur ve sonucu kayda yazar.

**Tek gönderim ilkesi.** Sağlayıcıya giden her istek canlı paradır. Kod bir
sağlayıcıya aynı işlemi kendiliğinden ikinci kez göndermez:

  · Gönderim ağa çıkmadan önce `Deneme` olarak yazılır (commit edilir).
    Süreç yarıda ölürse kayıt "Gönderiliyor"da kalır; bir sonraki tur onu
    görünce işlemi **askıya alır**, yeniden göndermez.
  · Cevap anlaşılamazsa (zaman aşımı, 5xx, tanınmayan metin) işlem askıya
    alınır. Yüklenmiş de olabilir; para bayiden düşülü kalır, yönetici
    "Sonucu sorgula / Yüklendi say / Sıradakine gönder / İptal et"ten
    birini seçer.
  · Yalnızca **kesin ret** (sağlayıcı açıkça reddetti ya da bağlantı hiç
    kurulamadı) ya da sonuç sorgusunda **iptal** gelirse sıradaki
    sağlayıcıya geçilir: işlem orada hiç yüklenmedi.
  · "Yüklendi mi?" sorgusu salt okumadır; tekrarlanması zararsızdır.

Aynı işlemi iki süreç (işçi, bayinin sayfası, bayi programının sorgusu,
yönetici) aynı anda yürütmesin diye `Islem.kilit_bitis` süreli sahiplik
tutar; HTTP beklerken veritabanı satırı kilitli kalmaz.
"""

import logging
import threading
from contextlib import contextmanager
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.bayi.telefon import TELEFON_DESENI, normalize
from apps.finans.services import (
    SiparisVerilemez,
    _cuzdani_getir,
    siparis_odemesini_geri_al,
    siparis_odemesini_isle,
)
from apps.kontor.models import (
    ACIK_DURUMLAR,
    Deneme,
    DenemeDurumu,
    Hedef,
    Islem,
    IslemDurumu,
    Kanal,
    Kategori,
    Paket,
    PaketFiyati,
    Rota,
    SaglayiciPaketi,
)
from apps.kontor.saglayicilar import Gonderim, SaglayiciHatasi, Sorgu
from apps.magaza.models import Siparis, SiparisDurumu

logger = logging.getLogger(__name__)

# Bir işlemin sahipliği bu kadar sürer; her gönderimden önce uzatılır.
# Süreç ölürse sahiplik kendiliğinden düşer ve işçi işi devralır.
KILIT_SURESI = timedelta(seconds=90)
# Aynı işlem için sağlayıcıya bu aralıktan sık "yüklendi mi?" sorulmaz;
# bayinin sayfası, bayi programı ve işçi aynı anda soruyor olabilir.
SORGU_ARALIGI = timedelta(seconds=5)
# Panelden aynı numaraya aynı paket, önceki işlem sürerken ya da açıldıktan
# sonraki bu süre içinde ikinci kez açılmaz: yavaş bağlantıda yeniden
# basılan düğme, yenilenen sayfa ya da ikinci sekme iki kez yüklemesin.
TEKRAR_KORUMASI = timedelta(minutes=2)


class YuklemeYapilamaz(SiparisVerilemez):
    """İşlem açılamadı; sebebi mesajda. Para hareket etmedi."""


class IslemMesgul(Exception):
    """İşlemi şu an başka bir süreç yürütüyor."""


class KararVerilemez(Exception):
    """Yöneticinin istediği karar bu durumdaki işleme uygulanamaz."""


# -- Fiyat ve katalog -----------------------------------------------------


def bayi_grubu(bayi):
    cuzdan = getattr(bayi, "cuzdan", None)
    return getattr(cuzdan, "grup", None) if cuzdan else None


def fiyatlandir(paketler, bayi):
    """Her pakete `fiyat` (bayinin ödeyeceği), `tavsiye` ve `kazanc` yazar.

    `fiyat` bayinin grubuna özel fiyat, yoksa paketin fiyatıdır. `tavsiye`
    paketin müşteriye önerilen fiyatıdır (grup değiştirmez); yoksa `None` ve
    ekran bayinin fiyatını düz yazar.
    """
    paketler = list(paketler)
    grup = bayi_grubu(bayi)
    ozel = {}
    if grup is not None and paketler:
        ozel = dict(
            PaketFiyati.objects.filter(grup=grup, paket__in=paketler).values_list("paket_id", "fiyat")
        )
    for paket in paketler:
        paket.fiyat = ozel.get(paket.pk, paket.satis_fiyati)
        paket.tavsiye = paket.tavsiye_fiyati if paket.tavsiye_fiyati else None
        paket.kazanc = (paket.tavsiye - paket.fiyat) if paket.tavsiye is not None else None
    return paketler


def bayi_fiyati(bayi, paket):
    return fiyatlandir([paket], bayi)[0].fiyat


def satistaki_paketler(kategori, bayi):
    """Kategorinin bayiye fiyatı olan, satıştaki paketleri."""
    paketler = fiyatlandir(
        Paket.objects.satista().filter(kategori=kategori).select_related("kategori"), bayi
    )
    return [p for p in paketler if p.fiyat > 0]


def kategori_listesi(*, oyun=False):
    """Satışta en az bir paketi olan kategoriler; kontör ya da oyun bölümü."""
    return (
        Kategori.objects.filter(
            aktif=True, oyun=oyun, pk__in=Paket.objects.satista().values("kategori")
        )
        .select_related("operator")
        .order_by("sira", "operator__sira", "ad")
    )


def hedefi_dogrula(kategori, hedef):
    """Kategorinin istediği biçime indirir; uymuyorsa `YuklemeYapilamaz`."""
    hedef = (hedef or "").strip()
    if kategori.hedef == Hedef.TELEFON:
        numara = normalize(hedef) or ""
        if not TELEFON_DESENI.match(numara):
            raise YuklemeYapilamaz(
                "Numara 10 haneli olmalı ve 5 ile başlamalı (örnek: 532 123 45 67)."
            )
        return numara
    if kategori.hedef == Hedef.HESAP:
        if not hedef:
            raise YuklemeYapilamaz(f"{kategori.hedef_basligi} boş olamaz.")
        if len(hedef) > 64:
            raise YuklemeYapilamaz(f"{kategori.hedef_basligi} en fazla 64 karakter olabilir.")
        return hedef
    return ""


# -- Numara sorgusu -------------------------------------------------------

# Aynı numara bu süre içinde kaynağa ikinci kez sorulmaz: bayi sayfayı
# yenilese de dış siteye tekrar gidilmez.
ONBELLEK_SURESI = 300


def numarayi_sorgula(kategori, hedef, bayi):
    """Kategorinin sorgu kaynağına sorar, sonucu kataloğumuzla eşleştirir.

    Dönüş: `{"numara", "sahip", "eslesen": [Paket], "diger": [SorguPaketi]}`.
    Eşleşme kupür koduyladır (`Paket.kod`); eşleşen pakete bayinin fiyatı
    yazılır. Hat sahibinin maskeli adı yalnızca kategoride açıksa istenir,
    ekranda gösterilir, veritabanına yazılmaz. Taze cevaptaki paketler
    `GorulenPaket` listesine işlenir (yeni paket takibi). Kaynak yoksa, hata
    verirse `SorguHatasi` — ekran sebebini yazar, satış sürer.
    """
    from django.core.cache import cache

    from apps.kontor.sorgu import SorguHatasi, SorguSonucu, kaynak_getir

    kaynak = kaynak_getir(kategori.sorgu_kaynagi) if kategori.sorgu_kaynagi else None
    if kaynak is None:
        raise SorguHatasi("Bu kategoride numara sorgusu tanımlı değil.")
    try:
        numara = hedefi_dogrula(kategori, hedef)
    except YuklemeYapilamaz as hata:
        raise SorguHatasi(str(hata))

    sahip_iste = kategori.sorgu_sahibi_goster
    anahtar = f"kontor-sorgu:{kaynak.kod}:{numara}:{int(sahip_iste)}"
    sonuc = cache.get(anahtar)
    if sonuc is None:
        try:
            sonuc = kaynak.fonksiyon(numara, sahip=sahip_iste)
        except SorguHatasi:
            raise
        except Exception as hata:  # kaynağın kendi hatası satışı düşürmesin
            logger.exception("Numara sorgusu başarısız (%s)", kaynak.kod)
            raise SorguHatasi(f"Sorgu yapılamadı: {hata}")
        if not isinstance(sonuc, SorguSonucu):
            sonuc = SorguSonucu(list(sonuc or []))
        cache.set(anahtar, sonuc, ONBELLEK_SURESI)
        gorulenleri_yaz(kaynak.kod, kategori, sonuc.paketler)

    kodlar = {str(p.kod).strip() for p in sonuc.paketler}
    eslesen = [p for p in satistaki_paketler(kategori, bayi) if p.kod in kodlar]
    bizde = {p.kod for p in eslesen}
    diger = [p for p in sonuc.paketler if str(p.kod).strip() not in bizde]
    return {
        "numara": numara,
        "sahip": sonuc.sahip if sahip_iste else "",
        "eslesen": eslesen,
        "diger": diger,
    }


def gorulenleri_yaz(kaynak_kodu, kategori, paketler):
    """Sorguda görülen paketleri takip listesine işler; hata sorguyu düşürmez.

    Var olanın son görülmesi ve sayısı güncellenir, fiyat değiştiyse eskisi
    `onceki_fiyat`'a geçer. Yönetimin kararı (`yok_say`) korunur.
    """
    from apps.kontor.models import GorulenPaket

    simdi = timezone.now()
    tekil = {str(p.kod).strip()[:60]: p for p in paketler if str(p.kod).strip()}
    if not tekil:
        return
    try:
        with transaction.atomic():
            mevcut = {
                g.kod: g
                for g in GorulenPaket.objects.select_for_update().filter(
                    kaynak=kaynak_kodu, kod__in=tekil
                )
            }
            for kod, veri in tekil.items():
                gorulen = mevcut.get(kod)
                if gorulen is None:
                    GorulenPaket.objects.create(
                        kaynak=kaynak_kodu,
                        kod=kod,
                        kategori=kategori,
                        ad=(veri.ad or "")[:200],
                        aciklama=veri.aciklama or "",
                        fiyat=veri.fiyat,
                        son_gorulme=simdi,
                    )
                    continue
                if veri.fiyat is not None and gorulen.fiyat is not None and veri.fiyat != gorulen.fiyat:
                    gorulen.onceki_fiyat = gorulen.fiyat
                    gorulen.fiyat_degisme = simdi
                if veri.fiyat is not None:
                    gorulen.fiyat = veri.fiyat
                gorulen.ad = (veri.ad or gorulen.ad)[:200]
                gorulen.aciklama = veri.aciklama or gorulen.aciklama
                gorulen.kategori = kategori
                gorulen.son_gorulme = simdi
                gorulen.gorulme_sayisi += 1
                gorulen.save()
    except Exception:
        logger.exception("Görülen paketler yazılamadı (%s)", kaynak_kodu)


def gorulen_paketi_kataloga_ekle(gorulen):
    """Görülen paketi kategorisine paket olarak açar; fiyatsız ve rotasız.

    Satış fiyatı ve sağlayıcı sırası girilmeden paket satılmaz
    (`satista`): açıldığı an bayiye görünmez, yönetici paketi tamamlar.
    Dönüş: (paket, yeni_mi).
    """
    if gorulen.kategori_id is None:
        raise KararVerilemez("Bu paketin hangi kategoride görüldüğü bilinmiyor.")
    return Paket.objects.get_or_create(
        kategori_id=gorulen.kategori_id,
        kod=gorulen.kod,
        defaults={
            "ad": (gorulen.ad or gorulen.kod)[:150],
            "aciklama": gorulen.aciklama[:255],
            # Operatörün fiyatı müşterinin ödeyeceğidir: tavsiye olarak gelir.
            "tavsiye_fiyati": gorulen.fiyat,
        },
    )


# -- İşlem açma -----------------------------------------------------------


def yukleme_baslat(bayi, paket, hedef, *, kanal=Kanal.PANEL, bayi_ref="", anahtar=None, olusturan=None):
    """İşlemi açar, tutarı bakiyeden düşer; gönderim arka planda başlar.

    Bakiye yetmezse ya da hesap işleme kapalıysa hiçbir şey yazılmaz
    (`SiparisVerilemez`). Borca yazılmaz — kontör de bakiyeden alınır.

    İki tekrar koruması var: panelde `anahtar` (formun gizli alanı, sayfa
    yenilenince aynı işlem ikinci kez açılmaz), bayi programında `bayi_ref`
    (aynı referansla gelen ikinci istek aynı işlemi döndürür — program zaman
    aşımına uğrayıp yeniden sorduğunda ikinci yükleme yapılmasın).
    """
    kategori = paket.kategori
    if not (paket.aktif and kategori.aktif) or not Paket.objects.satista().filter(pk=paket.pk).exists():
        raise YuklemeYapilamaz("Bu paket şu an satışta değil.")
    hedef = hedefi_dogrula(kategori, hedef)
    fiyat = bayi_fiyati(bayi, paket)
    if fiyat <= 0:
        raise YuklemeYapilamaz("Bu paketin fiyatı tanımlı değil.")
    bayi_ref = (bayi_ref or "").strip()[:64]

    with transaction.atomic():
        # Bayinin cüzdanı en başta kilitlenir: aynı bayinin eşzamanlı iki
        # isteği (çift dokunuş, ikinci sekme, yavaş bağlantıda yeniden
        # gönderim) burada sıraya girer. İkincisi, birincisi bitince aşağıdaki
        # denetimlerde onun kaydını görür; ikisi birlikte geçip iki kez
        # yükleyemez, parayı iki kez düşemez.
        _cuzdani_getir(bayi.pk)
        if anahtar:
            mevcut = Siparis.objects.filter(islem_anahtari=anahtar, bayi=bayi).select_related("kontor").first()
            if mevcut is not None and hasattr(mevcut, "kontor"):
                return mevcut.kontor
        if bayi_ref:
            mevcut = Islem.objects.filter(bayi=bayi, bayi_ref=bayi_ref).first()
            if mevcut is not None:
                if mevcut.hedef == hedef and mevcut.paket_id == paket.pk:
                    return mevcut
                raise YuklemeYapilamaz("Bu referans numarası daha önce başka bir işlemde kullanıldı.")
        if kanal == Kanal.PANEL and hedef:
            ayni = Islem.objects.filter(bayi=bayi, hedef=hedef, paket=paket)
            if ayni.filter(durum__in=ACIK_DURUMLAR).exists():
                raise YuklemeYapilamaz(
                    "Bu numaraya aynı paket şu an yükleniyor. Sonucu Yüklemelerim'de "
                    "görürsün; ikinci kez gönderme."
                )
            if ayni.filter(
                olusturma_tarihi__gte=timezone.now() - TEKRAR_KORUMASI
            ).exclude(durum=IslemDurumu.IPTAL).exists():
                raise YuklemeYapilamaz(
                    "Bu numaraya aynı paket az önce yüklendi. İkinci kez yüklemek "
                    "istiyorsan iki dakika sonra yeniden dene."
                )

        siparis = Siparis.objects.create(
            bayi=bayi,
            urun=None,
            urun_adi=f"{kategori.ad} · {paket.ad}"[:200],
            adet=1,
            birim_fiyat=fiyat,
            tutar=fiyat,
            islem_anahtari=anahtar or None,
        )
        islem = Islem.objects.create(
            siparis=siparis,
            bayi=bayi,
            paket=paket,
            kategori=kategori,
            paket_adi=paket.ad,
            hedef=hedef,
            tavsiye_fiyati=paket.tavsiye_fiyati or None,
            kanal=kanal,
            bayi_ref=bayi_ref,
        )
        siparis_odemesini_isle(siparis, olusturan=olusturan or bayi)
        transaction.on_commit(partial(arka_planda_isle, islem.pk))
    return islem


def arka_planda_isle(pk):
    """İşlemi ayrı iş parçacığında yürütür; bayi sağlayıcının cevabını beklemez.

    Bildirimdeki kuralın aynısı: dış sistemin yavaşlığı bayinin isteğini
    bekletmesin. İş parçacığı ölürse işçi (`kontor_isle`) ya da bayinin
    sayfası işi devralır. Testler `KONTOR_ARKA_PLAN = False` ile aynı
    iş parçacığında çalıştırır.
    """
    if not getattr(settings, "KONTOR_ARKA_PLAN", True):
        isle(pk)
        return
    threading.Thread(target=_is_parcacigi, args=(pk,), daemon=True).start()


def _is_parcacigi(pk):
    try:
        isle(pk)
    except Exception:
        logger.exception("Kontör işlemi arka planda yürütülemedi (%s)", pk)
    finally:
        connection.close()


# -- Sahiplik -------------------------------------------------------------


def _sahiplen(pk):
    simdi = timezone.now()
    return bool(
        Islem.objects.filter(pk=pk)
        .filter(Q(kilit_bitis__isnull=True) | Q(kilit_bitis__lt=simdi))
        .update(kilit_bitis=simdi + KILIT_SURESI)
    )


def _uzat(pk):
    Islem.objects.filter(pk=pk).update(kilit_bitis=timezone.now() + KILIT_SURESI)


def _birak(pk):
    Islem.objects.filter(pk=pk).update(kilit_bitis=None)


@contextmanager
def sahiplik(pk):
    """İşlemi yalnızca bu süreç yürütsün; alınamazsa `IslemMesgul`."""
    if not _sahiplen(pk):
        raise IslemMesgul("Bu işlem şu an yürütülüyor; birkaç saniye sonra yeniden deneyin.")
    try:
        yield
    finally:
        _birak(pk)


def _getir(pk):
    return Islem.objects.select_related(
        "siparis", "paket", "paket__kategori", "kategori", "saglayici"
    ).get(pk=pk)


# -- Otomatik yürütme -----------------------------------------------------


def isle(pk, *, zorla=False):
    """Sıradaki işlemi gönderir, işlemdekinin sonucunu sorar.

    Sahiplik alınamazsa (başka süreç yürütüyor) sessizce döner. Askıdaki,
    sonuçlanmış işleme dokunulmaz: askıdan çıkarmak yönetimin kararıdır.
    """
    try:
        with sahiplik(pk):
            islem = _getir(pk)
            if islem.durum == IslemDurumu.SIRADA:
                _siradakine_gonder(islem)
            elif islem.durum == IslemDurumu.ISLEMDE:
                _sonucu_sor(islem, zorla=zorla)
            return _getir(pk)
    except IslemMesgul:
        return None


def bekleyenleri_isle():
    """İşçinin bir turu: işlemdekileri sorar, takılan sıradakileri gönderir.

    Sırada bekleyen işlem normalde açıldığı anda arka planda gönderilir;
    birkaç saniyeden eskiyse o iş parçacığı ölmüştür, işçi devralır.
    Dönüş: dokunulan işlem sayısı.
    """
    simdi = timezone.now()
    pkler = list(
        Islem.objects.filter(
            Q(durum=IslemDurumu.ISLEMDE)
            | Q(durum=IslemDurumu.SIRADA, olusturma_tarihi__lt=simdi - timedelta(seconds=10))
        )
        .filter(Q(kilit_bitis__isnull=True) | Q(kilit_bitis__lt=simdi))
        .order_by("olusturma_tarihi")
        .values_list("pk", flat=True)[:200]
    )
    for pk in pkler:
        try:
            isle(pk)
        except Exception:
            logger.exception("Kontör işlemi yürütülemedi (%s)", pk)
    return len(pkler)


def _siradakine_gonder(islem):
    """Denenmemiş sağlayıcılara sırayla gönderir; kabul ya da belirsizde durur."""
    yarim = islem.denemeler.filter(durum=DenemeDurumu.GONDERILIYOR)
    if yarim.exists():
        # Önceki süreç istek atarken öldü: gitti mi gitmedi mi bilinmiyor.
        yarim.update(
            durum=DenemeDurumu.BELIRSIZ,
            gonderim_cevabi="Gönderim sırasında süreç kesildi; sağlayıcının cevabı alınamadı.",
            guncelleme_tarihi=timezone.now(),
        )
        _askiya_al(islem)
        return

    son_ret = ""
    for rota in _kalan_rotalar(islem):
        _uzat(islem.pk)
        deneme = _gonder(islem, rota.saglayici, rota.gidecek_kod, rota.gidecek_operator, rota.gidecek_tip)
        if deneme.durum != DenemeDurumu.REDDEDILDI:
            return  # kabul edildi ya da askıya alındı
        son_ret = _ret_metni(deneme)

    _iptal_et(islem, son_ret or "İşlem hiçbir sağlayıcıda yüklenemedi.")


def _kalan_rotalar(islem):
    if islem.paket_id is None:
        return []
    denenen = islem.denemeler.values_list("saglayici_id", flat=True)
    return list(
        Rota.objects.filter(paket_id=islem.paket_id, aktif=True, saglayici__aktif=True)
        .exclude(saglayici_id__in=denenen)
        .select_related("saglayici", "paket", "paket__kategori")
    )


def _ret_metni(deneme):
    return (deneme.sonuc_cevabi or deneme.gonderim_cevabi or "").strip()[:200]


def _gonder(islem, saglayici, kod, operator, tip, *, elle=False):
    """Tek bir gönderim. Deneme ağa çıkmadan önce yazılır."""
    if connection.in_atomic_block and getattr(settings, "KONTOR_ATOMIK_DENETIMI", True):
        # Açık bir transaction'da deneme commit edilmez; süreç düşerse kayıt
        # kaybolur ve işlem ikinci kez gönderilir. Çağıran görünüm
        # `non_atomic_requests` olmalı. (Testler TestCase içinde kapatır.)
        raise RuntimeError("Kontör gönderimi transaction içinden yapılamaz.")
    deneme = Deneme.objects.create(
        islem=islem,
        saglayici=saglayici,
        ref=saglayici.yeni_ref(),
        uzak_kod=kod,
        uzak_operator=operator,
        uzak_tip=tip,
        elle=elle,
    )
    islem.saglayici = saglayici
    islem.save(update_fields=["saglayici", "guncelleme_tarihi"])

    try:
        sonuc = saglayici.adaptor().gonder(
            ref=deneme.ref, hedef=islem.hedef, uzak_kod=kod, uzak_operator=operator, uzak_tip=tip
        )
    except SaglayiciHatasi as hata:
        deneme.gonderim_cevabi = str(hata)
        if hata.kesin_gitmedi:
            deneme.durum = DenemeDurumu.REDDEDILDI
            deneme.save()
            return deneme
        deneme.durum = DenemeDurumu.BELIRSIZ
        deneme.save()
        _askiya_al(islem)
        return deneme
    except Exception as hata:  # adaptör hatası: istek gitmiş olabilir
        logger.exception("Kontör gönderiminde beklenmeyen hata (%s)", deneme.ref)
        deneme.gonderim_cevabi = f"Beklenmeyen hata: {hata}"
        deneme.durum = DenemeDurumu.BELIRSIZ
        deneme.save()
        _askiya_al(islem)
        return deneme

    deneme.gonderim_cevabi = sonuc.ham[:2000] or sonuc.mesaj
    if sonuc.durum == Gonderim.KABUL:
        deneme.durum = DenemeDurumu.ISLEMDE
        deneme.uzak_ref = sonuc.uzak_ref[:64]
        deneme.alis = sonuc.alis
        deneme.save()
        islem.durum = IslemDurumu.ISLEMDE
        islem.save(update_fields=["durum", "guncelleme_tarihi"])
    elif sonuc.durum == Gonderim.RED:
        deneme.durum = DenemeDurumu.REDDEDILDI
        deneme.save()
    else:
        deneme.durum = DenemeDurumu.BELIRSIZ
        deneme.save()
        _askiya_al(islem)
    return deneme


def _askiya_al(islem):
    islem.durum = IslemDurumu.ASKIDA
    islem.save(update_fields=["durum", "guncelleme_tarihi"])


def _sonucu_sor(islem, *, zorla=False):
    deneme = islem.denemeler.filter(durum=DenemeDurumu.ISLEMDE).select_related("saglayici").last()
    if deneme is None:
        # İşlemde görünüyor ama kabul edilmiş gönderim yok: tutarsız, yönetici baksın.
        _askiya_al(islem)
        return

    simdi = timezone.now()
    if not zorla and islem.son_sorgu and simdi - islem.son_sorgu < SORGU_ARALIGI:
        return
    islem.son_sorgu = simdi
    islem.save(update_fields=["son_sorgu"])

    sonuc = _sor(deneme)
    if sonuc is None or sonuc.durum == Sorgu.ISLEMDE:
        return
    if sonuc.durum == Sorgu.BASARILI:
        _basarili(islem, deneme, mesaj=sonuc.mesaj, alis=sonuc.alis)
        return
    # İptal: sağlayıcı yüklemedi, para orada düşmedi; sıradakine geçilir.
    deneme.durum = DenemeDurumu.REDDEDILDI
    deneme.save(update_fields=["durum", "guncelleme_tarihi"])
    islem.durum = IslemDurumu.SIRADA
    islem.save(update_fields=["durum", "guncelleme_tarihi"])
    _siradakine_gonder(islem)


def _sor(deneme):
    """Sağlayıcıya sorar, cevabı denemeye yazar. Ağ hatasında `None`."""
    try:
        sonuc = deneme.saglayici.adaptor().sorgula(ref=deneme.ref, uzak_ref=deneme.uzak_ref)
    except SaglayiciHatasi as hata:
        logger.warning("Kontör sonucu sorulamadı (%s): %s", deneme.ref, hata)
        deneme.sonuc_cevabi = f"Sorgu hatası: {hata}"
        deneme.save(update_fields=["sonuc_cevabi", "guncelleme_tarihi"])
        return None
    deneme.sonuc_cevabi = sonuc.ham[:2000] or sonuc.mesaj
    deneme.save(update_fields=["sonuc_cevabi", "guncelleme_tarihi"])
    return sonuc


def _rota_alisi(islem, saglayici):
    if islem.paket_id is None:
        return None
    return (
        Rota.objects.filter(paket_id=islem.paket_id, saglayici=saglayici)
        .values_list("alis_fiyati", flat=True)
        .first()
    )


def _basarili(islem, deneme, *, mesaj="", alis=None, olusturan=None):
    with transaction.atomic():
        kilitli = Islem.objects.select_for_update().select_related("siparis").get(pk=islem.pk)
        if not kilitli.acik:
            return kilitli
        if alis is None:
            alis = deneme.alis if deneme is not None and deneme.alis is not None else None
        if deneme is not None:
            if alis is None:
                alis = _rota_alisi(kilitli, deneme.saglayici)
            deneme.durum = DenemeDurumu.BASARILI
            deneme.alis = alis
            deneme.save(update_fields=["durum", "alis", "guncelleme_tarihi"])
            kilitli.saglayici = deneme.saglayici

        kilitli.durum = IslemDurumu.BASARILI
        kilitli.sonuc_mesaji = (mesaj or "").strip() or "Yüklendi."
        kilitli.alis_tutari = alis
        kilitli.sonuc_tarihi = timezone.now()
        kilitli.save()

        siparis = kilitli.siparis
        if siparis.durum == SiparisDurumu.VERILDI:
            siparis.durum = SiparisDurumu.TESLIM
            siparis.save(update_fields=["durum", "guncelleme_tarihi"])
    return kilitli


def _iptal_et(islem, mesaj, *, olusturan=None):
    """İşlemi kapatır, tutarı ters kayıtla bayiye iade eder."""
    with transaction.atomic():
        kilitli = Islem.objects.select_for_update().select_related("siparis").get(pk=islem.pk)
        if kilitli.durum == IslemDurumu.IPTAL:
            return kilitli
        kilitli.durum = IslemDurumu.IPTAL
        kilitli.sonuc_mesaji = (mesaj or "").strip() or "İşlem iptal edildi."
        kilitli.sonuc_tarihi = timezone.now()
        kilitli.save()

        siparis = kilitli.siparis
        siparis.durum = SiparisDurumu.IPTAL
        siparis.yonetim_notu = f"İade edildi: {kilitli.sonuc_mesaji}"[:255]
        siparis.save(update_fields=["durum", "yonetim_notu", "guncelleme_tarihi"])
        siparis_odemesini_geri_al(siparis, olusturan=olusturan)
    return kilitli


# -- Yöneticinin kararları ------------------------------------------------
#
# Hepsi sahiplik alır (işçiyle yarışmasın) ve sonucu `KararVerilemez` ya da
# `IslemMesgul` ile söyler. Para yine yalnızca `_basarili` / `_iptal_et`
# üzerinden hareket eder.


def sonucu_sorgula(islem):
    """Sağlayıcıya "yüklendi mi?" diye sorar. Hiçbir şey göndermez.

    Askıdaki işlemde son gönderimin sonucu sorulur: sağlayıcı "başarılı"
    derse işlem yüklendi sayılır, "işlemde" derse işlemdeye döner ve takip
    kendiliğinden sürer. "İptal" derse işlem **askıda kalır** — yönetici
    sıradakine göndermeyi ya da iade etmeyi kendisi seçer.
    """
    with sahiplik(islem.pk):
        islem = _getir(islem.pk)
        if not islem.acik:
            raise KararVerilemez("İşlem sonuçlanmış; sorulacak bir şey yok.")
        deneme = (
            islem.denemeler.exclude(durum__in=(DenemeDurumu.REDDEDILDI, DenemeDurumu.BASARILI))
            .select_related("saglayici")
            .last()
        )
        if deneme is None:
            raise KararVerilemez("Bu işlem henüz hiçbir sağlayıcıya gönderilmedi.")
        islem.son_sorgu = timezone.now()
        islem.save(update_fields=["son_sorgu"])
        sonuc = _sor(deneme)
        if sonuc is None:
            raise KararVerilemez(f"Sağlayıcıya ulaşılamadı: {deneme.sonuc_cevabi}")
        if sonuc.durum == Sorgu.BASARILI:
            _basarili(islem, deneme, mesaj=sonuc.mesaj, alis=sonuc.alis)
            return "basarili"
        if sonuc.durum == Sorgu.ISLEMDE:
            deneme.durum = DenemeDurumu.ISLEMDE
            deneme.save(update_fields=["durum", "guncelleme_tarihi"])
            islem.durum = IslemDurumu.ISLEMDE
            islem.save(update_fields=["durum", "guncelleme_tarihi"])
            return "islemde"
        deneme.durum = DenemeDurumu.REDDEDILDI
        deneme.save(update_fields=["durum", "guncelleme_tarihi"])
        if islem.durum == IslemDurumu.ISLEMDE:
            # Olağan akış: iptal gelen işlem sıradakine gider.
            islem.durum = IslemDurumu.SIRADA
            islem.save(update_fields=["durum", "guncelleme_tarihi"])
            _siradakine_gonder(islem)
        return "iptal"


def yuklendi_say(islem, *, alis=None, mesaj="", olusturan=None):
    """Yönetici sağlayıcının panelinden baktı, yüklenmiş: işlem kapanır."""
    with sahiplik(islem.pk):
        islem = _getir(islem.pk)
        if not islem.acik:
            raise KararVerilemez("İşlem zaten sonuçlanmış.")
        deneme = (
            islem.denemeler.exclude(durum=DenemeDurumu.REDDEDILDI).select_related("saglayici").last()
        )
        return _basarili(islem, deneme, mesaj=mesaj, alis=alis, olusturan=olusturan)


def iptal_et(islem, *, mesaj="", olusturan=None):
    """İşlemi kapatır ve tutarı bayiye iade eder.

    Yüklenmiş işlemde de yapılabilir (sağlayıcı sonradan geri aldıysa) ama
    iade bizden çıkar; onay ekranı bunu yazar.
    """
    with sahiplik(islem.pk):
        islem = _getir(islem.pk)
        if islem.durum == IslemDurumu.IPTAL:
            raise KararVerilemez("İşlem zaten iptal edilmiş.")
        return _iptal_et(islem, mesaj or "Yönetim iptal etti.", olusturan=olusturan)


def elle_gonder(islem, saglayici, *, olusturan=None):
    """Askıdaki işlemi yöneticinin seçtiği sağlayıcıya gönderir.

    **Tek bilinçli yeniden gönderim yolu budur.** Önceki gönderimin sonucu
    belirsizse bu, numaraya iki kez yükleme demek olabilir; onay ekranı
    yöneticiye önce "Sonucu sorgula"yı ya da sağlayıcının panelini
    göstermesini söyler. Sağlayıcı reddederse işlem askıda kalır —
    kendiliğinden başka yere gitmez.
    """
    with sahiplik(islem.pk):
        islem = _getir(islem.pk)
        if islem.durum != IslemDurumu.ASKIDA:
            raise KararVerilemez("Yalnızca askıdaki işlem elle gönderilir.")
        if not saglayici.aktif:
            raise KararVerilemez(f"{saglayici} kapalı.")
        rota = Rota.objects.filter(paket_id=islem.paket_id, saglayici=saglayici).first()
        paket = islem.paket
        kod = rota.gidecek_kod if rota else (paket.kod if paket else "")
        operator = rota.gidecek_operator if rota else (islem.kategori.api_operator if islem.kategori else "")
        tip = rota.gidecek_tip if rota else (islem.kategori.api_tip if islem.kategori else "")
        if not kod:
            raise KararVerilemez("Paket silinmiş; gönderilecek kod bilinmiyor.")

        islem.durum = IslemDurumu.SIRADA
        islem.save(update_fields=["durum", "guncelleme_tarihi"])
        deneme = _gonder(islem, saglayici, kod, operator, tip, elle=True)
        if deneme.durum == DenemeDurumu.REDDEDILDI:
            _askiya_al(islem)
        return deneme


# -- Sağlayıcı fiyat listesi ---------------------------------------------


def fiyat_listesini_cek(saglayici):
    """Sağlayıcının fiyat listesini çeker, rotaların alış fiyatını günceller.

    Liste yalnızca bilgidir; satış fiyatına dokunulmaz — onu yönetim
    belirler. Dönüş: (listedeki satır, alışı güncellenen rota) sayıları.
    """
    veriler = saglayici.adaptor().paketleri_getir()
    fiyatlar = {v.kod: v.fiyat for v in veriler}
    with transaction.atomic():
        SaglayiciPaketi.objects.filter(saglayici=saglayici).delete()
        SaglayiciPaketi.objects.bulk_create(
            [
                SaglayiciPaketi(
                    saglayici=saglayici,
                    kod=v.kod[:60],
                    ad=v.ad[:200],
                    fiyat=v.fiyat,
                    operator=v.operator[:60],
                    tip=v.tip[:60],
                )
                for v in {v.kod: v for v in veriler}.values()
            ]
        )
        guncellenen = 0
        for rota in Rota.objects.filter(saglayici=saglayici).select_related("paket"):
            fiyat = fiyatlar.get(rota.gidecek_kod)
            if fiyat is not None and fiyat != rota.alis_fiyati:
                rota.alis_fiyati = fiyat
                rota.save(update_fields=["alis_fiyati"])
                guncellenen += 1
        saglayici.son_liste_cekme = timezone.now()
        saglayici.save(update_fields=["son_liste_cekme", "guncelleme_tarihi"])
    return len(fiyatlar), guncellenen


def tavsiyeyi_operatorden_al(paketler):
    """Seçili paketlerin tavsiye fiyatını operatör sorgusunda görülen fiyattan yazar.

    Eşleşme kategori + kupür kodudur. Operatörde hiç görülmemiş paket
    atlanır. Dönüş: (güncellenen, atlanan).
    """
    from apps.kontor.models import GorulenPaket

    guncellenen = atlanan = 0
    for paket in paketler:
        fiyat = (
            GorulenPaket.objects.filter(kategori_id=paket.kategori_id, kod=paket.kod, fiyat__isnull=False)
            .order_by("-son_gorulme")
            .values_list("fiyat", flat=True)
            .first()
        )
        if fiyat is None:
            atlanan += 1
            continue
        if paket.tavsiye_fiyati != fiyat:
            paket.tavsiye_fiyati = fiyat
            paket.save(update_fields=["tavsiye_fiyati", "guncelleme_tarihi"])
        guncellenen += 1
    return guncellenen, atlanan


def acik_islemler():
    return Islem.objects.filter(durum__in=ACIK_DURUMLAR)
