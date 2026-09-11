"""Yan menüdeki bekleyen iş sayıları.

Rozet, işin **henüz kimsenin dokunmadığı** hâlini sayar: yeni gelen bayi
başvuruları ve hâlâ başlangıç durumunda duran başvurular. Personel bir
kaydın durumunu değiştirdiği anda sayıdan düşer, böylece rozet "bakılacak
iş" demek olur; toplam kayıt sayısı değil.

Hangi durumun başlangıç sayılacağı koda gömülü değil, veridir:
`BasvuruDurumu.baslangic_durumu`. Yönetici başlangıç durumunu değiştirirse
rozet de onu takip eder.

Sayı sıfırsa boş dize döner ve rozet hiç çizilmez —
`templates/unfold/helpers/app_list_badge.html` bunu bekler.
"""

# Üç haneli sayı yan menüyü dağıtıyor; ötesi zaten "çok birikmiş" demek.
UST_SINIR = 99


def bekleyen_bayi_basvurulari(request):
    """Henüz görüşülmemiş bayi olma talepleri."""
    from apps.bayi.models import BayiBasvurusu, BayiBasvuruDurumu

    return _sayi(BayiBasvurusu.objects.filter(durum=BayiBasvuruDurumu.YENI))


def bekleyen_basvurular(request):
    """Başlangıç durumundan çıkmamış başvurular."""
    from apps.basvurular.models import Basvuru

    return _sayi(Basvuru.objects.filter(durum__baslangic_durumu=True))


def takilan_esimler(request):
    """Sağlayıcıdan profili gelmemiş ya da hataya düşmüş eSIM teslimatları.

    Hazırlanıyor birkaç saniye sürer; dakikalarca sürüyorsa sağlayıcıda
    sorun var, yönetici baksın. Hata zaten iade edilmiştir ama sebebini
    okuyan olmalı — sürekli aynı hata bakiye bitti demektir. Hata kaydı
    durumunu hiç değiştirmediği için yalnızca son bir günün hataları
    sayılır; rozet arşiv değil, bugünkü iş.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.esim.models import Teslimat, TeslimatDurumu

    simdi = timezone.now()
    return _sayi(
        Teslimat.objects.filter(
            durum=TeslimatDurumu.HATA, olusturma_tarihi__gte=simdi - timedelta(days=1)
        )
        | Teslimat.objects.filter(
            durum__in=(TeslimatDurumu.BEKLIYOR, TeslimatDurumu.HAZIRLANIYOR),
            olusturma_tarihi__lt=simdi - timedelta(minutes=5),
        )
    )


def _sayi(sorgu):
    adet = sorgu.count()
    if not adet:
        return ""
    return f"{UST_SINIR}+" if adet > UST_SINIR else str(adet)


def bekleyen_odeme_bildirimleri(request):
    """Bayinin bildirdiği, henüz onaylanmamış havaleler."""
    from apps.finans.models import OdemeBildirimi, OdemeBildirimiDurumu

    return _sayi(
        OdemeBildirimi.objects.filter(durum=OdemeBildirimiDurumu.BEKLIYOR)
    )


def yanit_bekleyen_talepler(request):
    """Bayinin yazdığı, yönetimin henüz yanıtlamadığı destek talepleri.

    Rozet yine "bakılacak iş" sayar: yönetim yanıt yazdığı anda sıra bayiye
    geçer ve talep sayıdan düşer.
    """
    from apps.destek.models import DestekTalebi, TalepDurumu

    return _sayi(
        DestekTalebi.objects.filter(durum=TalepDurumu.ACIK, yanit_bekliyor=True)
    )


def bekleyen_siparisler(request):
    """Verilmiş ama henüz teslim edilmemiş ürün siparişleri."""
    from apps.magaza.models import Siparis, SiparisDurumu

    return _sayi(Siparis.objects.filter(durum=SiparisDurumu.VERILDI))
