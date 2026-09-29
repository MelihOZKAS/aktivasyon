import django.core.validators
from decimal import ROUND_HALF_UP, Decimal
from django.db import migrations, models

KURUS = Decimal("0.01")


def nete_cevir(apps, schema_editor):
    """Yöntemli kuralları ve grubun genel oranını bugünkü alışla net fiyata çevirir.

    Bayinin bugün gördüğü fiyat değişmesin: "alış + %" kuralı, genel oranla
    satılan paket de o günkü tutarıyla net fiyat olarak yazılır. Alışı
    olmayan paketin alışa dayanan fiyatı zaten yoktu; satır açılmaz.
    """
    FiyatGrubu = apps.get_model("kontor", "FiyatGrubu")
    Paket = apps.get_model("kontor", "Paket")
    PaketFiyati = apps.get_model("kontor", "PaketFiyati")
    Rota = apps.get_model("kontor", "Rota")

    alislar = {}
    for rota in Rota.objects.filter(aktif=True, saglayici__aktif=True).order_by("sira", "pk"):
        alislar.setdefault(rota.paket_id, rota.alis_fiyati)

    def hesapla(alis, yuzde, tutar):
        yuzde, tutar = Decimal(yuzde or 0), Decimal(tutar or 0)
        return (alis * (1 + yuzde / 100) + tutar).quantize(KURUS, ROUND_HALF_UP)

    for kural in PaketFiyati.objects.exclude(yontem="net"):
        alis = alislar.get(kural.paket_id)
        if alis is None:
            kural.delete()
            continue
        if kural.yontem == "yuzde":
            kural.deger = hesapla(alis, kural.deger, None)
        else:
            kural.deger = hesapla(alis, None, kural.deger)
        kural.yontem = "net"
        kural.save(update_fields=["deger", "yontem"])

    for grup in FiyatGrubu.objects.exclude(oran__isnull=True, ek_tutar__isnull=True):
        dolu = set(PaketFiyati.objects.filter(grup=grup).values_list("paket_id", flat=True))
        yeni = [
            PaketFiyati(paket_id=paket_id, grup=grup, yontem="net", deger=hesapla(alislar[paket_id], grup.oran, grup.ek_tutar))
            for paket_id in Paket.objects.values_list("pk", flat=True)
            if paket_id not in dolu and alislar.get(paket_id) is not None
        ]
        PaketFiyati.objects.bulk_create(yeni)


class Migration(migrations.Migration):
    """Grubun her paketteki fiyatı tek net rakamdır; yöntem ve genel oran kalkar.

    Alış + % / alış + ₺ yalnızca yönetim ekranındaki hesap aracı oldu.
    """

    dependencies = [
        ("kontor", "0008_grup_genel_kurali_istege_bagli"),
    ]

    operations = [
        migrations.RunPython(nete_cevir, migrations.RunPython.noop),
        migrations.RemoveField(model_name="paketfiyati", name="yontem"),
        migrations.RenameField(model_name="paketfiyati", old_name="deger", new_name="fiyat"),
        migrations.AlterField(
            model_name="paketfiyati",
            name="fiyat",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Bayiye Satış",
            ),
        ),
        migrations.RemoveField(model_name="fiyatgrubu", name="oran"),
        migrations.RemoveField(model_name="fiyatgrubu", name="ek_tutar"),
        migrations.AlterField(
            model_name="fiyatgrubu",
            name="varsayilan",
            field=models.BooleanField(
                default=False,
                help_text="Grubu seçilmemiş bayi bu grubun fiyatlarını öder. Yalnızca bir grup varsayılan olabilir; hiçbiri değilse grupsuz bayi paketin kendi satış fiyatını öder.",
                verbose_name="Varsayılan",
            ),
        ),
    ]
