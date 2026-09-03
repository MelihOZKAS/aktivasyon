"""SIM kart stok hareketleri."""

import logging

from apps.bayi.models import SimKart, SimKartDurumu

logger = logging.getLogger(__name__)


def basvurunun_simlerini_serbest_birak(basvuru):
    """Başvuru olumsuz sonuçlandığında SIM kartları bayinin stoğuna döndürür.

    Operatörden iptal gelen ya da geçişi yapılamayan bir başvuruda kart
    fiziksel olarak bayinin elinde duruyor; sistemde "kullanıldı" kalırsa
    çöpe çıkmış olur. Bu yüzden karta yeniden işlem yapılabilir hâle
    getiriyoruz. Hangi başvuruda kullanıldığı bilgisi izlenebilirlik için
    korunur; kart yeniden kullanılırsa yeni başvuruyla güncellenir.
    """
    if not basvuru.bayi_id:
        return 0

    adet = SimKart.objects.filter(
        basvuru=basvuru, durum=SimKartDurumu.KULLANILDI
    ).update(durum=SimKartDurumu.ATANDI)

    if adet:
        logger.info(
            "Başvuru %s olumsuz sonuçlandı, %s SIM kart bayinin stoğuna döndü.",
            basvuru.referans_no,
            adet,
        )
    return adet
