"""Durum değişimini para motoruna ve SIM stoğuna bağlayan sinyaller.

Para işlemi, durum değişikliğiyle **aynı transaction içinde** yapılır.
Böylece para hareketi başarısız olursa durum değişikliği de geri alınır;
"Aktif göründü ama para işlenmedi" durumu oluşamaz.

Başvuru olumsuz sonuçlandığında kullanılan SIM kartlar bayinin stoğuna
geri döner: kart fiziksel olarak elinde durduğu için çöpe çıkmamalı.
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.basvurular.models import Basvuru, DurumGecmisi

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Basvuru)
def onceki_durumu_hatirla(sender, instance, **kwargs):
    """Kaydetmeden önce veritabanındaki durumu instance üzerinde saklar."""
    if not instance.pk:
        instance._onceki_durum_id = None
        return
    instance._onceki_durum_id = (
        sender.objects.filter(pk=instance.pk).values_list("durum_id", flat=True).first()
    )


@receiver(post_save, sender=Basvuru)
def durum_degisiminde_para_isle(sender, instance, created, **kwargs):
    onceki_durum_id = getattr(instance, "_onceki_durum_id", None)
    if not created and onceki_durum_id == instance.durum_id:
        return

    from apps.bayi.services import basvurunun_simlerini_serbest_birak
    from apps.finans.services import basvuru_parasini_geri_al, basvuru_parasini_isle

    DurumGecmisi.objects.create(
        basvuru=instance,
        onceki_durum_id=onceki_durum_id,
        yeni_durum=instance.durum,
        aciklama="Başvuru oluşturuldu." if created else "",
    )

    durum = instance.durum

    if durum.olumsuz_sonuc:
        # Operatörden iptal gelince kart fiziksel olarak bayide kalıyor;
        # sistemde de yeniden kullanılabilir olmalı.
        basvurunun_simlerini_serbest_birak(instance)

    if durum.hakedis_tetikler and not instance.para_islendi:
        guncel = basvuru_parasini_isle(instance)
    elif durum.olumsuz_sonuc and instance.para_islendi:
        guncel = basvuru_parasini_geri_al(instance)
    else:
        return

    # Servis kilitli bir kopya üzerinde çalıştı; eldeki instance'ı senkronla.
    instance.tahsil_edilen = guncel.tahsil_edilen
    instance.hakedis = guncel.hakedis
    instance.para_islendi = guncel.para_islendi
