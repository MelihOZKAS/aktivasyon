"""Başvuru yan işlemleri."""

import logging

from django.db import transaction

from apps.basvurular.models import BasvuruDurumu
from apps.bayi.models import SimKartDurumu
from apps.bayi.services import sim_arizali_isaretle

logger = logging.getLogger(__name__)


# --- Bozuk SIM ve bayinin düzeltmesi ----------------------------------------
#
# Bozuk kart için para hareketi yoktur, kart takası vardır. Başvuru iptal
# edilip yeniden girilseydi giriş bedeli iade edilir, güncel fiyattan yeniden
# kesilirdi; bayi 100'e aldığı işi 150'ye almış olurdu. Aynı başvuruda kartı
# değiştirmek parayı olduğu yerde bırakır. Eksik evrak da aynı yoldan yürür:
# bayi düzeltir, yeniden gönderir, başvuru kaldığı yere döner.


class SimDegisimiHatasi(Exception):
    """SIM bildirimi ya da düzeltme yapılamadı; sebebi mesajda."""


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


def duzeltmeyi_gonder(basvuru, *, degistiren, degisenler=()):
    """Bayi düzeltip yeniden gönderdi: başvuru bildirim öncesi durumuna döner.

    Neyin değiştiği geçmişe düşer; yönetim alan alan karşılaştırmasın. Para
    hiç oynamaz — düzeltme yeni bir ücret doğurmaz, iş zaten satın alındı.
    """
    if not basvuru.bayi_duzeltebilir:
        raise SimDegisimiHatasi("Bu başvuru şu an düzeltmeye açık değil.")

    hedef = _onceki_durum(basvuru)
    if hedef is not None:
        basvuru.durum = hedef
    basvuru._degistiren = degistiren
    ozet = ", ".join(degisenler) if degisenler else "değişiklik yok"
    basvuru._aciklama = f"Bayi düzeltip yeniden gönderdi: {ozet}."[:255]
    basvuru.save(update_fields=["durum", "guncelleme_tarihi"])

    logger.info("Başvuru %s: bayi düzeltip yeniden gönderdi (%s).", basvuru.referans_no, ozet)
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
