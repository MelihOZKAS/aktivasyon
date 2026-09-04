"""Kaydı olmayan belge dosyalarını bulur ve temizler.

Normal akışta buna gerek olmaz: silme, veritabanı değişikliği commit
edildikten sonra çalışır. Yine de disk hatası ya da yarıda kalan bir
işlem sahipsiz dosya bırakabilir. Kişisel veri söz konusu olduğu için
arada bir çalıştırmakta fayda var.

Veritabanı sıfırlandıktan sonra da gereklidir: kayıtlar gider, kimlik
görüntüleri diskte kalır. Eski sistemin `evrak/` klasörü de taranır —
yeni yapıda oraya yazan bir model yok, oradaki her dosya sahipsizdir.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.basvurular.models import BasvuruBelgesi

# Yalnızca başvuru belgesi klasörleri taranır. Tarife/kampanya/operatör
# görselleri kendi modellerine bağlıdır, buraya girmemeli.
KLASORLER = ["basvuru", "evrak"]


class Command(BaseCommand):
    help = "Veritabanında kaydı olmayan belge dosyalarını bulur."

    def add_arguments(self, ayrıştırıcı):
        ayrıştırıcı.add_argument(
            "--sil", action="store_true", help="Bulunanları gerçekten sil."
        )

    def handle(self, *args, **secenekler):
        kok = Path(settings.MEDIA_ROOT)
        klasorler = [kok / ad for ad in KLASORLER if (kok / ad).is_dir()]
        if not klasorler:
            self.stdout.write("Belge klasörü yok, temizlenecek bir şey de yok.")
            return

        kayitli = set(
            BasvuruBelgesi.objects.exclude(dosya="").values_list("dosya", flat=True)
        )

        sahipsiz = [
            yol
            for klasor in klasorler
            for yol in klasor.rglob("*")
            if yol.is_file() and str(yol.relative_to(kok)) not in kayitli
        ]

        if not sahipsiz:
            self.stdout.write(self.style.SUCCESS("Sahipsiz dosya yok."))
            return

        toplam = sum(y.stat().st_size for y in sahipsiz)
        for yol in sahipsiz:
            self.stdout.write(f"  {yol.relative_to(kok)}")

        if secenekler["sil"]:
            for yol in sahipsiz:
                yol.unlink(missing_ok=True)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(sahipsiz)} sahipsiz dosya silindi ({toplam/1024/1024:.1f} MB)."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(sahipsiz)} sahipsiz dosya bulundu ({toplam/1024/1024:.1f} MB). "
                    "Silmek için --sil ekleyin."
                )
            )
