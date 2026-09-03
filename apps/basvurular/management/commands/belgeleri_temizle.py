"""Saklama süresi dolmuş kimlik ve pasaport görüntülerini siler.

Bu dosyalar kişisel veridir; işleri bittikten sonra süresiz tutulmaz.
Başvuru kaydı ve para geçmişi yerinde kalır, yalnızca görüntüler silinir.

Sunucuda günlük cron ile çalıştırılır:
    0 4 * * * docker exec app_fadil python manage.py belgeleri_temizle
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.basvurular.models import Basvuru


class Command(BaseCommand):
    help = "Saklama süresi dolan başvuru belgelerini siler."

    def add_arguments(self, ayrıştırıcı):
        ayrıştırıcı.add_argument(
            "--gun",
            type=int,
            help="Saklama süresi. Verilmezse BELGE_SAKLAMA_GUNU ayarı kullanılır.",
        )
        ayrıştırıcı.add_argument(
            "--dene",
            action="store_true",
            help="Hiçbir şey silme, yalnızca ne silineceğini yaz.",
        )

    def handle(self, *args, **secenekler):
        gun = secenekler["gun"] or getattr(settings, "BELGE_SAKLAMA_GUNU", 0)
        if gun <= 0:
            self.stdout.write(
                self.style.WARNING(
                    "Saklama süresi tanımlı değil (BELGE_SAKLAMA_GUNU=0); "
                    "otomatik silme kapalı."
                )
            )
            return

        sinir = timezone.now() - timedelta(days=gun)
        adaylar = (
            Basvuru.objects.filter(
                belgeler_silindi=False,
                sonuclanma_tarihi__isnull=False,
                sonuclanma_tarihi__lt=sinir,
            )
            .prefetch_related("belgeler")
            .order_by("sonuclanma_tarihi")
        )

        toplam_basvuru = toplam_dosya = 0

        for basvuru in adaylar:
            belgeler = list(basvuru.belgeler.all())
            if secenekler["dene"]:
                self.stdout.write(
                    f"  {basvuru.referans_no}  "
                    f"{basvuru.sonuclanma_tarihi:%d.%m.%Y}  {len(belgeler)} dosya"
                )
                toplam_basvuru += 1
                toplam_dosya += len(belgeler)
                continue

            with transaction.atomic():
                for belge in belgeler:
                    if belge.dosya:
                        # Diskteki dosyayı sil; kayıt silinince yalnızca satır gider.
                        belge.dosya.delete(save=False)
                    toplam_dosya += 1
                basvuru.belgeler.all().delete()
                Basvuru.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
            toplam_basvuru += 1

        eylem = "silinecek" if secenekler["dene"] else "silindi"
        self.stdout.write(
            self.style.SUCCESS(
                f"{gun} günden eski {toplam_basvuru} başvurunun "
                f"{toplam_dosya} belgesi {eylem}."
            )
        )
