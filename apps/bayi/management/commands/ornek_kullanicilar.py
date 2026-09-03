"""Denemek için örnek yönetici ve bayi hesapları oluşturur.

Yalnızca geliştirme içindir; üretimde çalıştırılmamalıdır. Var olan
hesapları bozmaz, parolalarını tazeler.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bayi.models import BayiProfili
from apps.finans.models import BayiGrubu, Cuzdan

PAROLA = "deneme12345"

YONETICILER = [
    ("yonetici", "yonetici@aktivasyon.local", "Operasyon", "Yöneticisi"),
]

# (kullanıcı, ünvan, şehir, bakiye, borç izni, borç limiti)
BAYILER = [
    ("bayi.kaya", "Kaya İletişim", "İstanbul", Decimal("8450.00"), True, Decimal("2500.00")),
    ("bayi.demir", "Demir Telekom", "Ankara", Decimal("1200.00"), False, Decimal("0.00")),
    ("bayi.yildiz", "Yıldız GSM", "İzmir", Decimal("0.00"), True, Decimal("1000.00")),
]


class Command(BaseCommand):
    help = "Geliştirme için örnek yönetici ve bayi hesapları oluşturur."

    def add_arguments(self, ayrıştırıcı):
        ayrıştırıcı.add_argument(
            "--zorla",
            action="store_true",
            help="DEBUG kapalıyken de çalıştır (dikkatli kullanın).",
        )

    @transaction.atomic
    def handle(self, *args, **secenekler):
        from django.conf import settings

        if not settings.DEBUG and not secenekler["zorla"]:
            raise CommandError(
                "Bu komut örnek parolalarla hesap açar ve yalnızca geliştirme "
                "içindir. Üretimde çalıştırmak için --zorla gerekir."
            )

        grup, _ = BayiGrubu.objects.get_or_create(ad="Standart Bayi")

        self.stdout.write(self.style.MIGRATE_HEADING("\nYöneticiler"))
        for kullanici_adi, eposta, ad, soyad in YONETICILER:
            kullanici, olusturuldu = User.objects.get_or_create(
                username=kullanici_adi,
                defaults={"email": eposta, "first_name": ad, "last_name": soyad},
            )
            kullanici.is_staff = True
            kullanici.is_superuser = True
            kullanici.set_password(PAROLA)
            kullanici.save()
            self.stdout.write(
                f"  {kullanici_adi:14} {PAROLA:14} "
                f"{'oluşturuldu' if olusturuldu else 'parolası tazelendi'}"
            )

        self.stdout.write(self.style.MIGRATE_HEADING("\nBayiler"))
        for kullanici_adi, unvan, sehir, bakiye, borc_izni, limit in BAYILER:
            kullanici, olusturuldu = User.objects.get_or_create(
                username=kullanici_adi, defaults={"first_name": unvan}
            )
            kullanici.is_staff = False
            kullanici.set_password(PAROLA)
            kullanici.save()

            BayiProfili.objects.update_or_create(
                kullanici=kullanici,
                defaults={"unvan": unvan, "sehir": sehir, "yetkili_adi": unvan},
            )
            cuzdan, cuzdan_yeni = Cuzdan.objects.get_or_create(
                bayi=kullanici,
                defaults={
                    "grup": grup,
                    "bakiye": bakiye,
                    "borc_izni": borc_izni,
                    "borc_limiti": limit,
                },
            )
            durum = "borçlanabilir" if cuzdan.borc_izni else "borçlanamaz"
            self.stdout.write(
                f"  {kullanici_adi:14} {PAROLA:14} {unvan:16} "
                f"bakiye {cuzdan.bakiye:>9} ₺  {durum}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\nGiriş: /giris-yap/  ·  Yönetici oraya girince /yonetim/'e düşer.\n"
            )
        )
