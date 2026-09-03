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

# (kullanıcı, ünvan, şehir, bakiye, borç)
# (kullanıcı, ünvan, şehir, bakiye, borç, bayi mi, tedarikçi mi)
BAYILER = [
    ("bayi.kaya", "Kaya İletişim", "İstanbul", Decimal("8450.00"), Decimal("0.00"), True, False),
    ("bayi.demir", "Demir Telekom", "Ankara", Decimal("0.00"), Decimal("340.00"), True, False),
    ("tedarikci.ege", "Ege Tedarik", "İzmir", Decimal("5000.00"), Decimal("0.00"), False, True),
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

        self.stdout.write(self.style.MIGRATE_HEADING("\nBayiler ve tedarikçiler"))
        for kullanici_adi, unvan, sehir, bakiye, borc, bayi_mi, tedarikci_mi in BAYILER:
            kullanici, olusturuldu = User.objects.get_or_create(
                username=kullanici_adi, defaults={"first_name": unvan}
            )
            kullanici.is_staff = False
            kullanici.set_password(PAROLA)
            kullanici.save()

            BayiProfili.objects.update_or_create(
                kullanici=kullanici,
                defaults={
                    "unvan": unvan,
                    "sehir": sehir,
                    "yetkili_adi": unvan,
                    "bayi_mi": bayi_mi,
                    "tedarikci_mi": tedarikci_mi,
                },
            )
            cuzdan, cuzdan_yeni = Cuzdan.objects.get_or_create(
                bayi=kullanici,
                defaults={"grup": grup, "bakiye": bakiye, "borc": borc},
            )
            rol = "bayi" if bayi_mi and not tedarikci_mi else (
                "tedarikçi" if tedarikci_mi and not bayi_mi else "bayi+tedarikçi"
            )
            borc_notu = f"borç {cuzdan.borc} ₺" if cuzdan.borc else "borcu yok"
            self.stdout.write(
                f"  {kullanici_adi:16} {PAROLA:14} {unvan:16} {rol:14} "
                f"bakiye {cuzdan.bakiye:>9} ₺  {borc_notu}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\nGiriş: /giris-yap/  ·  Yönetici oraya girince /yonetim/'e düşer.\n"
            )
        )
