"""Sistemi tek komutla kurar: migration, başlangıç verisi, örnek veri, yönetici.

    manage.py kurulum                     # migration + başlangıç verisi (üretim)
    manage.py kurulum --yonetici admin    # üstüne yönetici hesabı açar
    manage.py kurulum --sifirla --ornek   # her şeyi siler, örnek verilerle kurar

`--sifirla` yalnızca DATABASE_URL'in gösterdiği veritabanına dokunur. Aynı
sunucudaki diğer projelerin veritabanları ayrı olduğu için etkilenmez;
komut silmeden önce hangi veritabanına bağlı olduğunu yazar ve onay ister.
"""

import secrets

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections


class Command(BaseCommand):
    help = "Veritabanını kurar: migration, başlangıç verisi ve isteğe bağlı örnek veri."

    def add_arguments(self, ayristirici):
        ayristirici.add_argument(
            "--sifirla",
            action="store_true",
            help="Kurmadan önce bu projenin veritabanındaki HER ŞEYİ siler.",
        )
        ayristirici.add_argument(
            "--ornek",
            action="store_true",
            help="Örnek tarife, kural, SIM stoğu ve deneme hesapları da ekler.",
        )
        ayristirici.add_argument(
            "--yonetici",
            metavar="KULLANICI_ADI",
            help=(
                "Bu adla bir yönetici hesabı açar. Parola DJANGO_SUPERUSER_PASSWORD "
                "ortam değişkeninden alınır, yoksa üretilip bir kez ekrana yazılır."
            ),
        )
        ayristirici.add_argument(
            "--evet",
            action="store_true",
            help="Silme onayını sorma (betikten çalıştırmak için).",
        )
        ayristirici.add_argument(
            "--zorla",
            action="store_true",
            help="DEBUG kapalıyken de örnek veri yükle.",
        )

    def handle(self, *args, **secenekler):
        adim = 0

        if secenekler["sifirla"]:
            adim += 1
            self._baslik(adim, "Veritabanı siliniyor")
            self._sifirla(onaylandi=secenekler["evet"])

        adim += 1
        self._baslik(adim, "Migration'lar uygulanıyor")
        call_command("migrate", "--noinput", verbosity=1, stdout=self.stdout,
                     stderr=self.stderr)

        adim += 1
        self._baslik(adim, "Başlangıç verisi (durumlar, operatörler, kategoriler)")
        call_command("baslangic_verisi", stdout=self.stdout, stderr=self.stderr)

        if secenekler["ornek"]:
            zorla = secenekler["zorla"] or not settings.DEBUG

            adim += 1
            self._baslik(adim, "Deneme hesapları")
            call_command("ornek_kullanicilar", zorla=zorla, stdout=self.stdout,
                         stderr=self.stderr)

            adim += 1
            self._baslik(adim, "Örnek tarifeler, kurallar ve SIM stoğu")
            call_command("ornek_veri", zorla=zorla, stdout=self.stdout, stderr=self.stderr)

        if secenekler["yonetici"]:
            adim += 1
            self._baslik(adim, "Yönetici hesabı")
            self._yonetici_ac(secenekler["yonetici"])

        self.stdout.write(self.style.SUCCESS("\nKurulum tamamlandı."))
        if not secenekler["ornek"]:
            self.stdout.write(
                "Sırada: /yonetim/ → tarifeler, bayi grupları ve ücret kuralları.\n"
                "Ayrıntılı sıra için CLAUDE.md → “Kurulum sırası”.\n"
            )

    def _baslik(self, sira, metin):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{sira}. {metin}"))

    # --- veritabanını sıfırlama -------------------------------------------

    def _sifirla(self, *, onaylandi):
        baglanti = connections[DEFAULT_DB_ALIAS]
        ayarlar = baglanti.settings_dict
        ad = str(ayarlar["NAME"])
        sunucu = ayarlar.get("HOST") or "yerel"
        port = ayarlar.get("PORT") or "-"

        self.stdout.write(f"   Motor      : {baglanti.vendor}")
        self.stdout.write(f"   Veritabanı : {ad}")
        self.stdout.write(f"   Sunucu     : {sunucu}:{port}")
        self.stdout.write(
            self.style.WARNING(
                "   Bu veritabanındaki tüm tablolar ve veriler silinecek.\n"
                "   Aynı sunucudaki diğer projelerin veritabanlarına dokunulmaz."
            )
        )

        if not onaylandi:
            beklenen = ad.split("/")[-1]
            try:
                cevap = input(f"   Onaylamak için veritabanı adını yazın ({beklenen}): ")
            except EOFError:
                raise CommandError(
                    "Onay alınamadı. Betikten çalıştırıyorsanız --evet ekleyin."
                )
            if cevap.strip() != beklenen:
                raise CommandError("Ad eşleşmedi, hiçbir şey silinmedi.")

        if baglanti.vendor == "sqlite":
            self._sqlite_sil(baglanti, ad)
        elif baglanti.vendor == "postgresql":
            self._postgres_sil(baglanti)
        else:
            raise CommandError(
                f"{baglanti.vendor} için otomatik sıfırlama yazılmadı. "
                "Veritabanını elle silip komutu --sifirla olmadan çalıştırın."
            )

        self.stdout.write(self.style.SUCCESS("   Veritabanı boşaltıldı."))

    def _sqlite_sil(self, baglanti, ad):
        from pathlib import Path

        baglanti.close()
        dosya = Path(ad)
        # Yazma günlüğü de gitmeli; kalırsa yeni veritabanına eski sayfalar taşınır.
        for yol in (dosya, Path(f"{ad}-wal"), Path(f"{ad}-shm")):
            if yol.exists():
                yol.unlink()
                self.stdout.write(f"   silindi: {yol}")

    def _postgres_sil(self, baglanti):
        # Yalnızca bağlı olunan veritabanının şeması düşürülür; sunucudaki
        # diğer veritabanları görünmez ve etkilenmez.
        with baglanti.cursor() as imlec:
            imlec.execute("DROP SCHEMA public CASCADE")
            imlec.execute("CREATE SCHEMA public")
            imlec.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
            imlec.execute("GRANT ALL ON SCHEMA public TO public")
        baglanti.close()

    # --- yönetici ---------------------------------------------------------

    def _yonetici_ac(self, kullanici_adi):
        import os

        from django.contrib.auth.models import User

        kullanici = User.objects.filter(username=kullanici_adi).first()
        if kullanici is not None:
            kullanici.is_staff = True
            kullanici.is_superuser = True
            kullanici.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(
                f"   {kullanici_adi} zaten var; yönetici yetkisi doğrulandı. "
                "Parola değiştirilmedi."
            )
            return

        parola = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        uretildi = parola is None
        if uretildi:
            parola = secrets.token_urlsafe(15)

        User.objects.create_superuser(username=kullanici_adi, password=parola)
        self.stdout.write(f"   {kullanici_adi} oluşturuldu.")
        if uretildi:
            self.stdout.write(
                self.style.WARNING(
                    f"   Parola: {parola}\n"
                    "   Bu parola bir daha gösterilmez; şimdi kaydedin."
                )
            )
