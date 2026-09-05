"""Tarifenin tek kategorisini çoklu kategori alanına taşır.

Aynı paket birden çok kategoride geçerli olabiliyor; tarifeyi her kategori
için yeniden açmak gerekmesin diye alan çoğullandı. Var olan tarifelerin
kategorisi burada yeni alana kopyalanır, sonraki migration eskisini düşürür.
"""

from django.db import migrations


def ileri(apps, schema_editor):
    Tarife = apps.get_model("katalog", "Tarife")
    for tarife in Tarife.objects.exclude(kategori__isnull=True).iterator():
        tarife.kategoriler.add(tarife.kategori_id)


def geri(apps, schema_editor):
    """Geri alınırsa ilk kategoriyi tek alana yazar.

    Birden çok kategoriye bağlanmış tarifede ilki seçilir; geri dönüş
    kayıpsız olamaz, çünkü hedef alan tek değer tutuyor.
    """
    Tarife = apps.get_model("katalog", "Tarife")
    for tarife in Tarife.objects.iterator():
        ilki = tarife.kategoriler.order_by("sira", "ad").first()
        if ilki is not None:
            tarife.kategori_id = ilki.pk
            tarife.save(update_fields=["kategori"])


class Migration(migrations.Migration):

    dependencies = [("katalog", "0010_tarife_kategoriler_ekle")]

    operations = [migrations.RunPython(ileri, geri)]
