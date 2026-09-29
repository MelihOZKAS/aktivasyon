from django.db import migrations


def eski_vodafone_kodlarini_sil(apps, schema_editor):
    """Vodafone'un `id`siyle yazılmış kayıtlar (`/Prepaid/…`, `BKPM046`) düşer.

    Kod artık `reasonCode`'dur (rakam); eski kayıtlar hiçbir pakete karşılık
    gelmiyor ve yeni kayıtların yanında aynı paket iki kez görünüyordu.
    """
    GorulenPaket = apps.get_model("kontor", "GorulenPaket")
    GorulenPaket.objects.filter(kaynak="vodafone").exclude(kod__regex=r"^[0-9]+$").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("kontor", "0010_paket_satis_yardim"),
    ]

    operations = [
        migrations.RemoveField(model_name="gorulenpaket", name="gorulme_sayisi"),
        migrations.RunPython(eski_vodafone_kodlarini_sil, migrations.RunPython.noop),
    ]
