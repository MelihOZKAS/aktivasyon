import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    """Grup fiyatı paket başına yöntem taşır: net fiyat, alış + %, alış + ₺.

    Var olan satırlar net fiyattır (şimdiye kadar tek anlamı buydu); alan
    yeniden adlandırılır, değeri korunur.
    """

    dependencies = [
        ("kontor", "0006_fiyat_grubu"),
    ]

    operations = [
        migrations.RenameField(model_name="paketfiyati", old_name="fiyat", new_name="deger"),
        migrations.AlterField(
            model_name="paketfiyati",
            name="deger",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Net fiyatta satış tutarı; Alış + % yöntemde yüzde; Alış + ₺ yöntemde eklenen tutar.",
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Değer",
            ),
        ),
        migrations.AddField(
            model_name="paketfiyati",
            name="yontem",
            field=models.CharField(
                choices=[("net", "Net fiyat"), ("yuzde", "Alış + %"), ("tutar", "Alış + ₺")],
                default="net",
                max_length=10,
                verbose_name="Yöntem",
            ),
        ),
    ]
