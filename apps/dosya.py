"""Kayıt silinince ya da dosya değişince diskteki dosyayı temizler.

Django, kayıt silindiğinde dosyayı diskten silmez (1.3'ten beri kasıtlı:
geri alınan bir işlemde dosya kaybolmasın diye). Sonuç olarak silinen her
tarife görseli ve değiştirilen her kimlik fotoğrafı diskte kalır.

Bu modül iki durumu kapatır:
  · kayıt silindiğinde dosyayı da siler
  · dosya alanına yenisi yüklendiğinde eskisini siler

Silme her zaman `transaction.on_commit` içinde yapılır: işlem geri alınırsa
dosya yerinde kalmalı.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, pre_save

logger = logging.getLogger(__name__)


def _sil(dosya):
    if not dosya:
        return

    def diskten():
        try:
            dosya.delete(save=False)
        except OSError as hata:
            logger.error("Dosya silinemedi (%s): %s", dosya.name, hata)

    transaction.on_commit(diskten)


def dosyalari_temizle(model, *alanlar):
    """Verilen dosya alanları için otomatik temizliği açar."""

    def silindiginde(sender, instance, **kwargs):
        for ad in alanlar:
            _sil(getattr(instance, ad, None))

    def degistiginde(sender, instance, **kwargs):
        if not instance.pk:
            return
        try:
            onceki = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            return
        for ad in alanlar:
            eski = getattr(onceki, ad, None)
            yeni = getattr(instance, ad, None)
            # Alan boşaltıldıysa ya da başka bir dosya yüklendiyse eskisi gitsin.
            if eski and eski.name != getattr(yeni, "name", None):
                _sil(eski)

    ad = model._meta.label_lower
    post_delete.connect(silindiginde, sender=model, dispatch_uid=f"dosya_sil:{ad}")
    pre_save.connect(degistiginde, sender=model, dispatch_uid=f"dosya_degis:{ad}")
