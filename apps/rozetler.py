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
