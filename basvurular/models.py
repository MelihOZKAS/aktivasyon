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
MUTABAKAT = 'Mutabakat Bekliyor'

AKTIVASYON_DURUMU_CHOICES = [
    (BEKLEMEDE, 'Beklemede'),
    (ISLEMDE, 'İşlemde'),
    (EKSIK_EVRAK, 'Eksik Evrak'),
    (AKTIF, 'Aktif'),
    (HATALI, 'Hatalı'),
    (MUTABAKAT, 'Mutabakat Bekliyor'),
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
    gececegi_operator = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(TurkTarife, related_name='evrak_turk', blank=True,null=True,on_delete=models.SET_NULL)
    tarifeYabanci = models.ForeignKey(YabanciTarife, related_name='evrak_yabanci',  blank=True,null=True,on_delete=models.SET_NULL)
    aks = models.CharField(max_length=255)
    simimei = models.CharField(max_length=255,blank=True,null=True)
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
    simimei = models.CharField(max_length=255,blank=True,null=True)
    operatoru = models.CharField(max_length=100)
    tarifeTurk = models.ForeignKey(YeniTurkTarife, related_name='yeni_kontorlu_evrak_turk', blank=True,null=True,on_delete=models.SET_NULL)
    tarifeYabanci = models.ForeignKey(YeniYabanciTarife, related_name='yeni_kontorlu_evrak_yabanci', blank=True,null=True,on_delete=models.SET_NULL)
    aks = models.CharField(max_length=255)
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
    tarifeTurk = models.ForeignKey(YeniFaturaliTurkTarife, related_name='yeni_faturali_evrak_turk', blank=True,null=True,on_delete=models.SET_NULL)
    tarifeYabanci = models.ForeignKey(YeniFaturaliYabanciTarife, related_name='yeni_faturali_evrak_yabanci', blank=True,null=True,on_delete=models.SET_NULL)
    aks = models.CharField(max_length=255)
    simimei = models.CharField(max_length=255,blank=True,null=True)
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
    tarifeTurk = models.ForeignKey(SebekeiciTurkTarife, related_name='sebeke_ici_turk', blank=True,null=True,on_delete=models.SET_NULL)
    tarifeYabanci = models.ForeignKey(SebekeiciYabanciTarife, related_name='sebeke_ici_yabanci', blank=True,null=True,on_delete=models.SET_NULL)
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
    operatoru = models.ForeignKey(Operatorleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.SET_NULL)

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
    sabithat = models.ForeignKey(Telefon,related_name='SabitHat', blank=True,null=True,on_delete=models.SET_NULL)
    modemolsunmu = models.ForeignKey(Modemlimi,related_name='ModemDurumu', blank=True,null=True,on_delete=models.SET_NULL)
    Operatorler = models.ForeignKey(Operatorleri, related_name='Operatorleri', blank=True,null=True,on_delete=models.SET_NULL)
    operatortarife = models.ForeignKey(OperatorTarifeleri, related_name='OperatorTarifeleri', blank=True,null=True,on_delete=models.SET_NULL)
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










class Banka(models.Model):
    banka_adi = models.CharField(max_length=100)
    hesap_sahibi = models.CharField(max_length=100)
    hesap_numarasi = models.CharField(max_length=100)
    sube_kodu = models.CharField(max_length=100)
    iban = models.CharField(max_length=50)
    aciklama = models.TextField(blank=True)
    bakiye = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    BayiGormesin = models.BooleanField("Bayi Gormesin", default=False)
    Aktifmi = models.BooleanField("Aktif mi ?", default=True)

    def __str__(self):
        return self.banka_adi

    class Meta:
        verbose_name = "Bankalar"
        verbose_name_plural = "Bankalar"


class FiyatKategorisi(models.Model):
    kategori_adi = models.CharField(max_length=255)

    def __str__(self):
        return self.kategori_adi

class Urun(models.Model):
    fiyat_kategorisi = models.ForeignKey(FiyatKategorisi, on_delete=models.SET_NULL, null=True)
    urun_adi = models.CharField(max_length=255)
    urun_fiyati = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.fiyat_kategorisi.kategori_adi} - {self.urun_adi} - {self.urun_fiyati}"




