"""Destek talebine mesaj yazmanın tek yolu.

Mesaj eklemek iki şeyi birden yapar: kaydı yazar ve talebin özet alanlarını
(son mesaj, sıra kimde) günceller. Ayrı ayrı yapılsaydı biri unutulur,
talep listede yanlış tarafta görünürdü.

**Mesaj yazmak talebin durumunu değiştirmez.** Bir süre kapalı talebe
yazılan mesaj onu yeniden açıyordu; sonuç, yöneticinin kapattığı talebin
bayi yazar yazmaz yeniden açılması oldu — kapatma hiç tutmuyor, bayi
kapalı talebe sürekli yazabiliyordu. Kapatmak yönetimin (ya da talebi
kendisi kapatan bayinin) kararıdır ve kapalı kalır; devam eden bir konu
için bayi yeni talep açar.
"""

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class TalepKapali(Exception):
    """Kapalı talebe bayi mesajı yazılamaz."""


def mesaj_ekle(talep, gonderen, icerik, *, personelden=False):
    """Talebe mesaj yazar ve özet alanlarını günceller.

    Durum olduğu gibi kalır. Kapalı talebe **bayi yazamaz**: kapı önce
    görünümde durur (kutu hiç çizilmez), burada ikinci kez durur — elle
    gönderilen bir istek kapalı talebi konuşmaya döndürmesin. Yönetim
    kapalı talebe not düşebilir; talep yine kapalı kalır, yeniden açmak
    ayrı ve bilinçli bir iştir.
    """
    from apps.destek.models import DestekMesaji, TalepDurumu

    icerik = (icerik or "").strip()
    if not icerik:
        return None

    if not personelden and talep.durum == TalepDurumu.KAPALI:
        raise TalepKapali(
            f"{talep.referans_no} kapalı; yeni mesaj için yeni talep açılmalı."
        )

    with transaction.atomic():
        mesaj = DestekMesaji.objects.create(
            talep=talep,
            gonderen=gonderen,
            personelden=personelden,
            icerik=icerik,
        )
        talep.son_mesaj_tarihi = mesaj.tarih or timezone.now()
        # Son sözü bayi söylediyse sıra yönetimdedir.
        talep.yanit_bekliyor = not personelden
        talep.save(
            update_fields=["son_mesaj_tarihi", "yanit_bekliyor", "guncelleme_tarihi"]
        )

    return mesaj


def talep_ac(bayi, konu, icerik, *, basvuru=None):
    """Yeni talep açar ve ilk mesajı yazar."""
    from apps.bildirim.telegram import destek_talebi_bildir
    from apps.destek.models import DestekTalebi

    talep = DestekTalebi.objects.create(bayi=bayi, konu=konu, basvuru=basvuru)
    mesaj_ekle(talep, bayi, icerik)
    logger.info("Destek talebi açıldı: %s", talep.referans_no)
    destek_talebi_bildir(talep)
    return talep
