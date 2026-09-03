"""Para hareketlerinin tek giriş noktası.

Kural: bakiye/borç yalnızca buradaki fonksiyonlar üzerinden değişir.
Her fonksiyon atomiktir, cüzdanı satır bazında kilitler ve idempotency
anahtarı ile aynı olayın iki kez işlenmesini engeller.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.finans.models import Cuzdan, CuzdanHareketi, HareketTipi, KuralYonu, UcretKurali

logger = logging.getLogger(__name__)

SIFIR = Decimal("0.00")


def _hareket_yaz(
    *,
    cuzdan,
    tip,
    tutar,
    idempotency_anahtari,
    aciklama="",
    basvuru=None,
    kural=None,
    banka=None,
    olusturan=None,
    borca_yaz=False,
):
    """Cüzdanı günceller ve defter kaydını oluşturur.

    `borca_yaz=True` ise tutar bakiyeden değil borç hanesinden işlenir.
    Çağıran fonksiyon `transaction.atomic` içinde ve cüzdanı kilitlemiş olmalıdır.
    Aynı anahtarla ikinci kez çağrılırsa hiçbir şey yapmadan None döner.
    """
    onceki_bakiye = cuzdan.bakiye
    onceki_borc = cuzdan.borc

    if borca_yaz:
        cuzdan.borc = onceki_borc + tutar
    else:
        cuzdan.bakiye = onceki_bakiye + tutar

    try:
        with transaction.atomic():
            hareket = CuzdanHareketi.objects.create(
                cuzdan=cuzdan,
                tip=tip,
                tutar=tutar,
                onceki_bakiye=onceki_bakiye,
                sonraki_bakiye=cuzdan.bakiye,
                onceki_borc=onceki_borc,
                sonraki_borc=cuzdan.borc,
                basvuru=basvuru,
                kural=kural,
                banka=banka,
                idempotency_anahtari=idempotency_anahtari,
                aciklama=aciklama,
                olusturan=olusturan,
            )
    except IntegrityError:
        # Aynı olay daha önce işlenmiş; cüzdanı geri al ve sessizce çık.
        cuzdan.bakiye = onceki_bakiye
        cuzdan.borc = onceki_borc
        logger.info("Tekrarlanan para hareketi atlandı: %s", idempotency_anahtari)
        return None

    cuzdan.save(update_fields=["bakiye", "borc", "guncelleme_tarihi"])
    return hareket


def uygun_kurallari_bul(basvuru, durum):
    """Başvuruya uyan ücret kurallarını yön başına bir tane olacak şekilde seçer.

    Kapsam alanı boş olan kural "hepsi" demektir. Aday kurallar arasından
    en spesifik olan, eşitlikte önceliği yüksek olan kazanır.
    """
    bugun = basvuru.olusturma_tarihi.date()
    cuzdan = getattr(basvuru.bayi, "cuzdan", None)
    grup_id = cuzdan.grup_id if cuzdan else None

    def kapsam(alan, deger):
        return Q(**{f"{alan}__isnull": True}) | Q(**{alan: deger})

    adaylar = (
        UcretKurali.objects.filter(aktif=True, tetikleyici_durum=durum)
        .filter(Q(baslangic_tarihi__isnull=True) | Q(baslangic_tarihi__lte=bugun))
        .filter(Q(bitis_tarihi__isnull=True) | Q(bitis_tarihi__gte=bugun))
        .filter(kapsam("kategori_id", basvuru.kategori_id))
        .filter(kapsam("operator_id", basvuru.operator_id))
        .filter(kapsam("tarife_id", basvuru.tarife_id))
        .filter(kapsam("kampanya_id", basvuru.kampanya_id))
        .filter(kapsam("bayi_grubu_id", grup_id))
        .filter(kapsam("bayi_id", basvuru.bayi_id))
        .select_related("kategori", "operator", "tarife", "kampanya")
    )

    secilen = {}
    for kural in adaylar:
        mevcut = secilen.get(kural.yon)
        if mevcut is None or (kural.ozgulluk, kural.oncelik) > (mevcut.ozgulluk, mevcut.oncelik):
            secilen[kural.yon] = kural
    return secilen


def basvuru_parasini_isle(basvuru, *, olusturan=None):
    """Başvuru para tetikleyen bir duruma geçtiğinde çağrılır.

    Önce tahsilat (bayiden kesinti), sonra hakediş (bayiye ödeme) işlenir.
    Bakiye yetmezse kalan tutar borca yazılır; borç için üst sınır yoktur.
    """
    with transaction.atomic():
        cuzdan = Cuzdan.objects.select_for_update().get(bayi_id=basvuru.bayi_id)
        basvuru_kilitli = type(basvuru).objects.select_for_update().get(pk=basvuru.pk)

        if basvuru_kilitli.para_islendi:
            logger.info("Başvuru %s için para zaten işlenmiş.", basvuru_kilitli.referans_no)
            return basvuru_kilitli

        kurallar = uygun_kurallari_bul(basvuru_kilitli, basvuru_kilitli.durum)
        tahsilat_kurali = kurallar.get(KuralYonu.TAHSILAT)
        hakedis_kurali = kurallar.get(KuralYonu.HAKEDIS)

        tahsil_edilen = SIFIR
        hakedis = SIFIR

        if tahsilat_kurali and tahsilat_kurali.tutar > SIFIR:
            tutar = tahsilat_kurali.tutar
            # Borç için üst sınır yok: bakiye yetiyorsa bakiyeden, yetmiyorsa
            # kalanı borca yazılır. Bayiyi tamamen durdurmak gerekirse
            # cüzdandaki `islem_yapabilir` kapatılır.
            bakiyeden = min(tutar, max(cuzdan.bakiye, SIFIR))
            borctan = tutar - bakiyeden

            if bakiyeden > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.TAHSILAT,
                    tutar=-bakiyeden,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:tahsilat:bakiye",
                    aciklama=f"{basvuru_kilitli.referans_no} · {tahsilat_kurali.ad}",
                    basvuru=basvuru_kilitli,
                    kural=tahsilat_kurali,
                    olusturan=olusturan,
                )
            if borctan > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.BORC_EKLE,
                    tutar=borctan,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:tahsilat:borc",
                    aciklama=f"{basvuru_kilitli.referans_no} · {tahsilat_kurali.ad} (borç)",
                    basvuru=basvuru_kilitli,
                    kural=tahsilat_kurali,
                    olusturan=olusturan,
                    borca_yaz=True,
                )
            tahsil_edilen = tutar

        if hakedis_kurali and hakedis_kurali.tutar > SIFIR:
            _hareket_yaz(
                cuzdan=cuzdan,
                tip=HareketTipi.HAKEDIS,
                tutar=hakedis_kurali.tutar,
                idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:hakedis",
                aciklama=f"{basvuru_kilitli.referans_no} · {hakedis_kurali.ad}",
                basvuru=basvuru_kilitli,
                kural=hakedis_kurali,
                olusturan=olusturan,
            )
            hakedis = hakedis_kurali.tutar

        basvuru_kilitli.tahsil_edilen = tahsil_edilen
        basvuru_kilitli.hakedis = hakedis
        basvuru_kilitli.para_islendi = True
        basvuru_kilitli.save(
            update_fields=["tahsil_edilen", "hakedis", "para_islendi", "guncelleme_tarihi"]
        )
        return basvuru_kilitli


def basvuru_parasini_geri_al(basvuru, *, olusturan=None):
    """Başvuru olumsuz bir duruma döndüğünde işlenmiş parayı ters kayıtla iptal eder."""
    with transaction.atomic():
        cuzdan = Cuzdan.objects.select_for_update().get(bayi_id=basvuru.bayi_id)
        basvuru_kilitli = type(basvuru).objects.select_for_update().get(pk=basvuru.pk)

        if not basvuru_kilitli.para_islendi:
            return basvuru_kilitli

        hareketler = basvuru_kilitli.cuzdan_hareketleri.filter(
            ters_kayit__isnull=True
        ).exclude(tip=HareketTipi.IPTAL)

        for hareket in hareketler:
            borca_yaziliyordu = hareket.tip in {HareketTipi.BORC_EKLE, HareketTipi.BORC_TAHSIL}
            ters = _hareket_yaz(
                cuzdan=cuzdan,
                tip=HareketTipi.IPTAL,
                tutar=-hareket.tutar,
                idempotency_anahtari=f"iptal:{hareket.pk}",
                aciklama=f"{basvuru_kilitli.referans_no} · iptal ({hareket.get_tip_display()})",
                basvuru=basvuru_kilitli,
                kural=hareket.kural,
                olusturan=olusturan,
                borca_yaz=borca_yaziliyordu,
            )
            if ters:
                hareket.ters_kayit = ters
                hareket.save(update_fields=["ters_kayit"])

        basvuru_kilitli.tahsil_edilen = SIFIR
        basvuru_kilitli.hakedis = SIFIR
        basvuru_kilitli.para_islendi = False
        basvuru_kilitli.save(
            update_fields=["tahsil_edilen", "hakedis", "para_islendi", "guncelleme_tarihi"]
        )
        return basvuru_kilitli


def bakiye_yukle(cuzdan, tutar, *, aciklama="", banka=None, olusturan=None, anahtar=None):
    """Manuel bakiye yüklemesi. Borç varsa önce borçtan düşer, kalanı bakiyeye yazar."""
    if tutar <= SIFIR:
        raise ValueError("Yükleme tutarı sıfırdan büyük olmalıdır.")

    with transaction.atomic():
        cuzdan = Cuzdan.objects.select_for_update().get(pk=cuzdan.pk)
        anahtar = anahtar or f"yukleme:{cuzdan.pk}:{CuzdanHareketi.objects.count()}"

        borctan_dusulen = min(tutar, cuzdan.borc)
        bakiyeye_yazilan = tutar - borctan_dusulen

        if borctan_dusulen > SIFIR:
            _hareket_yaz(
                cuzdan=cuzdan,
                tip=HareketTipi.BORC_TAHSIL,
                tutar=-borctan_dusulen,
                idempotency_anahtari=f"{anahtar}:borc",
                aciklama=aciklama or "Borç kapatma",
                banka=banka,
                olusturan=olusturan,
                borca_yaz=True,
            )
        if bakiyeye_yazilan > SIFIR:
            _hareket_yaz(
                cuzdan=cuzdan,
                tip=HareketTipi.YUKLEME,
                tutar=bakiyeye_yazilan,
                idempotency_anahtari=f"{anahtar}:bakiye",
                aciklama=aciklama or "Bakiye yükleme",
                banka=banka,
                olusturan=olusturan,
            )

        if banka and tutar > SIFIR:
            banka.bakiye = banka.bakiye + tutar
            banka.save(update_fields=["bakiye", "guncelleme_tarihi"])

        return cuzdan
