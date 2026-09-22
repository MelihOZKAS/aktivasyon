"""Başvuru yan işlemleri."""

import logging

from django.db import transaction

from apps.basvurular.models import BasvuruDurumu
from apps.bayi.models import SimKart, SimKartDurumu
from apps.bayi.services import sim_arizali_isaretle

logger = logging.getLogger(__name__)


# --- SIM değişimi ---------------------------------------------------------
#
# Bozuk kart için para hareketi yoktur, kart takası vardır. Başvuru iptal
# edilip yeniden girilseydi giriş bedeli iade edilir, güncel fiyattan yeniden
# kesilirdi; bayi 100'e aldığı işi 150'ye almış olurdu. Aynı başvuruda kartı
# değiştirmek parayı olduğu yerde bırakır.


class SimDegisimiHatasi(Exception):
    """SIM değişimi yapılamadı; sebebi mesajda."""


def bayi_duzenleyebilir_durumlar():
    """Bozuk SIM'de başvurunun düşürüleceği durumlar (veridir, kodda ad yok)."""
    return BasvuruDurumu.objects.filter(aktif=True, bayi_duzenleyebilir=True).order_by(
        "sira", "ad"
    )


def sim_bozuk_bildir(basvuru, kart, *, bildiren, aciklama="", hedef_durum=None):
    """Aktivasyonda bozuk çıkan kartı arızalıya düşürür, başvuruyu bayinin
    düzenleyebildiği duruma çeker.

    Yönetim ya da tedarikçi bildirir; bayi kendi panelinden bildirmez.
    Sonuçlanmış başvuruya uygulanmaz: hat açıldıktan sonra bozulan kart
    ayrı bir iştir (SIM değişimi kategorisi), bu akışın konusu değil.
    """
    if basvuru.sonuclandi_mi:
        raise SimDegisimiHatasi(
            "Bu işlem sonuçlandı; SIM değişimi yalnızca aktivasyon tamamlanmadan yapılır."
        )
    if kart.basvuru_id != basvuru.pk or kart.durum != SimKartDurumu.KULLANILDI:
        raise SimDegisimiHatasi(f"{kart.imei} bu başvuruda takılı bir kart değil.")

    hedef = hedef_durum or bayi_duzenleyebilir_durumlar().first()
    if hedef is None or not hedef.bayi_duzenleyebilir or not hedef.aktif:
        raise SimDegisimiHatasi(
            "Bayinin düzenleyebileceği bir durum tanımlı değil. Başvuru "
            "Durumları'nda bir durumda “Bayi düzenleyebilir” kutusunu açın."
        )

    with transaction.atomic():
        sim_arizali_isaretle(kart, bildiren=bildiren)
        if basvuru.durum_id != hedef.pk:
            basvuru.durum = hedef
            basvuru._degistiren = bildiren
            not_ = f"SIM kart bozuk çıktı ({kart.imei}); bayi stoğundan yeni kart seçecek."
            if aciklama:
                not_ = f"{not_} {aciklama}"
            basvuru._aciklama = not_[:255]
            basvuru.save(update_fields=["durum", "guncelleme_tarihi"])

    logger.info("Başvuru %s: SIM %s bozuk bildirildi.", basvuru.referans_no, kart.imei)
    return basvuru


def _onceki_durum(basvuru):
    """Bozuk SIM bildirilmeden önce başvuru hangi durumdaydı?

    Son durum geçmişi kaydının "önceki"sidir. Kapanmış ya da yine bayinin
    düzenlediği bir durumsa başlangıç durumuna düşülür — iş kuyruğa geri
    girsin, yönetim yeni kartı görsün.
    """
    son = basvuru.durum_gecmisi.select_related("onceki_durum").order_by("-tarih", "-pk").first()
    onceki = son.onceki_durum if son else None
    if onceki is not None and onceki.aktif and not onceki.bayi_duzenleyebilir:
        return onceki
    return BasvuruDurumu.objects.filter(aktif=True, baslangic_durumu=True).first()


