import django.core.validators
from decimal import Decimal
from django.db import migrations, models


def sifirlari_bosalt(apps, schema_editor):
    """0 % + 0 ₺ "alış fiyatına sat" demekti; kimse bunu istemedi, boş = satılmaz."""
    FiyatGrubu = apps.get_model("kontor", "FiyatGrubu")
    FiyatGrubu.objects.filter(oran=0, ek_tutar=0).update(oran=None, ek_tutar=None)


class Migration(migrations.Migration):

    dependencies = [
        ("kontor", "0007_paket_fiyat_yontemi"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="fiyatgrubu",
            options={
                "ordering": ["ad"],
                "verbose_name": "Kontör Fiyat Grubu",
                "verbose_name_plural": "Kontör Fiyat Grupları",
            },
        ),
        migrations.AlterField(
            model_name="fiyatgrubu",
            name="oran",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="İsteğe bağlı. Boşsa (ek tutar da boşsa) fiyatı yazılmamış paket bu gruba satılmaz.",
                max_digits=6,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Kuralsız paket: alışın üstüne (%)",
            ),
        ),
        migrations.AlterField(
            model_name="fiyatgrubu",
            name="ek_tutar",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="İsteğe bağlı; yüzdenin üstüne eklenir.",
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Kuralsız paket: ek tutar (₺)",
            ),
        ),
        migrations.RunPython(sifirlari_bosalt, migrations.RunPython.noop),
    ]
