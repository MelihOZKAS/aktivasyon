"""Para hareketlerinin tek giriş noktası.

Kural: bakiye/borç yalnızca buradaki fonksiyonlar üzerinden değişir.
Her fonksiyon atomiktir, cüzdanı satır bazında kilitler ve idempotency
anahtarı ile aynı olayın iki kez işlenmesini engeller.

**Bayiye giren her kuruş önce borcu kapatır.** Hakediş de, elle yapılan
bakiye yüklemesi de aynı sırayı izler: borç varsa oradan düşülür, kalanı
bakiyeye yazılır. Böylece cüzdanda aynı anda çekilebilir bakiye ve borç
durmaz; bayinin gördüğü tek rakam gerçekten elindeki paradır.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.finans.models import Cuzdan, CuzdanHareketi, HareketTipi, KuralYonu, UcretKurali

logger = logging.getLogger(__name__)

SIFIR = Decimal("0.00")


def _cuzdani_getir(kullanici_id):
    """Kullanıcının kilitli cüzdanını verir; yoksa açar.

    Elle oluşturulmuş bir kullanıcının cüzdanı olmayabilir. Bu yüzden para
    işlenirken çökmek yerine sıfır bakiyeli cüzdan açılır: işlem tamamlanır,
    bakiye eksiye/borca düşer ve yönetim durumu görür.
    """
    Cuzdan.objects.get_or_create(bayi_id=kullanici_id)
    return Cuzdan.objects.select_for_update().get(bayi_id=kullanici_id)


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

    Tedarikçi kapsamı yalnızca başvuruya bir tedarikçi atanmışsa eşleşir;
    atanmamışsa tedarikçiye özel kurallar devreye girmez.
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
        .filter(kapsam("tedarikci_id", basvuru.tedarikci_id))
        .select_related("kategori", "operator", "tarife", "kampanya")
    )

    secilen = {}
    for kural in adaylar:
        mevcut = secilen.get(kural.yon)
        # Aynı özgüllük ve öncelikte en son eklenen kural kazanır: sonuç
        # rastgele değil, öngörülebilir olsun.
        if mevcut is None or (kural.ozgulluk, kural.oncelik, kural.pk) > (
            mevcut.ozgulluk, mevcut.oncelik, mevcut.pk
        ):
            secilen[kural.yon] = kural
    return secilen


def _tahsilat_adaylari(bayi, kategori):
    """Bu bayi ve kategori için geçerli olabilecek tahsilat kuralları.

    `uygun_kurallari_bul` bir başvuru **ve** bir tetikleyici durum ister;
    burada henüz başvuru yok. Tetikleyici duruma da bakılmaz: soru "bu
    başvuru bayiye kaça mal olacak", "ne zaman tahsil edilecek" değil.
    """
    cuzdan = getattr(bayi, "cuzdan", None)
    grup_id = cuzdan.grup_id if cuzdan else None

    def kapsam(alan, deger):
        return Q(**{f"{alan}__isnull": True}) | Q(**{alan: deger})

    return (
        UcretKurali.objects.filter(aktif=True, yon=KuralYonu.TAHSILAT)
        .filter(kapsam("kategori_id", kategori.pk))
        .filter(kapsam("bayi_grubu_id", grup_id))
        .filter(kapsam("bayi_id", bayi.pk))
        .filter(tedarikci__isnull=True)
    )


def _en_spesifik(kurallar):
    """Aday kurallar arasından uygulanacak olanı seçer."""
    secilen = None
    for kural in kurallar:
        if secilen is None or (kural.ozgulluk, kural.oncelik, kural.pk) > (
            secilen.ozgulluk, secilen.oncelik, secilen.pk
        ):
            secilen = kural
    return secilen


def basvuru_bedeli(bayi, kategori, *, operator=None, tarife=None):
    """Bu başvurunun bayiye maliyeti: bayiden tahsil edilecek tutar.

    Operatör ve tarife biliniyorsa tam tutar, bilinmiyorsa kapsamı onlara
    bağlı olmayan kuralların tutarı döner. Kural yoksa sıfır.
    """
    adaylar = _tahsilat_adaylari(bayi, kategori)
    if operator is not None:
        adaylar = adaylar.filter(Q(operator__isnull=True) | Q(operator=operator))
    else:
        adaylar = adaylar.filter(operator__isnull=True)
    if tarife is not None:
        adaylar = adaylar.filter(Q(tarife__isnull=True) | Q(tarife=tarife))
    else:
        adaylar = adaylar.filter(tarife__isnull=True)

    kural = _en_spesifik(adaylar)
    return kural.tutar if kural else SIFIR


def en_dusuk_basvuru_bedeli(bayi, kategori):
    """Bu kategoride bayiden istenebilecek **en düşük** tutar.

    Kategori ekranında ve form açılışında operatör/tarife henüz belli değil.
    Bayi kategorideki en ucuz seçeneği bile karşılayamıyorsa forma hiç
    girmemeli; karşılayabiliyorsa forma girer ve tam tutar seçim yapılınca
    denetlenir.
    """
    adaylar = list(_tahsilat_adaylari(bayi, kategori))
    if not adaylar:
        return SIFIR

    # Her (operatör, tarife) bileşimi için ayrı bir kural kazanır; en ucuz
    # bileşim bayinin girebileceği en düşük bedeldir.
    gruplar = {}
    for kural in adaylar:
        gruplar.setdefault((kural.operator_id, kural.tarife_id), []).append(kural)

    tutarlar = []
    for anahtar, grup in gruplar.items():
        # Bu bileşime, kapsamı daha geniş olan kurallar da uyar.
        operator_id, tarife_id = anahtar
        uyanlar = [
            k
            for k in adaylar
            if k.operator_id in (None, operator_id) and k.tarife_id in (None, tarife_id)
        ]
        kazanan = _en_spesifik(uyanlar)
        if kazanan is not None:
            tutarlar.append(kazanan.tutar)

    return min(tutarlar) if tutarlar else SIFIR


def basvuru_parasini_isle(basvuru, *, olusturan=None):
    """Başvuru para tetikleyen bir duruma geçtiğinde çağrılır.

    Önce tahsilat (bayiden kesinti), sonra hakediş (bayiye ödeme) işlenir.
    Bakiye yetmezse kalan tutar borca yazılır; borç için üst sınır yoktur.
    """
    with transaction.atomic():
        cuzdan = _cuzdani_getir(basvuru.bayi_id)
        basvuru_kilitli = type(basvuru).objects.select_for_update().get(pk=basvuru.pk)

        if basvuru_kilitli.para_islendi:
            logger.info("Başvuru %s için para zaten işlenmiş.", basvuru_kilitli.referans_no)
            return basvuru_kilitli

        # Sürüm anahtara girer: geri alınmış bir başvuru yeniden işlendiğinde
        # eski anahtara takılıp sessizce yutulmasın.
        surum = basvuru_kilitli.para_surumu

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
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:tahsilat:bakiye",
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
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:tahsilat:borc",
                    aciklama=f"{basvuru_kilitli.referans_no} · {tahsilat_kurali.ad} (borç)",
                    basvuru=basvuru_kilitli,
                    kural=tahsilat_kurali,
                    olusturan=olusturan,
                    borca_yaz=True,
                )
            tahsil_edilen = tutar

        if hakedis_kurali and hakedis_kurali.tutar > SIFIR:
            tutar = hakedis_kurali.tutar
            # Hakediş bir alacaktır: borç varken önce onu kapatır, kalanı
            # bakiyeye geçer. Bakiye yüklemesi de aynı sırayı izler. Aksi
            # hâlde cüzdanda aynı anda çekilebilir bakiye ve borç durur;
            # 100 borcu olan bayi 250 hakediş alınca hem 250'yi çeker hem
            # 100 borçlu görünürdü.
            borctan_dusulen = min(tutar, cuzdan.borc)
            bakiyeye_yazilan = tutar - borctan_dusulen

            if borctan_dusulen > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.BORC_TAHSIL,
                    tutar=-borctan_dusulen,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:hakedis:borc",
                    aciklama=f"{basvuru_kilitli.referans_no} · {hakedis_kurali.ad} (borçtan düşüldü)",
                    basvuru=basvuru_kilitli,
                    kural=hakedis_kurali,
                    olusturan=olusturan,
                    borca_yaz=True,
                )
            if bakiyeye_yazilan > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.HAKEDIS,
                    tutar=bakiyeye_yazilan,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:hakedis",
                    aciklama=f"{basvuru_kilitli.referans_no} · {hakedis_kurali.ad}",
                    basvuru=basvuru_kilitli,
                    kural=hakedis_kurali,
                    olusturan=olusturan,
                )
            hakedis = tutar

        basvuru_kilitli.tahsil_edilen = tahsil_edilen
        basvuru_kilitli.hakedis = hakedis
        basvuru_kilitli.para_islendi = True
        basvuru_kilitli.save(
            update_fields=["tahsil_edilen", "hakedis", "para_islendi", "guncelleme_tarihi"]
        )
        return basvuru_kilitli


def ana_hakedisi_isle(basvuru, *, olusturan=None):
    """İşlemden bize giren ana hakedişi kaydeder.

    Kaynak iki türlü olabilir:

    · **Tedarikçi:** işlemi bir tedarikçi üstlendiyse bedel onun hesabından
      düşer; cüzdan hareketi oluşur.
    · **Operatör:** işlem üstlenilmemişse tutar doğrudan operatörden gelir.
      Operatörün sistemde cüzdanı yok, bu yüzden hareket yazılmaz; tutar
      yalnızca başvuruya işlenir ve kâr hesabına girer.

    Tedarikçi sonradan da atanabildiği için bayi tarafındaki paradan ayrı,
    kendi tekillik anahtarıyla işlenir.
    """
    with transaction.atomic():
        basvuru_kilitli = type(basvuru).objects.select_for_update().get(pk=basvuru.pk)

        if basvuru_kilitli.ana_hakedis_islendi:
            return basvuru_kilitli

        surum = basvuru_kilitli.para_surumu
        kurallar = uygun_kurallari_bul(basvuru_kilitli, basvuru_kilitli.durum)
        kural = kurallar.get(KuralYonu.ANA_HAKEDIS)
        if kural is None or kural.tutar <= SIFIR:
            return basvuru_kilitli

        tutar = kural.tutar

        if basvuru_kilitli.tedarikci_id:
            cuzdan = _cuzdani_getir(basvuru_kilitli.tedarikci_id)
            bakiyeden = min(tutar, max(cuzdan.bakiye, SIFIR))
            borctan = tutar - bakiyeden

            if bakiyeden > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.TEDARIKCI_BEDELI,
                    tutar=-bakiyeden,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:anahakedis:bakiye",
                    aciklama=f"{basvuru_kilitli.referans_no} · {kural.ad}",
                    basvuru=basvuru_kilitli,
                    kural=kural,
                    olusturan=olusturan,
                )
            if borctan > SIFIR:
                _hareket_yaz(
                    cuzdan=cuzdan,
                    tip=HareketTipi.BORC_EKLE,
                    tutar=borctan,
                    idempotency_anahtari=f"basvuru:{basvuru_kilitli.pk}:{surum}:anahakedis:borc",
                    aciklama=f"{basvuru_kilitli.referans_no} · {kural.ad} (borç)",
                    basvuru=basvuru_kilitli,
                    kural=kural,
                    olusturan=olusturan,
                    borca_yaz=True,
                )

        basvuru_kilitli.ana_hakedis = tutar
        basvuru_kilitli.ana_hakedis_islendi = True
        basvuru_kilitli.save(
            update_fields=["ana_hakedis", "ana_hakedis_islendi", "guncelleme_tarihi"]
        )
        return basvuru_kilitli


def basvuru_parasini_geri_al(basvuru, *, olusturan=None):
    """Başvuru para tetikleyen durumdan çıktığında işlenmiş parayı ters kayıtla iptal eder.

    Yalnızca iptal için değil: yanlış başvuru onaylandığında da durum geri
    alınır ve para buradan döner. Defter değişmezdir, satır silinmez; her
    hareketin karşısına ters kaydı yazılır.
    """
    with transaction.atomic():
        basvuru_kilitli = type(basvuru).objects.select_for_update().get(pk=basvuru.pk)

        if not (basvuru_kilitli.para_islendi or basvuru_kilitli.ana_hakedis_islendi):
            return basvuru_kilitli

        hareketler = list(
            basvuru_kilitli.cuzdan_hareketleri.filter(ters_kayit__isnull=True)
            .exclude(tip=HareketTipi.IPTAL)
            .select_related("cuzdan")
        )
        # Hem bayinin hem tedarikçinin cüzdanı kilitlenir.
        cuzdanlar = {
            c.pk: c
            for c in Cuzdan.objects.select_for_update().filter(
                pk__in={h.cuzdan_id for h in hareketler}
            )
        }

        for hareket in hareketler:
            cuzdan = cuzdanlar[hareket.cuzdan_id]
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
        basvuru_kilitli.ana_hakedis = SIFIR
        basvuru_kilitli.para_islendi = False
        basvuru_kilitli.ana_hakedis_islendi = False
        # Sonraki işleme yeni anahtarlarla yazsın: aynı başvuru düzeltilip
        # yeniden onaylandığında para gerçekten hareket etsin.
        basvuru_kilitli.para_surumu = basvuru_kilitli.para_surumu + 1
        basvuru_kilitli.save(
            update_fields=[
                "tahsil_edilen", "hakedis", "ana_hakedis",
                "para_islendi", "ana_hakedis_islendi", "para_surumu",
                "guncelleme_tarihi",
            ]
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
