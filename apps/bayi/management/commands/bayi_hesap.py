"""Bir telefon numarasının sistemdeki hâlini gösterir.

"Bayi giremiyor" şikâyeti geldiğinde sorunun nerede olduğunu ayırmak için
var: başvuru mu düşmemiş, hesap mı açılmamış, parola mı yok, numara mı
başka biçimde kaydedilmiş. Üçü de aynı ekranda "kullanıcı adı veya parola
hatalı" diye görünüyor; sunucuda tek komutla ayırt edilebilmeli.

    manage.py bayi_hesap 0543 560 96 72

Parola hiçbir zaman gösterilmez; yalnızca var/yok bilgisi verilir.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.bayi.models import BayiBasvurusu
from apps.bayi.telefon import normalize


class Command(BaseCommand):
    help = "Telefon numarasının başvuru ve hesap durumunu gösterir."

    def add_arguments(self, ayrıştırıcı):
        ayrıştırıcı.add_argument("numara", nargs="+", help="Bayinin telefon numarası.")

    def handle(self, *args, **secenekler):
        ham = " ".join(secenekler["numara"])
        numara = normalize(ham)
        if not numara:
            raise CommandError("Numara okunamadı.")

        self.stdout.write(f"Girilen: {ham}")
        self.stdout.write(f"Aranan kullanıcı adı: {numara}\n")

        self._basvurular(numara)
        self._hesaplar(numara)

    def _basvurular(self, numara):
        # Numarası farklı biçimde kaydedilmiş eski kayıtlar da yakalansın diye
        # tüm başvurular normalleştirilmiş hâliyle karşılaştırılır.
        bulunan = [
            b for b in BayiBasvurusu.objects.all() if normalize(b.irtibat) == numara
        ]
        if not bulunan:
            self.stdout.write(self.style.WARNING("Bayi başvurusu yok."))
            return

        self.stdout.write(f"{len(bulunan)} başvuru:")
        for basvuru in bulunan:
            parola = "parola var" if basvuru.parolasini_secti else "PAROLA YOK"
            hesap = basvuru.olusturulan_kullanici or "hesap açılmamış"
            self.stdout.write(
                f"  {basvuru.ad_soyad} · kayıtlı numara {basvuru.irtibat} · "
                f"{basvuru.get_durum_display()} · {parola} · {hesap}"
            )

    def _hesaplar(self, numara):
        kullanici = User.objects.filter(username=numara).first()
        if kullanici:
            girilebilir = (
                "girebilir"
                if kullanici.has_usable_password() and kullanici.is_active
                else "GİREMEZ"
            )
            parola = "parola var" if kullanici.has_usable_password() else "PAROLA YOK"
            aktif = "aktif" if kullanici.is_active else "PASİF"
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nHesap var: {kullanici.username} · {parola} · {aktif} "
                    f"· {girilebilir}"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("\nBu kullanıcı adıyla hesap yok."))

        # Numarası tek biçime indirilmeden açılmış hesaplar bayiyi giriş
        # ekranında bırakır: bayi 5xx yazar, hesabın adı 05xx'tir.
        benzer = [
            k
            for k in User.objects.exclude(username=numara)
            if normalize(k.username) == numara
        ]
        if benzer:
            adlar = ", ".join(k.username for k in benzer)
            self.stdout.write(
                self.style.WARNING(
                    f"Aynı numaranın başka biçimde açılmış hesabı var: {adlar}. "
                    f"Bayi {numara} yazınca giremez; kullanıcı adını düzeltin."
                )
            )
