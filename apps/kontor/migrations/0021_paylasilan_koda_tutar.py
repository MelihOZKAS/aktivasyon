"""Paylaşılan Vodafone kodunda (13239) tutar da koda girer.

Kişiye özel tekliflerin fiyatı numaraya göre değişiyor; kod artık
`13239-5g-tam-senlik-30-gb-1060`. Tutarsız eski kodlar (`…-30-gb`) görülen
paketin son fiyatıyla yeni biçime çevrilir: katalogdaki paket fiyatı, karşı
site kodu ve alışıyla birlikte yeni sorgularla eşleşmeye devam eder. Fiyatı
bilinmeyen kayda dokunulmaz; yeni kod zaten varsa (çakışma) eskisi bırakılır.
"""

import re
from decimal import Decimal

from django.db import migrations

ON_EKLER = ("13239-",)
TUTARLI = re.compile(r"-\d+(\.\d+)?$")


def _tutar(fiyat):
    metin = f"{Decimal(fiyat).quantize(Decimal('0.01')):f}"
    return metin.rstrip("0").rstrip(".") if "." in metin else metin


def _eski_mi(kod):
    return kod.startswith(ON_EKLER) and not TUTARLI.search(kod)


def tasi(apps, schema_editor):
    GorulenPaket = apps.get_model("kontor", "GorulenPaket")
    Paket = apps.get_model("kontor", "Paket")

    yeniler = {}  # (kategori_id, eski kod) → yeni kod
    for gorulen in GorulenPaket.objects.filter(kod__startswith=ON_EKLER[0], fiyat__isnull=False):
        if not _eski_mi(gorulen.kod):
            continue
        yeni = f"{gorulen.kod}-{_tutar(gorulen.fiyat)}"[:60]
        yeniler[(gorulen.kategori_id, gorulen.kod)] = yeni
        if GorulenPaket.objects.filter(kaynak=gorulen.kaynak, kod=yeni).exists():
            gorulen.delete()  # yeni biçimdeki kayıt zaten var
            continue
        gorulen.kod = yeni
        gorulen.onceki_fiyat = None  # fiyat artık kodun parçası
        gorulen.save(update_fields=["kod", "onceki_fiyat"])

    for paket in Paket.objects.filter(kod__startswith=ON_EKLER[0]):
        yeni = yeniler.get((paket.kategori_id, paket.kod))
        if not yeni or not _eski_mi(paket.kod):
            continue
        if Paket.objects.filter(kategori_id=paket.kategori_id, kod=yeni).exists():
            continue
        paket.kod = yeni
        paket.save(update_fields=["kod"])


class Migration(migrations.Migration):

    dependencies = [
        ("kontor", "0020_paylasilan_kod_temizligi"),
    ]

    operations = [
        migrations.RunPython(tasi, migrations.RunPython.noop),
    ]
