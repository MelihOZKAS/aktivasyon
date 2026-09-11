"""`manage.py esim_esitle` — aktif sağlayıcıların paket kataloğunu çeker.

Panelde de düğmesi var; komut cron için. Fiyatlar sağlayıcıda değişince
buradan yansır: alış artmışsa satış da artar, sipariş eski fiyata açılmaz.
"""

from django.core.management.base import BaseCommand

from apps.esim.models import Saglayici
from apps.esim.saglayicilar import SaglayiciHatasi
from apps.esim.services import paketleri_esitle


class Command(BaseCommand):
    help = "Aktif eSIM sağlayıcılarının paket listesini eşitler."

    def handle(self, *args, **options):
        saglayicilar = Saglayici.objects.filter(aktif=True)
        if not saglayicilar:
            self.stdout.write("Aktif sağlayıcı yok.")
            return
        for saglayici in saglayicilar:
            try:
                eklenen, guncellenen, dusen = paketleri_esitle(saglayici)
            except SaglayiciHatasi as hata:
                self.stderr.write(f"{saglayici}: {hata}")
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"{saglayici}: {eklenen} yeni, {guncellenen} güncellendi, {dusen} düştü"
                )
            )
