"""Kontör işçisi: işlemdekilerin sonucunu sorar, takılanları yürütür.

İşlem açıldığı anda arka planda gönderilir; sonucu bayinin sayfası ve bayi
programının sorgusu da yürütür. İşçi, kimse bakmazken de işin bitmesini
sağlar: bayi sayfayı kapatsa bile yüklenen işlem kapanır, yüklenemeyen
iade edilir.

    manage.py kontor_isle            bir tur
    manage.py kontor_isle --dongu    sürekli (docker-compose'daki kontor_isci)

Hiçbir şeyi ikinci kez göndermez: sıradakine geçiş yalnızca kesin retle,
askıdaki işleme hiç dokunulmaz (`apps.kontor.services`).

**Migration bitmeden başlamaz.** docker-compose'un `depends_on`'u yalnızca
app container'ının *açılmasını* bekler, kurulumun bitmesini değil; işçi
tablolar oluşmadan sorgu atıp her 3 saniyede bir traceback basıyordu.
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connections
from django.db.migrations.executor import MigrationExecutor

from apps.kontor.services import bekleyenleri_isle

logger = logging.getLogger(__name__)

# Aynı hata üst üste gelirse log'u doldurmasın: bekleme her seferinde
# ikiye katlanır, bu sınırda durur.
EN_UZUN_BEKLEME = 60


def _migration_bekliyor():
    try:
        baglanti = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(baglanti)
        return bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    except Exception:
        return True  # veritabanı henüz hazır değil


class Command(BaseCommand):
    help = "Kontör işlemlerinin sonucunu sağlayıcılardan sorar."

    def add_arguments(self, parser):
        parser.add_argument("--dongu", action="store_true", help="Durmadan çalış.")
        parser.add_argument("--aralik", type=float, default=3, help="Turlar arası saniye (varsayılan 3).")

    def handle(self, *args, dongu=False, aralik=3, **options):
        if not dongu:
            adet = bekleyenleri_isle()
            self.stdout.write(f"{adet} işleme bakıldı.")
            return

        while _migration_bekliyor():
            self.stdout.write("Kurulum (migration) bekleniyor…")
            close_old_connections()
            time.sleep(5)

        self.stdout.write(f"Kontör işçisi başladı ({aralik} sn aralıkla).")
        bekleme = aralik
        while True:
            close_old_connections()
            try:
                bekleyenleri_isle()
                bekleme = aralik
            except Exception:
                # Veritabanı kısa süre gitse de işçi ölmesin; bir sonraki tur dener.
                logger.exception("Kontör işçisi turu başarısız; %s sn sonra yeniden.", bekleme)
                bekleme = min(bekleme * 2, EN_UZUN_BEKLEME)
            time.sleep(bekleme)
