"""SIM kart stok hareketleri."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.bayi.models import SimKart, SimKartDurumu

logger = logging.getLogger(__name__)


def basvurunun_simlerini_serbest_birak(basvuru):
    """Başvuru olumsuz sonuçlandığında SIM kartları bayinin stoğuna döndürür.

    Operatörden iptal gelen ya da geçişi yapılamayan bir başvuruda kart
    fiziksel olarak bayinin elinde duruyor; sistemde "kullanıldı" kalırsa
    çöpe çıkmış olur. Bu yüzden karta yeniden işlem yapılabilir hâle
    getiriyoruz. Hangi başvuruda kullanıldığı bilgisi izlenebilirlik için
    korunur; kart yeniden kullanılırsa yeni başvuruyla güncellenir.
    """
    if not basvuru.bayi_id:
        return 0

    adet = SimKart.objects.filter(
        basvuru=basvuru, durum=SimKartDurumu.KULLANILDI
    ).update(durum=SimKartDurumu.ATANDI)

    if adet:
        logger.info(
            "Başvuru %s olumsuz sonuçlandı, %s SIM kart bayinin stoğuna döndü.",
            basvuru.referans_no,
            adet,
        )
    return adet


# --- arızalı kart takibi -------------------------------------------------
#
# Bozuk kart için para hareketi yoktur, kart takası vardır: bayi kartın
# parasını (nakit ya da başvuruda) zaten ödedi, ona para değil kart
# borçluyuz. İade edip yeniden tahsil etseydik kartın o günkü fiyatı
# (100 → 150) araya girerdi; bire bir değişimde girmez.


class ArizaHatasi(Exception):
    """Arıza adımı yapılamadı; sebebi mesajda."""


def sim_arizali_isaretle(kart, *, bildiren=None):
    """Kartı arızalıya düşürür. Başvuru bağı ve bayi korunur: hangi işlemde
    bozulduğu ve kimde durduğu takibin kendisidir."""
    if kart.arizali:
        return kart
    kart.durum = SimKartDurumu.ARIZALI
    kart.ariza_tarihi = timezone.now()
    kart.ariza_bildiren = bildiren
    kart.save(update_fields=["durum", "ariza_tarihi", "ariza_bildiren", "guncelleme_tarihi"])
    logger.info("SIM %s arızalı işaretlendi.", kart.imei)
    return kart


def sim_bayiden_alindi(kart):
    """Bozuk kart elimize geçti. İkinci kez basılırsa tarih değişmez."""
    if not kart.arizali:
        raise ArizaHatasi(f"{kart.imei} arızalı değil.")
    if kart.iade_alinma_tarihi is not None:
        return False
    kart.iade_alinma_tarihi = timezone.now()
    kart.save(update_fields=["iade_alinma_tarihi", "guncelleme_tarihi"])
    return True


def sim_degisimi_alindi(kart):
    """Operatör bozuk kartın yerine yenisini verdi. Yeni kart burada
    açılmaz — “Toplu ekle” ile stoğa girer; burada yalnızca alacak kapanır."""
    if not kart.arizali:
        raise ArizaHatasi(f"{kart.imei} arızalı değil.")
    if kart.degisim_tarihi is not None:
        return False
    kart.degisim_tarihi = timezone.now()
    kart.save(update_fields=["degisim_tarihi", "guncelleme_tarihi"])
    return True


def sim_yerine_ver(kart, yeni_kart):
    """Bozuk kartın yerine bayiye stoktan kart zimmetler ve ikisini bağlar.

    Yeni kart stokta (Beklemede) ve aynı operatörün kartı olmalı: hatlar
    BTK'da IMEI bazında lisanslı, Vodafone kartı Turkcell kartının yerini
    tutmaz. Kilit, iki yöneticinin aynı kartı iki bayiye vermesini önler.
    """
    if not kart.arizali:
        raise ArizaHatasi(f"{kart.imei} arızalı değil.")
    if not kart.bayi_id:
        raise ArizaHatasi(f"{kart.imei} bir bayide değildi; yerine kart verilecek kimse yok.")
    if kart.yerine_verilen_id:
        raise ArizaHatasi(f"{kart.imei} yerine zaten kart verildi.")
    if yeni_kart.pk == kart.pk:
        raise ArizaHatasi("Kartın yerine kendisi verilemez.")
    if kart.operator_id and yeni_kart.operator_id and kart.operator_id != yeni_kart.operator_id:
        raise ArizaHatasi(
            f"{yeni_kart.imei} {yeni_kart.operator.ad} kartı; "
            f"{kart.operator.ad} kartının yerini tutmaz."
        )

    with transaction.atomic():
        adet = SimKart.objects.filter(
            pk=yeni_kart.pk, durum=SimKartDurumu.BEKLEMEDE, bayi__isnull=True
        ).update(bayi=kart.bayi, durum=SimKartDurumu.ATANDI)
        if not adet:
            raise ArizaHatasi(f"{yeni_kart.imei} stokta değil; bu sırada başka yere verilmiş olabilir.")
        kart.yerine_verilen_id = yeni_kart.pk
        kart.save(update_fields=["yerine_verilen", "guncelleme_tarihi"])

    yeni_kart.refresh_from_db()
    logger.info("SIM %s yerine %s bayiye verildi.", kart.imei, yeni_kart.imei)
    return yeni_kart


class HesapAcilamadi(Exception):
    """Başvurudan hesap açılamadı; sebebi mesajda."""


def bayi_hesabi_ac(basvuru):
    """Onaylanan bir bayi başvurusundan hesap açar.

    Kullanıcı adı telefon numarasıdır; parola başvuru sırasında başvuranın
    kendisi tarafından seçilmiştir ve burada özet olarak taşınır — düz metin
    parola bu akışın hiçbir yerinde bulunmaz.

    Eski başvurularda parola olmayabilir; o hâlde hesap kullanılamaz parolayla
    açılır ve yönetici panelden parola belirler.

    **Fiyat kademesi olmadan hesap açılmaz.** Kademesiz cüzdanda bayi grubuna
    bağlı hakediş kuralları işlemez: bayi başvuru girer, karşılığında hiçbir
    şey almaz ve bu ancak "hakedişim yatmadı" dediğinde fark edilir. Uyarı
    yetmiyordu — uyarı okunmayabilir, eksik kademe kapıda durur.

    Aynı başvuru için iki kez çağrılırsa ikinci çağrı hiçbir şey yapmaz.
    """
    from django.contrib.auth.hashers import make_password
    from django.contrib.auth.models import User
    from django.db import transaction

    from apps.bayi.models import BayiBasvuruDurumu, BayiProfili
    from apps.finans.models import Cuzdan

    if basvuru.olusturulan_kullanici_id:
        return basvuru.olusturulan_kullanici, False

    if basvuru.bayi_grubu_id is None:
        raise HesapAcilamadi(
            f"{basvuru.ad_soyad}: fiyat kademesi seçilmeden hesap açılmaz. "
            "Başvuruyu açıp “Fiyat Kademesi” alanını doldurun; kademesiz "
            "cüzdanda hakediş kuralları işlemez."
        )

    kullanici_adi = basvuru.kullanici_adi
    if User.objects.filter(username=kullanici_adi).exists():
        raise HesapAcilamadi(
            f"{kullanici_adi} kullanıcı adı zaten alınmış. "
            "Var olan hesabı başvuruya elle bağlayın."
        )

    with transaction.atomic():
        kullanici = User(
            username=kullanici_adi,
            first_name=basvuru.isim,
            last_name=basvuru.soyisim,
        )
        # Özet doğrudan taşınır; set_password çağrılmaz çünkü elimizde
        # düz metin yok. Parola seçilmemişse hesap girişe kapalı açılır.
        kullanici.password = basvuru.parola_ozeti or make_password(None)
        kullanici.save()

        BayiProfili.objects.create(
            kullanici=kullanici,
            unvan=basvuru.ad_soyad,
            yetkili_adi=basvuru.ad_soyad,
            telefon=basvuru.irtibat,
            bayi_mi=True,
        )
        # Fiyat kademesi cüzdana o anda yazılır; yönetici hesabı açtıktan
        # sonra bir de cüzdan ekranına gitmesin.
        Cuzdan.objects.create(bayi=kullanici, grup=basvuru.bayi_grubu)

        basvuru.olusturulan_kullanici = kullanici
        basvuru.durum = BayiBasvuruDurumu.ONAYLANDI
        basvuru.save(
            update_fields=["olusturulan_kullanici", "durum", "guncelleme_tarihi"]
        )

    logger.info("Bayi başvurusundan hesap açıldı: %s", kullanici_adi)
    return kullanici, True
