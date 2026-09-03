"""Türkçe harf içeren slug'ları düzeltir.

Django'nun slugify'ı ASCII dışı harfleri düşürdüğü için "Faturalı Yeni Hat"
-> "fatural-yeni-hat", "Numara Taşıma" -> "numara-tasma" gibi bozuk slug'lar
oluşmuştu. Bu slug'lar URL'lerde göründüğü için düzeltiliyor.
"""

from django.db import migrations

from apps.katalog.utils import turkce_slug


def sluglari_duzelt(apps, schema_editor):
    for model_adi in ("Operator", "BasvuruKategorisi"):
        Model = apps.get_model("katalog", model_adi)
        for nesne in Model.objects.all():
            dogru = turkce_slug(nesne.ad)
            if nesne.slug != dogru:
                nesne.slug = dogru
                nesne.save(update_fields=["slug"])


def geri_al(apps, schema_editor):
    """Slug'lar veriye özgü; geri alma işlemi anlamsız olduğu için boş."""


class Migration(migrations.Migration):
    dependencies = [("katalog", "0001_initial")]

    operations = [migrations.RunPython(sluglari_duzelt, geri_al)]
