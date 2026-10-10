"""Kurumdaki iki müşteri alanı (tavsiye_ek, tavsiye_fiyati) tek `tavsiye`.

Kontördeki gibi tek "tavsiye satış" rakamı: sorgulu kurumda fatura
tutarının üstüne eklenen, sorgusuz kalemde müşteri fiyatı. Rakam kaybolmaz:
türüne göre doğru alandan kopyalanır, sonra eski alanlar düşer.
"""

from django.db import migrations, models


def tasi(apps, schema_editor):
    Kurum = apps.get_model("fatura", "Kurum")
    for kurum in Kurum.objects.all():
        deger = kurum.tavsiye_ek if kurum.sorgulu else kurum.tavsiye_fiyati
        kurum.tavsiye = deger if deger else None
        kurum.save(update_fields=["tavsiye"])


def geri(apps, schema_editor):
    Kurum = apps.get_model("fatura", "Kurum")
    for kurum in Kurum.objects.all():
        if kurum.sorgulu:
            kurum.tavsiye_ek = kurum.tavsiye or 0
        else:
            kurum.tavsiye_fiyati = kurum.tavsiye
        kurum.save(update_fields=["tavsiye_ek", "tavsiye_fiyati"])


class Migration(migrations.Migration):

    dependencies = [
        ("fatura", "0003_grup_fiyati"),
    ]

    operations = [
        migrations.AddField(
            model_name="kurum",
            name="tavsiye",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True, verbose_name="Müşteriye",
                help_text=(
                    "Bayinin müşteriye söyleyeceği (kontördeki tavsiye satış gibi; gruba göre "
                    "değişmez). Sorgulu kurumda fatura tutarının üstüne eklenen tutar, "
                    "sorgusuz kalemde müşteri fiyatı."
                ),
            ),
        ),
        migrations.RunPython(tasi, geri),
        migrations.RemoveField(model_name="kurum", name="tavsiye_ek"),
        migrations.RemoveField(model_name="kurum", name="tavsiye_fiyati"),
    ]
