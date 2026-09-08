"""Sipariş açma.

Para hareketinin kendisi `apps.finans.services` içindedir — kural gereği
bakiye yalnızca oradan değişir. Buradaki iş siparişi kurup o servisi
çağırmak ve ikisini tek transaction'da tutmaktır: ödeme geçmezse ortada
ödenmemiş bir sipariş kalmaz.
"""

from decimal import Decimal

from django.db import transaction

from apps.finans.services import SiparisVerilemez, siparis_odemesini_isle
from apps.magaza.models import Siparis


def siparis_olustur(bayi, urun, adet, *, bayi_notu="", anahtar=None, olusturan=None):
    """Siparişi açar ve tutarı bayinin bakiyesinden düşer.

    `anahtar` formda gizli alanda taşınır: bayi sayfayı yenilediğinde aynı
    sipariş ikinci kez açılmaz, var olan kayıt geri döner. Cüzdan işlem
    ekranındaki kuralın aynısı.

    Bakiye yetmezse `SiparisVerilemez` yükselir ve transaction geri alınır;
    yarım kalmış bir sipariş kaydı oluşmaz.
    """
    if adet < 1:
        raise SiparisVerilemez("Adet en az 1 olmalı.")
    if not urun.aktif:
        raise SiparisVerilemez("Bu ürün şu an satışta değil.")

    tutar = urun.fiyat * Decimal(adet)

    with transaction.atomic():
        if anahtar:
            siparis, olusturuldu = Siparis.objects.get_or_create(
                islem_anahtari=anahtar,
                defaults={
                    "bayi": bayi,
                    "urun": urun,
                    "urun_adi": urun.ad,
                    "adet": adet,
                    "birim_fiyat": urun.fiyat,
                    "tutar": tutar,
                    "bayi_notu": bayi_notu,
                },
            )
            if not olusturuldu:
                # Sayfa yenilendi; para zaten işlenmiş.
                return siparis
        else:
            siparis = Siparis.objects.create(
                bayi=bayi,
                urun=urun,
                urun_adi=urun.ad,
                adet=adet,
                birim_fiyat=urun.fiyat,
                tutar=tutar,
                bayi_notu=bayi_notu,
            )

        siparis_odemesini_isle(siparis, olusturan=olusturan or bayi)
        siparis.refresh_from_db()
        return siparis