class BakiyeHareketleri(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    islem_tutari = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    onceki_bakiye = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    sonraki_bakiye = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    onceki_Borc = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    sonraki_Borc = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    tarih = models.DateTimeField(auto_now_add=True)
    aciklama = models.TextField(null=True,blank=True)
    class Meta:
        verbose_name = "Bakiye Hareketleri"
        verbose_name_plural = "Bakiye Hareketleri"



class SimCard(models.Model):
    bayi = models.ForeignKey(User, on_delete=models.CASCADE)
    operator = models.CharField(max_length=100,null=True,blank=True)
    imei = models.CharField(max_length=31,unique=True)
    status = models.CharField(max_length=20, choices=(
        ('used', 'Kullanıldı'),
        ('pending', 'Beklemede'),
    ), default='pending')
    dist_status = models.CharField(max_length=20, choices=(
        ('calculated', 'Hesaplandı'),
        ('pending', 'Beklemede'),
    ), default='pending')

    def __str__(self):
        return f"{self.imei} - {self.bayi.username} - {self.status} - {self.dist_status}"





class Bayi_Listesi(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    Fiyati = models.ForeignKey(FiyatKategorisi, on_delete=models.SET_NULL, blank=True, null=True)
    Bayi_Bakiyesi = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    Borc = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    Tutar = models.DecimalField(max_digits=10, decimal_places=2,default=0)
    secili_banka = models.ForeignKey(Banka, on_delete=models.SET_NULL,null=True,default=None)
    aciklama = models.CharField(max_length=255)
    islem_durumu = models.CharField(max_length=20, choices=(
        ('islem_sec', 'işlem Türünü Seç'),
        ('nakit_ekle', 'Nakit/Havele/EFT Bakiye Ekle'),
        ('borc_ve_bakiye_ekle', 'Hem Borç Hem Bakiye Ekle'),
        ('bakiye_dus', 'Bakiye Düş'),
        ('sadece_borc_ekle', 'Sadece Borç Ekle'),
        ('borc_dus_bakiye_ekle', 'Borç Düş Bakiye Ekle'),
    ), default='islem_sec')



    def save(self, *args, **kwargs):
        if self.pk is None:  # Yeni bir nesne oluşturuluyorsa
            self.Tutar = 0  # Tutar alanını sıfırla

        # Önce bayi bakiyesine tutarı ekle
        onceki_bakiye = self.Bayi_Bakiyesi
        onceki_Borc = self.Borc



        if self.islem_durumu == "nakit_ekle":
            self.Bayi_Bakiyesi += self.Tutar
            # Sonra seçili bankanın bakiyesine de tutarı ekle
            if self.secili_banka is not None and self.Tutar > 0:
                self.secili_banka.bakiye += self.Tutar

                self.secili_banka.save()

        elif self.islem_durumu == "borc_dus_bakiye_ekle":
            if self.Tutar > self.Borc:
                self.Bayi_Bakiyesi += self.Tutar - self.Borc
                self.Borc = 0
            else:
                self.Borc -= self.Tutar


        elif self.islem_durumu == "borc_ve_bakiye_ekle":
            self.Bayi_Bakiyesi += self.Tutar
            self.Borc += self.Tutar
        elif self.islem_durumu == "bakiye_dus":
            self.Bayi_Bakiyesi -= self.Tutar
        elif self.islem_durumu == "sadece_borc_ekle":
            self.Borc += self.Tutar


        # En son Bayi_Listesi nesnesini kaydet

        sonraki_bakiye = self.Bayi_Bakiyesi
        sonraki_Borc = self.Borc

        bakiye_hareketi = BakiyeHareketleri.objects.create(
            user=self.user,
            islem_tutari=self.Tutar,
            onceki_bakiye=onceki_bakiye,
            sonraki_bakiye=sonraki_bakiye,
            onceki_Borc=onceki_Borc,
            sonraki_Borc=sonraki_Borc,
            aciklama=f'Admin Tarafından: {self.secili_banka} - {self.aciklama} ',
        )
        bakiye_hareketi.save()
        super(Bayi_Listesi, self).save(*args, **kwargs)


        # Tutar alanını sıfırla
        self.Tutar = 0
        super(Bayi_Listesi, self).save(update_fields=['Tutar'])

    class Meta:
        verbose_name = "Bayi Listesi"
        verbose_name_plural = "Bayi Listesi"








