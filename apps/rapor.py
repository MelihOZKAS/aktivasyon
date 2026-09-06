"""Kârlılık raporu: seçilen tarih aralığında ne kazandık.

Kâr rakamı başvuru listesinin üstünde de duruyor ama orada uygulanan
filtreye bağlı ve kırılımı yok: yönetici "bu ay hangi kategori kazandırdı,
hangi bayi ne getirdi" sorusuna cevap bulamıyordu.

Rakamlar hesaplanır, **saklanmaz**: kaynak yine başvurulardır. İkinci bir
doğruluk kaynağı yaratılmaz.

Aralık **en fazla 31 gündür**. Sınır bilinçli: rapor her açılışta bütün
başvuruları tarıyor, tarih alanı indeksli olsa da yıllık bir aralık
sunucuyu boşuna yorar. Bir ayı geçen soru zaten ayrı bir rapordur.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from unfold.widgets import UnfoldAdminTextInputWidget

SIFIR = Decimal("0.00")

# Aralık sınırı: gün sayısı (başlangıç ve bitiş dahil).
EN_UZUN_ARALIK = 31

# Varsayılan: bugün dahil son 30 gün.
VARSAYILAN_GUN = 30


class AralikFormu(forms.Form):
    """Rapor aralığı. Bitiş günü aralığa dahildir."""

    baslangic = forms.DateField(
        label="Başlangıç",
        widget=UnfoldAdminTextInputWidget(attrs={"type": "date"}),
    )
    bitis = forms.DateField(
        label="Bitiş",
        widget=UnfoldAdminTextInputWidget(attrs={"type": "date"}),
    )

    def clean(self):
        temiz = super().clean()
        baslangic, bitis = temiz.get("baslangic"), temiz.get("bitis")
        if not (baslangic and bitis):
            return temiz

        if bitis < baslangic:
            raise forms.ValidationError("Bitiş tarihi başlangıçtan önce olamaz.")

        gun = (bitis - baslangic).days + 1
        if gun > EN_UZUN_ARALIK:
            raise forms.ValidationError(
                f"Aralık en fazla {EN_UZUN_ARALIK} gün olabilir; "
                f"{gun} gün seçtiniz. Daha uzun bir dönem için aralığı bölün."
            )
        return temiz


def _gun_baslangici(gun):
    """Tarihi zaman dilimine bağlı bir ana çevirir.

    Saf tarihle karşılaştırmak Django'da uyarı üretir ve sınır bir gün
    kayabilir; `GunAraligiFiltresi` de aynı yolu izler.
    """
    an = datetime.combine(gun, time.min)
    return timezone.make_aware(an) if timezone.is_naive(an) else an


def _araligi_coz(request):
    """GET'ten aralığı okur; yoksa ya da geçersizse varsayılana düşer."""
    bugun = timezone.localdate()
    varsayilan = (bugun - timedelta(days=VARSAYILAN_GUN - 1), bugun)

    if not (request.GET.get("baslangic") or request.GET.get("bitis")):
        return AralikFormu(initial={"baslangic": varsayilan[0], "bitis": varsayilan[1]}), varsayilan

    form = AralikFormu(request.GET)
    if not form.is_valid():
        return form, varsayilan
    return form, (form.cleaned_data["baslangic"], form.cleaned_data["bitis"])


# Rapordaki her satırın para kalemleri. Tek yerde durur: toplam da, kırılım
# da buradan üretilir, biri güncellenip diğeri unutulmaz.
KALEMLER = {
    "tahsilat": "tahsil_edilen",
    "giris": "giris_bedeli",
    "prim": "alinan_prim",
    "hakedis": "hakedis",
    "maliyet": "alis_bedeli",
}


