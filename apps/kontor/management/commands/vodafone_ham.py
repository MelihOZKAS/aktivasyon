"""Vodafone Kolay Paket cevabını ham JSON olarak yazar.

Paket kodu eşleşmesi (`Paket.kod` ↔ Vodafone'un paket alanı) yanlış
kurulunca hangi alanın ne taşıdığını görmek için. Hat sahibinin adı
istenmez; yalnızca token ve paket listesi çekilir.

    manage.py vodafone_ham 5XXXXXXXXX            # ilk 3 paket, bütün alanlarıyla
    manage.py vodafone_ham 5XXXXXXXXX --hepsi
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.kontor.sorgu import SorguHatasi


class Command(BaseCommand):
    help = "Vodafone Kolay Paket cevabını ham JSON olarak yazar (alan eşleştirmesi için)."

    def add_arguments(self, parser):
        parser.add_argument("numara")
        parser.add_argument("--hepsi", action="store_true", help="Bütün paketleri yaz.")

    def handle(self, numara, hepsi, **_):
        from apps.kontor.sorgu.vodafone import istemci_ac

        # Bayinin sorgusuyla aynı yol: Genel Ayarlar'da anahtar varsa proxy'den.
        try:
            istemci, proxy = istemci_ac()
        except SorguHatasi as hata:
            raise CommandError(str(hata))
        self.stderr.write("Proxy üzerinden." if proxy else "Doğrudan (proxy anahtarı yok).")
        token = (istemci.get_public_token(numara) or {}).get("publicToken")
        if not token:
            raise CommandError("publicToken alınamadı; numara Vodafone'da değil ya da servis cevap vermedi.")
        cevap = istemci.get_kolay_packs(token)
        kategoriler = cevap.get("kolayPackCategory") or []
        if not hepsi:
            kategoriler = [
                {**k, "kolayPacks": (k.get("kolayPacks") or [])[:3]} for k in kategoriler[:2]
            ]
        self.stdout.write(json.dumps({"kolayPackCategory": kategoriler}, ensure_ascii=False, indent=2))
