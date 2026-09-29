"""Vodafone Kolay Paket cevabını ham JSON olarak yazar.

Paket kodu eşleşmesi (`Paket.kod` ↔ Vodafone'un paket alanı) yanlış
kurulunca hangi alanın ne taşıdığını görmek için. Hat sahibinin adı
istenmez; yalnızca token ve paket listesi çekilir.

    manage.py vodafone_ham 5XXXXXXXXX            # ilk 3 paket, bütün alanlarıyla
    manage.py vodafone_ham 5XXXXXXXXX --hepsi
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.kontor.sorgu.vodafone import ZAMAN_ASIMI


class Command(BaseCommand):
    help = "Vodafone Kolay Paket cevabını ham JSON olarak yazar (alan eşleştirmesi için)."

    def add_arguments(self, parser):
        parser.add_argument("numara")
        parser.add_argument("--hepsi", action="store_true", help="Bütün paketleri yaz.")

    def handle(self, numara, hepsi, **_):
        from apps.kontor.sorgu.vodafone_istemci import VodafoneSorgu

        istemci = VodafoneSorgu(timeout=ZAMAN_ASIMI)
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