def _satir(toplamlar, adet=0, **ek):
    """Ham toplamlardan kâr satırı üretir.

    Toplam kuruşsuz dönebiliyor (100 gibi); para her yerde iki hanesiyle
    görünmeli, yoksa tabloda rakamlar hizasız kalıyor.
    """
    deger = {ad: (toplamlar.get(ad) or SIFIR).quantize(SIFIR) for ad in KALEMLER}
    gelir = deger["tahsilat"] + deger["giris"] + deger["prim"]
    gider = deger["hakedis"] + deger["maliyet"]
    return {
        **deger,
        **ek,
        "adet": adet,
        "gelir": gelir.quantize(SIFIR),
        "gider": gider.quantize(SIFIR),
        "kar": (gelir - gider).quantize(SIFIR),
    }


def _toplamlar(sorgu):
    return sorgu.aggregate(
        adet=Count("id"), **{ad: Sum(alan) for ad, alan in KALEMLER.items()}
    )


def _kirilim(sorgu, alan, etiket_alani):
    """Verilen alana göre gruplar, kâra göre sıralar."""
    satirlar = [
        _satir(ham, adet=ham["adet"], etiket=ham[etiket_alani] or "—")
        for ham in sorgu.values(alan, etiket_alani)
        .annotate(adet=Count("id"), **{ad: Sum(a) for ad, a in KALEMLER.items()})
        .order_by()
    ]
    return sorted(satirlar, key=lambda s: s["kar"], reverse=True)


def _gunluk(sorgu, baslangic, bitis):
    """Günlük kâr; aralık 31 günle sınırlı olduğu için tablo kısa kalır."""
    from django.db.models.functions import TruncDate

    ham = {
        satir["gun"]: satir
        for satir in sorgu.annotate(gun=TruncDate("sonuclanma_tarihi"))
        .values("gun")
        .annotate(adet=Count("id"), **{ad: Sum(a) for ad, a in KALEMLER.items()})
        .order_by()
    }

    gunler = []
    gun = baslangic
    while gun <= bitis:
        veri = ham.get(gun)
        gunler.append(_satir(veri or {}, adet=(veri or {}).get("adet", 0), etiket=gun))
        gun += timedelta(days=1)
    return gunler


@staff_member_required
def karlilik(request):
    from apps.basvurular.models import Basvuru
    from apps.ozet import admin_baglami

    form, (baslangic, bitis) = _araligi_coz(request)

    # Sonuçlanma tarihine göre: kâr ancak işlem sonuçlanınca kesinleşir.
    # Henüz sonuçlanmamış başvurunun parası da yarım işlenmiş olur.
    sorgu = Basvuru.objects.filter(
        sonuclanma_tarihi__gte=_gun_baslangici(baslangic),
        sonuclanma_tarihi__lt=_gun_baslangici(bitis) + timedelta(days=1),
    )

    ham = _toplamlar(sorgu)
    liste = reverse("admin:basvurular_basvuru_changelist")

    return render(
        request,
        "admin/rapor.html",
        {
            **admin_baglami(request),
            "title": "Kârlılık Raporu",
            "form": form,
            "baslangic": baslangic,
            "bitis": bitis,
            "gun_sayisi": (bitis - baslangic).days + 1,
            "en_uzun_aralik": EN_UZUN_ARALIK,
            "toplam": _satir(ham, adet=ham["adet"] or 0),
            # Kırılımlar aynı tabloyu paylaşır; şablonda tek döngü var.
            "kirilimlar": [
                {
                    "baslik": "Kategoriye göre",
                    "sutun": "Kategori",
                    "satirlar": _kirilim(sorgu, "kategori_id", "kategori__ad"),
                },
                {
                    "baslik": "Operatöre göre",
                    "sutun": "Operatör",
                    "satirlar": _kirilim(sorgu, "operator_id", "operator__ad"),
                },
                {
                    "baslik": "En çok kazandıran 10 bayi",
                    "sutun": "Bayi",
                    "satirlar": _kirilim(sorgu, "bayi_id", "bayi__username")[:10],
                },
                {
                    "baslik": "Günlük",
                    "sutun": "Gün",
                    "satirlar": _gunluk(sorgu, baslangic, bitis),
                },
            ],
            "basvuru_listesi": liste,
        },
    )
