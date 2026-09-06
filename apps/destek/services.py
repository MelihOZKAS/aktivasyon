"""Destek talebine mesaj yazmanın tek yolu.

Mesaj eklemek üç şeyi birden yapar: kaydı yazar, talebin özet alanlarını
(son mesaj, sıra kimde) günceller ve kapalı talebi yeniden açar. Bunlar
ayrı ayrı yapılsaydı biri unutulur, talep listede yanlış tarafta görünürdü.
"""

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def mesaj_ekle(talep, gonderen, icerik, *, personelden=False):
    """Talebe mesaj yazar ve özet alanlarını günceller.

    Kapalı bir talebe yazmak onu **yeniden açar**: konuşma devam ediyorsa
    kayıt kapalı görünmemeli, yoksa kimse bakmaz.
    """
    from apps.destek.models import DestekMesaji, TalepDurumu

    icerik = (icerik or "").strip()
    if not icerik:
        return None

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
        alanlar = ["son_mesaj_tarihi", "yanit_bekliyor", "guncelleme_tarihi"]
        if talep.durum == TalepDurumu.KAPALI:
            talep.durum = TalepDurumu.ACIK
            alanlar.append("durum")
        talep.save(update_fields=alanlar)

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
