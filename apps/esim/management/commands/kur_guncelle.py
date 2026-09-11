"""`manage.py kur_guncelle` — USD kurunu TCMB'den çekip Genel Ayarlar'a yazar.

Günde bir çalıştırılması beklenir (cron); eSIM satış fiyatı bu kurla
hesaplandığı için eski kur maliyetin altında satış demektir.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.esim.kur import KurAlinamadi, kuru_guncelle


class Command(BaseCommand):
    help = "USD kurunu TCMB'den çeker ve Genel Ayarlar'a yazar."

    def handle(self, *args, **options):
        try:
            kur = kuru_guncelle()
        except KurAlinamadi as hata:
            raise CommandError(str(hata))
        self.stdout.write(self.style.SUCCESS(f"USD kuru güncellendi: {kur} ₺"))
