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
from django.utils import timezone

from apps.basvurular.models import Basvuru, DurumGecmisi

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Basvuru)
def onceki_durumu_hatirla(sender, instance, **kwargs):
    """Kaydetmeden önce durumu ve tedarikçiyi instance üzerinde saklar."""
    if not instance.pk:
        instance._onceki_durum_id = None
        instance._onceki_tedarikci_id = None
        return
    onceki = (
        sender.objects.filter(pk=instance.pk)
        .values_list("durum_id", "tedarikci_id")
        .first()
    )
    instance._onceki_durum_id, instance._onceki_tedarikci_id = onceki or (None, None)


@receiver(post_save, sender=Basvuru)
def durum_degisiminde_para_isle(sender, instance, created, **kwargs):
    from apps.bayi.services import basvurunun_simlerini_serbest_birak
    from apps.bildirim.telegram import basvuru_bildir
    from apps.finans.services import (
        basvuru_parasini_geri_al,
        basvuru_parasini_isle,
        tedarikci_bedelini_isle,
    )

    onceki_durum_id = getattr(instance, "_onceki_durum_id", None)
    onceki_tedarikci_id = getattr(instance, "_onceki_tedarikci_id", None)
    durum_degisti = created or onceki_durum_id != instance.durum_id
    tedarikci_atandi = not created and onceki_tedarikci_id != instance.tedarikci_id

    # Tedarikçi işlem aktifleştikten sonra da atanabilir; o durumda yalnızca
    # tedarikçi tarafını işleriz.
    if not durum_degisti:
        if tedarikci_atandi and instance.durum.hakedis_tetikler:
            guncel = tedarikci_bedelini_isle(instance)
            instance.tedarikci_geliri = guncel.tedarikci_geliri
            instance.tedarikci_islendi = guncel.tedarikci_islendi
        return

    DurumGecmisi.objects.create(
        basvuru=instance,
        onceki_durum_id=onceki_durum_id,
        yeni_durum=instance.durum,
        aciklama="Başvuru oluşturuldu." if created else "",
    )

    durum = instance.durum

    # Bildirim işin önüne geçmez: transaction tamamlandıktan sonra,
    # arka planda gönderilir ve hatası akışı bozmaz.
    if created or durum.bildirim_gonder:
        basvuru_bildir(instance, yeni=created)

    # Saklama süresi buradan işler: belgeler sonuçlanma tarihine göre silinir.
    if instance.sonuclandi_mi and instance.sonuclanma_tarihi is None:
        instance.sonuclanma_tarihi = timezone.now()
        type(instance).objects.filter(pk=instance.pk).update(
            sonuclanma_tarihi=instance.sonuclanma_tarihi
        )

    if durum.olumsuz_sonuc:
        # Operatörden iptal gelince kart fiziksel olarak bayide kalıyor;
        # sistemde de yeniden kullanılabilir olmalı.
        basvurunun_simlerini_serbest_birak(instance)

    if durum.hakedis_tetikler and not instance.para_islendi:
        guncel = basvuru_parasini_isle(instance)
        guncel = tedarikci_bedelini_isle(guncel)
    elif durum.olumsuz_sonuc and (instance.para_islendi or instance.tedarikci_islendi):
        guncel = basvuru_parasini_geri_al(instance)
    else:
        return

    # Servis kilitli bir kopya üzerinde çalıştı; eldeki instance'ı senkronla.
    instance.tahsil_edilen = guncel.tahsil_edilen
    instance.hakedis = guncel.hakedis
    instance.tedarikci_geliri = guncel.tedarikci_geliri
    instance.para_islendi = guncel.para_islendi
    instance.tedarikci_islendi = guncel.tedarikci_islendi
