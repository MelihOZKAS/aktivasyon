# Generated by Django 4.2.2 on 2023-07-11 21:32

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('basvurular', '0002_rename_balance_balance_amount'),
    ]

    operations = [
        migrations.CreateModel(
            name='BakiyeHareketleri',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('islem_tutari', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('onceki_bakiye', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('sonraki_bakiye', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('onceki_Borc', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('sonraki_Borc', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('tarih', models.DateTimeField(auto_now_add=True)),
                ('aciklama', models.CharField(max_length=255)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Bakiye Hareketleri',
                'verbose_name_plural': 'Bakiye Hareketleri',
            },
        ),
        migrations.CreateModel(
            name='Banka',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('banka_adi', models.CharField(max_length=100)),
                ('hesap_sahibi', models.CharField(max_length=100)),
                ('hesap_numarasi', models.CharField(max_length=100)),
                ('sube_kodu', models.CharField(max_length=100)),
                ('iban', models.CharField(max_length=50)),
                ('aciklama', models.TextField(blank=True)),
                ('bakiye', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('BayiGormesin', models.BooleanField(default=False, verbose_name='Bayi Gormesin')),
                ('Aktifmi', models.BooleanField(default=True, verbose_name='Aktif mi ?')),
            ],
            options={
                'verbose_name': 'Bankalar',
                'verbose_name_plural': 'Bankalar',
            },
        ),
        migrations.CreateModel(
            name='Bayi_Listesi',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('Bayi_Bakiyesi', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('Borc', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('Tutar', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('islem_durumu', models.CharField(choices=[('islem_sec', 'işlem Türünü Seç'), ('nakit_ekle', 'Nakit/Havele/EFT Bakiye Ekle'), ('borc_ve_bakiye_ekle', 'Hem Borç Hem Bakiye Ekle'), ('bakiye_dus', 'Bakiye Düş'), ('sadece_borc_ekle', 'Sadece Borç Ekle')], default='islem_sec', max_length=20)),
                ('secili_banka', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='basvurular.banka')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Bayi Listesi',
                'verbose_name_plural': 'Bayi Listesi',
            },
        ),
        migrations.RemoveField(
            model_name='balancetransaction',
            name='balance',
        ),
        migrations.DeleteModel(
            name='Balance',
        ),
        migrations.DeleteModel(
            name='BalanceTransaction',
        ),
        migrations.DeleteModel(
            name='Bank',
        ),
    ]
