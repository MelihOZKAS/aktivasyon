# Generated by Django 4.2.2 on 2023-07-10 21:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('basvurular', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='operatorleri',
            options={'verbose_name_plural': '83. ADSL Operatorleri '},
        ),
        migrations.AlterModelOptions(
            name='operatortarifeleri',
            options={'verbose_name_plural': '84. ADSL Operator Tarifeleri'},
        ),
        migrations.AddField(
            model_name='evrak',
            name='aktivasyon_durumu',
            field=models.CharField(blank=True, choices=[('Beklemede', 'Beklemede'), ('İşlemde', 'İşlemde'), ('Eksik Evrak', 'Eksik Evrak'), ('Aktif', 'Aktif'), ('Hatalı', 'Hatalı')], default='Beklemede', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='evrak',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='evrakpass',
            name='aktivasyon_durumu',
            field=models.CharField(blank=True, choices=[('Beklemede', 'Beklemede'), ('İşlemde', 'İşlemde'), ('Eksik Evrak', 'Eksik Evrak'), ('Aktif', 'Aktif'), ('Hatalı', 'Hatalı')], default='Beklemede', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='evrakpass',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='faturaliyenihat',
            name='aktivasyon_durumu',
            field=models.CharField(blank=True, choices=[('Beklemede', 'Beklemede'), ('İşlemde', 'İşlemde'), ('Eksik Evrak', 'Eksik Evrak'), ('Aktif', 'Aktif'), ('Hatalı', 'Hatalı')], default='Beklemede', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='faturaliyenihat',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='internet',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='kontorluyenihat',
            name='aktivasyon_durumu',
            field=models.CharField(blank=True, choices=[('Beklemede', 'Beklemede'), ('İşlemde', 'İşlemde'), ('Eksik Evrak', 'Eksik Evrak'), ('Aktif', 'Aktif'), ('Hatalı', 'Hatalı')], default='Beklemede', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='kontorluyenihat',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='sebekeici',
            name='aktivasyon_durumu',
            field=models.CharField(blank=True, choices=[('Beklemede', 'Beklemede'), ('İşlemde', 'İşlemde'), ('Eksik Evrak', 'Eksik Evrak'), ('Aktif', 'Aktif'), ('Hatalı', 'Hatalı')], default='Beklemede', max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='sebekeici',
            name='odeme_durumu',
            field=models.CharField(blank=True, choices=[('OdemeYapilmadi', 'OdemeYapilmadi'), ('OdemeYapildi', 'OdemeYapildi'), ('Hatalı', 'Hatalı')], default='OdemeYapilmadi', max_length=20, null=True),
        ),
    ]
