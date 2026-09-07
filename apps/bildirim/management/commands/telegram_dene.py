"""Telegram ayarlarını doğrular ve deneme mesajı atar."""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.bildirim import telegram


class Command(BaseCommand):
    help = "Telegram bağlantısını sınar ve gruba deneme mesajı gönderir."

    def handle(self, *args, **secenekler):
        if not telegram.yapilandirilmis_mi():
            self.stdout.write(
                self.style.ERROR(
                    "Telegram yapılandırılmamış.\n"
                    "  .env dosyasına şunları ekleyin:\n"
                    "    TELEGRAM_BOT_TOKEN=BotFather'dan aldığınız anahtar\n"
                    "    TELEGRAM_SOHBET_ID=@grup_kullanici_adi ya da sayısal id"
                )
            )
            return

        self.stdout.write(f"Sohbet: {settings.TELEGRAM_SOHBET_ID}")
        self.stdout.write("Mesaj gönderiliyor...")

        # Komutta doğrudan gönderiyoruz: sonucu hemen görmek istiyoruz.
        gitti, aciklama = telegram._gonder(
            "✅ <b>Aktivasyon</b>\nBildirim ayarları çalışıyor. Bu bir deneme mesajıdır."
        )
        if gitti:
            self.stdout.write(self.style.SUCCESS("Mesaj gönderildi."))
            return

        self.stdout.write(
            self.style.ERROR(
                f"Telegram mesajı kabul etmedi: {aciklama}\n"
                "  · Bot gruba/kanala eklendi ve yönetici yapıldı mı?\n"
                "  · Sohbet id doğru mu? (herkese açık kanal için @kullanici_adi, "
                "özel grup için -100... ile başlayan sayısal id — özel grupta "
                "@ ile başlayan ad çalışmaz)\n"
                "  · Anahtar BotFather'dan alınan güncel anahtar mı?"
            )
        )
