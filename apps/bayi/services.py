"""SIM kart stok hareketleri."""

import logging

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
