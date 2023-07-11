from django.db import models

# Create your models here.
import os
import uuid
from django.db import models

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from decimal import Decimal


from django.utils import timezone
from ckeditor.fields import RichTextField

BEKLEMEDE = 'Beklemede'
ISLEMDE = 'İşlemde'
EKSIK_EVRAK = 'Eksik Evrak'
AKTIF = 'Aktif'
HATALI = 'Hatalı'

AKTIVASYON_DURUMU_CHOICES = [
    (BEKLEMEDE, 'Beklemede'),
    (ISLEMDE, 'İşlemde'),
    (EKSIK_EVRAK, 'Eksik Evrak'),
    (AKTIF, 'Aktif'),
    (HATALI, 'Hatalı'),
]





OdemeYapilmadi = 'OdemeYapilmadi'
OdemeYapildi = 'OdemeYapildi'
HATALI = 'Hatalı'

Odeme_DURUMU_CHOICES = [
    (OdemeYapilmadi, 'OdemeYapilmadi'),
    (OdemeYapildi, 'OdemeYapildi'),
    (HATALI, 'Hatalı'),
]

class Duyuru(models.Model):
    baslik = models.CharField(max_length=255)
    icerik = RichTextField()
    tarih = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-tarih']

    class Meta:
        verbose_name_plural = 'Duyurular'



def generate_filename(instance, filename):
    now = timezone.now()
    timestamp = now.strftime('%Y%m%d%H%M%S')
    filename = f'{timestamp}_{filename}'
    return filename


class TurkTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad




    class Meta:
        ordering = ['ad']
        verbose_name_plural = '12. MNT Turk Tarifeler'

class YabanciTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '11. MNT YabanciTarifeler'


class Evrak(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    numara = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    operatoru = models.CharField(max_length=100)
    gececegi_operator = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(TurkTarife, related_name='evrak_turk', blank=True,null=True,on_delete=models.CASCADE)
    tarifeYabanci = models.ForeignKey(YabanciTarife, related_name='evrak_yabanci',  blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    simno = models.CharField(max_length=100)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    ikametgah = models.FileField(upload_to='evrak/', blank=True, null=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = '10. MNT Başvuru Kayıtları'


########################################################################################################


class YeniTurkTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '22. Yeni Kontorlu Turk Tarifeler'

class YeniYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '21. YeniKontorlu Yabanci Tarifeler'

class KontorluYeniHat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    operatoru = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(YeniTurkTarife, related_name='yeni_kontorlu_evrak_turk', blank=True,null=True,on_delete=models.CASCADE)
    tarifeYabanci = models.ForeignKey(YeniYabanciTarife, related_name='yeni_kontorlu_evrak_yabanci', blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    simno = models.CharField(max_length=100)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = '20. Kontörlü Yeni Hat Başvuru Kayıtları'


########################################################################################################



class YeniFaturaliTurkTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '32. Yeni Faturalı Turk Tarifeler'

class YeniFaturaliYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '31. Yeni Faturalı Yabanci Tarifeler'

class FaturaliYeniHat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    operatoru = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(YeniFaturaliTurkTarife, related_name='yeni_faturali_evrak_turk', blank=True,null=True,on_delete=models.CASCADE)
    tarifeYabanci = models.ForeignKey(YeniFaturaliYabanciTarife, related_name='yeni_faturali_evrak_yabanci', blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    simno = models.CharField(max_length=100)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    ikametgah = models.FileField(upload_to='evrak/', blank=True, null=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = '30. Faturalı Yeni Hat Başvuru Kayıtları'


########################################################################################################



class SebekeiciTurkTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '42. SebekeiciTurkTarife'

class SebekeiciYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)
    operator = models.CharField(max_length=100,null=True,blank=True)
    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '41. SebekeiciYabanciTarife'

class Sebekeici(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    numara = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    operatoru = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(SebekeiciTurkTarife, related_name='sebeke_ici_turk', blank=True,null=True,on_delete=models.CASCADE)
    tarifeYabanci = models.ForeignKey(SebekeiciYabanciTarife, related_name='sebeke_ici_yabanci', blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    ikametgah = models.FileField(upload_to='evrak/', blank=True, null=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = '40. Şebeke içi işlemler Başvuru Kayıtları'


########################################################################################################


class Operatorleri(models.Model):
    ad = models.CharField(max_length=255)


    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '83. ADSL Operatorleri '
class OperatorTarifeleri(models.Model):
    ad = models.CharField(max_length=255)
    operatoru = models.ForeignKey(Operatorleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.CASCADE)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = '84. ADSL Operator Tarifeleri'







class Telefon(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad
    class Meta:
        ordering = ['ad']
        verbose_name_plural = '81. Telefon Bilgisi'

class Modemlimi(models.Model):
    ad = models.CharField(max_length=255)
    def __str__(self):
        return self.ad
    class Meta:
        verbose_name_plural = '82. Modem Bilgisi'
class internet(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    sabithat = models.ForeignKey(Telefon,related_name='SabitHat', blank=True,null=True,on_delete=models.CASCADE)
    modemolsunmu = models.ForeignKey(Modemlimi,related_name='ModemDurumu', blank=True,null=True,on_delete=models.CASCADE)
    Operatorler = models.ForeignKey(Operatorleri, related_name='Operatorleri', blank=True,null=True,on_delete=models.CASCADE)
    operatortarife = models.ForeignKey(OperatorTarifeleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    ikametgah = models.FileField(upload_to='evrak/', blank=True, null=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = '80. ADSL Başvuru Kayıtları'


########################################################################################################


class EvrakPass(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    isim = models.CharField(max_length=100)
    soyisim = models.CharField(max_length=100)
    pasaportno = models.CharField(max_length=100)
    numara = models.CharField(max_length=100)
    operator = models.CharField(max_length=100)
    gececegi_operator = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    adres = models.TextField()
    pass1 = models.ImageField(upload_to=generate_filename, blank=True)
    pass2 = models.ImageField(upload_to=generate_filename, blank=True)
    ikametgah = models.FileField(upload_to=generate_filename, blank=True)
    aktivasyon_durumu = models.CharField(max_length=20,choices=AKTIVASYON_DURUMU_CHOICES,default=BEKLEMEDE,blank=True,null=True)
    odeme_durumu = models.CharField(max_length=20,choices=Odeme_DURUMU_CHOICES,default=OdemeYapilmadi,blank=True,null=True)
    BayiAciklama = models.CharField(max_length=255,blank=True,null=True)
    GizliAciklama = models.TextField(blank=True,null=True)
    tutar = models.DecimalField(max_digits=10, decimal_places=2,blank=True, null=True, default=Decimal('0.00'))
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.isim + ' ' + self.soyisim

    class Meta:
        verbose_name_plural = '50. Passaportlu işlemler Başvuru Kayıtları'
