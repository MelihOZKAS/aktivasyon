# Generated by Django 4.2.2 on 2023-07-11 21:01

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('basvurular', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='balance',
            old_name='balance',
            new_name='amount',
        ),
    ]