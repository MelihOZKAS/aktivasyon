"""Durum değişikliği bildirimleri kapatılır.

Telegram grubu her durum değişikliğinde mesajla doluyordu; yönetim yalnızca
yeni başvuruyu, ödeme bildirimini ve bayi başvurusunu görmek istiyor.
Anahtar veri olarak kalır — gerekirse durumun sayfasından yeniden açılır.
"""

from django.db import migrations


def kapat(apps, schema_editor):
    apps.get_model("basvurular", "BasvuruDurumu").objects.update(bildirim_gonder=False)


class Migration(migrations.Migration):
    dependencies = [
        ("basvurular", "0015_rename_ana_hakedis_basvuru_alis_bedeli_and_more"),
    ]

    operations = [
        migrations.RunPython(kapat, migrations.RunPython.noop),
    ]
