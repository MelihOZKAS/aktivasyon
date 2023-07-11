# Generated by Django 4.2.2 on 2023-07-11 11:18

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('basvurular', '0002_alter_operatorleri_options_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='evrak',
            options={'verbose_name_plural': '10. MNT Başvuru Kayıtları'},
        ),
        migrations.AlterModelOptions(
            name='evrakpass',
            options={'verbose_name_plural': '50. Passaportlu işlemler Başvuru Kayıtları'},
        ),
        migrations.AlterModelOptions(
            name='faturaliyenihat',
            options={'verbose_name_plural': '30. Faturalı Yeni Hat Başvuru Kayıtları'},
        ),
        migrations.AlterModelOptions(
            name='kontorluyenihat',
            options={'verbose_name_plural': '20. Kontörlü Yeni Hat Başvuru Kayıtları'},
        ),
        migrations.AlterModelOptions(
            name='sebekeici',
            options={'verbose_name_plural': '40. Şebeke içi işlemler Başvuru Kayıtları'},
        ),
        migrations.AlterModelOptions(
            name='sebekeiciturktarife',
            options={'verbose_name_plural': '42. SebekeiciTurkTarife'},
        ),
        migrations.AlterModelOptions(
            name='sebekeiciyabancitarife',
            options={'verbose_name_plural': '41. SebekeiciYabanciTarife'},
        ),
        migrations.AlterModelOptions(
            name='turktarife',
            options={'ordering': ['ad'], 'verbose_name_plural': '12. MNT Turk Tarifeler'},
        ),
        migrations.AlterModelOptions(
            name='yabancitarife',
            options={'verbose_name_plural': '11. MNT YabanciTarifeler'},
        ),
        migrations.AlterModelOptions(
            name='yenifaturaliturktarife',
            options={'verbose_name_plural': '32. Yeni Faturalı Turk Tarifeler'},
        ),
        migrations.AlterModelOptions(
            name='yenifaturaliyabancitarife',
            options={'verbose_name_plural': '31. Yeni Faturalı Yabanci Tarifeler'},
        ),
        migrations.AlterModelOptions(
            name='yeniturktarife',
            options={'verbose_name_plural': '22. Yeni Kontorlu Turk Tarifeler'},
        ),
        migrations.AlterModelOptions(
            name='yeniyabancitarife',
            options={'verbose_name_plural': '21. YeniKontorlu Yabanci Tarifeler'},
        ),
        migrations.AddField(
            model_name='evrak',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='evrak',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='evrak',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='evrakpass',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='evrakpass',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='evrakpass',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='faturaliyenihat',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='faturaliyenihat',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='faturaliyenihat',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='internet',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='internet',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='internet',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='kontorluyenihat',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='kontorluyenihat',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='kontorluyenihat',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='sebekeici',
            name='BayiAciklama',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='sebekeici',
            name='GizliAciklama',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sebekeici',
            name='tutar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='yeniturktarife',
            name='operator',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='yeniyabancitarife',
            name='operator',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
