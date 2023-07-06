from django.db import models

# Create your models here.
import os
import uuid
from django.db import models

from django.db import models
from django.utils import timezone

from django.utils import timezone
from ckeditor.fields import RichTextField




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

    def __str__(self):
        return self.ad




    class Meta:
        ordering = ['ad']
        verbose_name_plural = 'MNT Turk Tarifeler'

class YabanciTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'MNT YabanciTarifeler'

class Evrak(models.Model):
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
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = 'MNT'


########################################################################################################


class YeniTurkTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'Yeni Kontorlu Turk Tarifeler'

class YeniYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'YeniKontorlu Yabanci Tarifeler'

class KontorluYeniHat(models.Model):
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
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = 'Kontörlü Yeni Hat'


########################################################################################################



class YeniFaturaliTurkTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'Yeni Faturalı Turk Tarifeler'

class YeniFaturaliYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'Yeni Faturalı Yabanci Tarifeler'

class FaturaliYeniHat(models.Model):
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
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = 'Faturalı Yeni Hat'


########################################################################################################



class SebekeiciTurkTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'SebekeiciTurkTarife'

class SebekeiciYabanciTarife(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'SebekeiciYabanciTarife'

class Sebekeici(models.Model):
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
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = 'Şebeke içi işlemler'


########################################################################################################


class Operatorleri(models.Model):
    ad = models.CharField(max_length=255)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'Operatorleri ADSL'
class OperatorTarifeleri(models.Model):
    ad = models.CharField(max_length=255)
    operatoru = models.ForeignKey(Operatorleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.CASCADE)

    def __str__(self):
        return self.ad

    class Meta:
        verbose_name_plural = 'ADSL Operator Tarifeleri'



class internet(models.Model):
    kimlik_tipi = models.CharField(max_length=10)
    isim = models.CharField(max_length=255)
    soyisim = models.CharField(max_length=255)
    tc = models.CharField(max_length=100)
    irtibat = models.CharField(max_length=100)
    Operatorler = models.ForeignKey(Operatorleri, related_name='Operatorleri', blank=True,null=True,on_delete=models.CASCADE)
    operatortarife = models.ForeignKey(OperatorTarifeleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.CASCADE)
    aks = models.CharField(max_length=255)
    adres = models.CharField(max_length=255)
    kimlik_on = models.ImageField(upload_to='evrak/', blank=True, null=True)
    kimlik_arka = models.ImageField(upload_to='evrak/', blank=True, null=True)
    ikametgah = models.FileField(upload_to='evrak/', blank=True, null=True)
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.isim} {self.soyisim}"
    class Meta:
        verbose_name_plural = 'ADSL Başvuru Kayıtları'


########################################################################################################


class EvrakPass(models.Model):
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
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.isim + ' ' + self.soyisim

    class Meta:
        verbose_name_plural = 'Passaportlu işlemler'
