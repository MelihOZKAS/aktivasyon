"""Kontör işçisi: işlemdekilerin sonucunu sorar, takılanları yürütür.

İşlem açıldığı anda arka planda gönderilir; sonucu bayinin sayfası ve bayi
programının sorgusu da yürütür. İşçi, kimse bakmazken de işin bitmesini
sağlar: bayi sayfayı kapatsa bile yüklenen işlem kapanır, yüklenemeyen
iade edilir.

    manage.py kontor_isle            bir tur
    manage.py kontor_isle --dongu    sürekli (docker-compose'daki kontor_isci)

Hiçbir şeyi ikinci kez göndermez: sıradakine geçiş yalnızca kesin retle,
askıdaki işleme hiç dokunulmaz (`apps.kontor.services`).
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.kontor.services import bekleyenleri_isle

logger = logging.getLogger(__name__)


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
        self.stdout.write(f"Kontör işçisi başladı ({aralik} sn aralıkla).")
        while True:
            close_old_connections()
            try:
                bekleyenleri_isle()
            except Exception:
                # Veritabanı kısa süre gitse de işçi ölmesin; bir sonraki tur dener.
                logger.exception("Kontör işçisi turu başarısız.")
            time.sleep(aralik)
