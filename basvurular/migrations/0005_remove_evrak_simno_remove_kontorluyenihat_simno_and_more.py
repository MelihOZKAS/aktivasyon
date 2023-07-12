# Generated by Django 4.2.2 on 2023-07-12 07:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('basvurular', '0004_fiyatguruplari_bayi_listesi_aciklama_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='evrak',
            name='simno',
        ),
        migrations.RemoveField(
            model_name='kontorluyenihat',
            name='simno',
        ),
        migrations.AddField(
            model_name='evrak',
            name='simimei',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='simcard',
            name='imei',
            field=models.CharField(max_length=31, unique=True),
        ),
    ]