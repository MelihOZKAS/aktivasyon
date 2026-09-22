"""eSIM kâr özeti: yönetime sağlayıcı alışı / bayiye satış, bayiye kendi kazancı.

Rakamlar hesaplanır, saklanmaz: kaynak teslimatlar ve yüklemelerdir.
Yalnızca **tamamlanmış** iş sayılır (profil gelmiş teslimat, sağlayıcının
kabul ettiği yükleme); iade edilmiş kayıtlar girmez. Başvuru raporundaki
"sonuçlanmamış başvuru sayılmaz" kuralının aynısı.

Bayinin kazancı bizim ödediğimiz bir hakediş **değildir**: bayi müşteriden
tavsiye fiyatla alır, farkı cebinde kalır. Bu yüzden hakediş sayfasına
değil eSIM sayfasına yazılır ve "tavsiye fiyatla" diye nitelenir — bayi
müşteriye başka fiyat verdiyse gerçek kazancı farklıdır.
"""

from decimal import Decimal

from django.db.models import Count, F, Sum
from django.utils import timezone

from apps.bayi.etiket import etiket_satirdan, etiket_sutunlari
from apps.esim.models import Teslimat, TeslimatDurumu, Yukleme, YuklemeDurumu

SIFIR = Decimal("0.00")


def _tamamlananlar(baslangic, bitis):
    """Aralıktaki tamamlanmış teslimatlar ve yüklemeler (iki queryset)."""
    return (
        Teslimat.objects.filter(
            durum=TeslimatDurumu.HAZIR, olusturma_tarihi__gte=baslangic, olusturma_tarihi__lt=bitis
        ),
        Yukleme.objects.filter(
            durum=YuklemeDurumu.TAMAM, olusturma_tarihi__gte=baslangic, olusturma_tarihi__lt=bitis
        ),
    )


def _topla(sorgu):
    ham = sorgu.aggregate(
        adet=Count("id"), satis=Sum("siparis__tutar"), alis=Sum("alis_tl"), tavsiye=Sum("tavsiye_fiyati")
    )
    return {ad: (ham.get(ad) or SIFIR) for ad in ("satis", "alis", "tavsiye")} | {"adet": ham["adet"] or 0}


def _birlestir(*parcalar):
    toplam = {"adet": 0, "satis": SIFIR, "alis": SIFIR, "tavsiye": SIFIR}
    for parca in parcalar:
        for ad in toplam:
            toplam[ad] += parca.get(ad) or 0
    toplam["kar"] = (toplam["satis"] - toplam["alis"]).quantize(SIFIR)
    for ad in ("satis", "alis", "tavsiye"):
        toplam[ad] = Decimal(toplam[ad]).quantize(SIFIR)
    return toplam


def esim_raporu(baslangic, bitis):
    """Yönetim: aralıkta satış, alış, kâr; sağlayıcı ve bayi kırılımıyla."""
    teslimatlar, yuklemeler = _tamamlananlar(baslangic, bitis)
    toplam = _birlestir(_topla(teslimatlar), _topla(yuklemeler))
    toplam["yukleme_adedi"] = yuklemeler.count()

    def kirilim(alan, *etiketler, etiket=None):
        """`alan`a göre gruplar; etiket ilk dolu alandır ya da `etiket(satir, onek)` ile kurulur."""
        satirlar = {}
        for sorgu, kaynak in ((teslimatlar, ""), (yuklemeler, "teslimat__")):
            ham = (
                sorgu.values(kaynak + alan, *(kaynak + e for e in etiketler))
                .annotate(adet=Count("id"), satis=Sum("siparis__tutar"), alis=Sum("alis_tl"))
                .order_by()
            )
            for satir in ham:
                anahtar = satir[kaynak + alan]
                if etiket:
                    ad = etiket(satir, kaynak)
                else:
                    ad = next((satir[kaynak + e] for e in etiketler if satir[kaynak + e]), "—")
                kayit = satirlar.setdefault(
                    anahtar, {"etiket": ad, "adet": 0, "satis": SIFIR, "alis": SIFIR}
                )
                kayit["adet"] += satir["adet"]
                kayit["satis"] += satir["satis"] or 0
                kayit["alis"] += satir["alis"] or 0
        for kayit in satirlar.values():
            kayit["kar"] = (kayit["satis"] - kayit["alis"]).quantize(SIFIR)
            kayit["satis"] = kayit["satis"].quantize(SIFIR)
            kayit["alis"] = kayit["alis"].quantize(SIFIR)
        return sorted(satirlar.values(), key=lambda k: k["kar"], reverse=True)

    return {
        "toplam": toplam,
        "kirilimlar": [
            {"baslik": "Sağlayıcıya göre", "sutun": "Sağlayıcı", "satirlar": kirilim("saglayici_id", "saglayici__ad")},
            {
                "baslik": "En çok kazandıran 10 bayi",
                "sutun": "Bayi",
                "satirlar": kirilim(
                    "siparis__bayi_id", *etiket_sutunlari("siparis__bayi__"),
                    etiket=lambda satir, onek: etiket_satirdan(satir, onek + "siparis__bayi__"),
                )[:10],
            },
        ],
    }


def bayi_aylik_ozet(bayi):
    """Bayi: bu ay kaç eSIM, ne ödedi, tavsiye fiyatla satsa ne kazanır."""
    simdi = timezone.localtime()
    ay_basi = simdi.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    teslimatlar, yuklemeler = _tamamlananlar(ay_basi, simdi)
    toplam = _birlestir(
        _topla(teslimatlar.filter(siparis__bayi=bayi)), _topla(yuklemeler.filter(siparis__bayi=bayi))
    )
    # Tavsiye oranı sıfırken kayıtta tavsiye 0 durur; kazanç hesaplanamaz.
    toplam["kazanc"] = (toplam["tavsiye"] - toplam["satis"]).quantize(SIFIR) if toplam["tavsiye"] else None
    toplam["ay"] = ay_basi.date()
    return toplam