def simi_degistir(basvuru, eski_kart, yeni_kart, *, degistiren):
    """Bayi bozuk kartın yerine stoğundan yeni kart takar; başvuru bildirim
    öncesi durumuna döner.

    Para hiç oynamaz. Eski kart arızalı kalır (arıza takibi onu ayrıca
    kapatır), başvurudaki IMEI yenisiyle değişir, yeni kart "Kullanıldı"
    olur. Yeni kart bayinin stoğunda ve başvurunun operatörüne ait olmalı.
    """
    if not basvuru.sim_degisimi_bekliyor:
        raise SimDegisimiHatasi("Bu başvuruda SIM değişimi beklenmiyor.")
    if eski_kart.pk not in {k.pk for k in basvuru.bozuk_simler}:
        raise SimDegisimiHatasi(f"{eski_kart.imei} bu başvuruda değişim bekleyen bir kart değil.")
    if yeni_kart.bayi_id != basvuru.bayi_id or yeni_kart.durum != SimKartDurumu.ATANDI:
        raise SimDegisimiHatasi("Bu SIM kart stoğunuzda değil.")
    if (
        basvuru.operator_id
        and yeni_kart.operator_id
        and yeni_kart.operator_id != basvuru.operator_id
    ):
        raise SimDegisimiHatasi(
            f"Bu SIM kart {yeni_kart.operator.ad} kartı; "
            f"{basvuru.operator.ad} aktivasyonunda kullanılamaz."
        )

    with transaction.atomic():
        # Eşzamanlı iki başvuru aynı kartı takamaz; yalnızca hâlâ stoktaysa.
        adet = SimKart.objects.filter(pk=yeni_kart.pk, durum=SimKartDurumu.ATANDI).update(
            durum=SimKartDurumu.KULLANILDI, basvuru=basvuru
        )
        if not adet:
            raise SimDegisimiHatasi("Bu SIM kart az önce başka bir başvuruda kullanıldı.")

        for kod, imei in basvuru.sim_degerleri().items():
            if imei == eski_kart.imei:
                basvuru.ek_bilgiler[kod] = yeni_kart.imei

        basvuru.durum = _onceki_durum(basvuru) or basvuru.durum
        basvuru._degistiren = degistiren
        basvuru._aciklama = f"Bayi yeni SIM kart taktı: {yeni_kart.imei} ({eski_kart.imei} yerine)."
        basvuru.save(update_fields=["ek_bilgiler", "durum", "guncelleme_tarihi"])

    logger.info(
        "Başvuru %s: SIM %s yerine %s takıldı.", basvuru.referans_no, eski_kart.imei, yeni_kart.imei
    )
    return basvuru


def belgeleri_sil(basvuru):
    """Başvurunun kimlik görüntülerini kayıttan ve diskten siler.

    Kimlik ve pasaport görüntüleri kişisel veridir; başvurunun işi bittiği
    anda (bakiye yüklendi ya da iptal edilip geri alındı) saklanmaları için
    sebep kalmaz. Başvuru kaydı, para geçmişi ve hakediş bilgisi durur;
    yalnızca görüntüler gider.

    Dosyalar veritabanı değişikliği **commit edildikten sonra** silinir.
    Aksi hâlde transaction geri alınırsa dosya çoktan gitmiş, satır geri
    gelmiş olur; kayıt olmayan bir dosyayı işaret eder.
    """
    belgeler = list(basvuru.belgeler.all())
    model = type(basvuru)

    if not belgeler:
        # Kayıt yoksa bile bayrağı işaretle: bir daha aranmasın.
        model.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
        basvuru.belgeler_silindi = True
        return 0

    # Kayıtları silmek yeterli: post_delete sinyali dosyaları da commit
    # sonrasında diskten siliyor (apps/dosya.py).
    basvuru.belgeler.all().delete()
    model.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
    basvuru.belgeler_silindi = True

    logger.info(
        "Başvuru %s sonuçlandı, %s belge silindi.", basvuru.referans_no, len(belgeler)
    )
    return len(belgeler)
