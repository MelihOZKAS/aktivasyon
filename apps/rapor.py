"""Kârlılık raporu: seçilen tarih aralığında ne kazandık.

Kâr rakamı başvuru listesinin üstünde de duruyor ama orada uygulanan
filtreye bağlı ve kırılımı yok: yönetici "bu ay hangi kategori kazandırdı,
hangi bayi ne getirdi" sorusuna cevap bulamıyordu.

Bölümler menüdeki sırayla: aktivasyon, kontör, fatura, oyun & pin, eSIM.
Üstte hepsinin toplamı ve bölüm bölüm özet, altta her bölümün kırılımı ve
bölüm sütunlu günlük kâr. Bir süre yalnızca aktivasyon ve eSIM vardı;
kontör, oyun ve faturanın kârı hiçbir ekranda toplanmıyordu.

Rakamlar hesaplanır, **saklanmaz**: kaynak başvurular, kontör işlemleri,
fatura ödemeleri ve eSIM teslimatlarıdır. İkinci bir doğruluk kaynağı
yaratılmaz.

Aralık **en fazla 31 gündür**. Sınır bilinçli: rapor her açılışta bütün
başvuruları tarıyor, tarih alanı indeksli olsa da yıllık bir aralık
sunucuyu boşuna yorar. Bir ayı geçen soru zaten ayrı bir rapordur.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from unfold.widgets import UnfoldAdminTextInputWidget

from apps.bayi.etiket import etiket_satirdan, etiket_sutunlari

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


def _kirilim(sorgu, alan, *etiket_alanlari, etiket=None):
    """Verilen alana göre gruplar, kâra göre sıralar.

    Etiket ilk etiket alanından okunur; birden çok sütundan kurulan etiket
    (bayinin adı · numarası) için `etiket` çağrılabiliri verilir.
    """
    etiket = etiket or (lambda ham: ham[etiket_alanlari[0]] or "—")
    satirlar = [
        _satir(ham, adet=ham["adet"], etiket=etiket(ham))
        for ham in sorgu.values(alan, *etiket_alanlari)
        .annotate(adet=Count("id"), **{ad: Sum(a) for ad, a in KALEMLER.items()})
        .order_by()
    ]
    return sorted(satirlar, key=lambda s: s["kar"], reverse=True)


def _gunluk(sorgu, baslangic, bitis):
    """Günlük kâr; aralık 31 günle sınırlı olduğu için tablo kısa kalır."""
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


# -- Satış bölümleri: kontör, fatura, oyun & pin, eSIM --------------------
#
# Aktivasyonun beş para kalemi var, satış bölümlerinin iki: bayiye satış
# (bayinin ödediği, `siparis.tutar`) ve alışımız. Kâr aradaki farktır.
# Bayinin müşteriden aldığı tavsiye fiyat burada yoktur: o bayinin
# kazancıdır (Kazancım), bizim değil.
#
# Gün **satış günüdür** (`olusturma_tarihi`), Kazancım ve eSIM'le aynı; tarih
# indeksi de (durum, olusturma_tarihi) üzerinde. Yalnızca sonuçlanmış iş
# sayılır: yüklenen kontör, ödenen fatura. Sürerken sayılsaydı iptal olunca
# geçmiş günün kârı düşerdi.
#
# **Alışı kayıtlı olmayan iş kâra katılmaz**, sayısı ve satışı ayrıca
# yazılır. Alış sıfır sayılsaydı satışın tamamı kâr görünürdü (aktivasyonda
# "kural yarım kalmış" uyarısının aynısı). Kontörde sağlayıcı alış vermeyip
# rotada da yazılı değilse, faturada alışı girilmemiş sorgusuz kalemde olur.


def _satis_alanlari():
    """Satış bölümünün toplamları; sorguda `rapor_satis` ve `rapor_alis` olmalı."""
    bilinen = Q(rapor_alis__isnull=False)
    return {
        "adet": Count("id"),
        "satis": Sum("rapor_satis", filter=bilinen),
        "alis": Sum("rapor_alis", filter=bilinen),
        "eksik": Count("id", filter=~bilinen),
        "eksik_satis": Sum("rapor_satis", filter=~bilinen),
    }


def _satis_satiri(ham, **ek):
    satis = (ham.get("satis") or SIFIR).quantize(SIFIR)
    alis = (ham.get("alis") or SIFIR).quantize(SIFIR)
    return {
        **ek,
        "adet": ham.get("adet") or 0,
        "satis": satis,
        "alis": alis,
        "kar": (satis - alis).quantize(SIFIR),
        "eksik": ham.get("eksik") or 0,
        "eksik_satis": (ham.get("eksik_satis") or SIFIR).quantize(SIFIR),
    }


def _satis_kirilimi(sorgu, alan, *etiket_alanlari, etiket=None):
    """`_kirilim`in satış bölümü karşılığı: alana göre gruplar, kâra göre sıralar."""
    etiket_alani = (etiket_alanlari or (alan,))[0]
    etiket = etiket or (lambda ham: ham[etiket_alani] or "—")
    satirlar = [
        _satis_satiri(ham, etiket=etiket(ham))
        for ham in sorgu.values(alan, *etiket_alanlari).annotate(**_satis_alanlari()).order_by()
    ]
    return sorted(satirlar, key=lambda s: s["kar"], reverse=True)


def _satis_bolumu(kod, ad, sorgu, aciklama, kirilimlar):
    """Bölüm: toplam, kırılımlar (sonda en çok kazandıran bayiler) ve gün → satır."""
    return {
        "kod": kod,
        "ad": ad,
        "aciklama": aciklama,
        "toplam": _satis_satiri(sorgu.aggregate(**_satis_alanlari())),
        "kirilimlar": [
            {"baslik": baslik, "sutun": sutun, "satirlar": _satis_kirilimi(sorgu, *alanlar)}
            for baslik, sutun, alanlar in kirilimlar
        ]
        + [
            {
                "baslik": "En çok kazandıran 10 bayi",
                "sutun": "Bayi",
                "satirlar": _satis_kirilimi(
                    sorgu, "bayi_id", *etiket_sutunlari("bayi__"),
                    etiket=lambda ham: etiket_satirdan(ham, "bayi__"),
                )[:10],
            }
        ],
        "gunler": {
            ham["gun"]: _satis_satiri(ham)
            for ham in sorgu.annotate(gun=TruncDate("olusturma_tarihi"))
            .values("gun")
            .annotate(**_satis_alanlari())
            .order_by()
        },
    }


def _kontor_bolumleri(bas, bit):
    """Kontör ve oyun & pin: aynı işlem tablosu, kategorinin oyun işaretiyle ayrılır.

    Alış işlemin kaydındadır (`Islem.alis_tutari`): sağlayıcının cevabı, yoksa
    gönderilen paketin o sağlayıcıdaki rotası. Ucuz alternatif gittiyse onun
    alışıdır, bayinin istediği paketinki değil.
    """
    from apps.kontor.models import Islem, IslemDurumu

    sorgu = Islem.objects.filter(
        durum=IslemDurumu.BASARILI, olusturma_tarihi__gte=bas, olusturma_tarihi__lt=bit
    ).annotate(rapor_satis=F("siparis__tutar"), rapor_alis=F("alis_tutari"))
    saglayici = ("Sağlayıcıya göre", "Sağlayıcı", ("saglayici_id", "saglayici__ad"))
    return (
        _satis_bolumu(
            "kontor", "Kontör", sorgu.exclude(kategori__oyun=True),
            "Aralıkta satılıp yüklenen TL ve paketler. Bayiye satışımız, sağlayıcıdan "
            "alışımız ve aradaki kâr. İptal edilen ve hâlâ süren işlemler sayılmaz.",
            [("Kategoriye göre", "Kategori", ("kategori_id", "kategori__ad")), saglayici],
        ),
        _satis_bolumu(
            "oyun", "Oyun & Pin", sorgu.filter(kategori__oyun=True),
            "Aralıkta satılıp teslim edilen oyun yüklemeleri ve pinler. İptal edilen ve "
            "hâlâ süren işlemler sayılmaz.",
            [("Oyuna göre", "Oyun", ("kategori_id", "kategori__ad")), saglayici],
        ),
    )


def _fatura_bolumu(bas, bit):
    """Ödenen fatura ödemeleri.

    Alış sağlayıcının hesabımızdan düştüğüdür (`Gonderim.dusen`: fatura +
    sağlayıcının işlem bedeli + varsa gecikme faizi). Düşen yazılmamış
    gönderimde gönderilen fatura bedeli alınır. Sağlayıcıya hiç gitmemiş
    (yönetimin elle ödediği) ödemede `Odeme.saglayici_tutari`: faturaların
    bedeli, sorgusuz kalemde kurumun alışı. Elle ödenende sağlayıcının işlem
    bedeli bilinmez. Sayfa bunu yazar.
    """
    from apps.fatura.models import Gonderim, GonderimDurumu, Odeme, OdemeDurumu

    odenen = (
        Gonderim.objects.filter(odeme=OuterRef("pk"), durum=GonderimDurumu.ODENDI)
        .order_by()
        .values("odeme")
        .annotate(toplam=Sum(Coalesce("dusen", "tutar")))
        .values("toplam")
    )
    sorgu = Odeme.objects.filter(
        durum=OdemeDurumu.ODENDI, olusturma_tarihi__gte=bas, olusturma_tarihi__lt=bit
    ).annotate(
        rapor_satis=F("siparis__tutar"),
        rapor_alis=Coalesce(Subquery(odenen), F("saglayici_tutari")),
    )
    return _satis_bolumu(
        "fatura", "Fatura", sorgu,
        "Aralıkta açılıp ödenen faturalar. Alış, sağlayıcının hesabımızdan düştüğü "
        "tutardır (fatura ve işlem bedeli). Yönetimin elle ödediğinde yalnızca fatura "
        "bedeli bilinir. Ödenmeyi bekleyen ve iade edilen ödemeler sayılmaz.",
        [("Kuruma göre", "Kurum", ("kurum_adi",))],
    )


def _esim_bolumu(bas, bit):
    """eSIM satış bölümünün biçiminde (`apps.esim.rapor`): teslimat ve yükleme birlikte."""
    from apps.esim.rapor import esim_gunlugu, esim_raporu

    esim = esim_raporu(bas, bit)
    return {
        "kod": "esim",
        "ad": "eSIM",
        "aciklama": "Aralıkta teslim edilen eSIM'ler ve yüklemeler. Sağlayıcıdan alışımız "
        "(sipariş günkü kurla), bayiye satışımız ve aradaki kâr. İade edilenler sayılmaz.",
        "toplam": {**esim["toplam"], "eksik": 0},
        "adet_eki": f"{esim['toplam']['yukleme_adedi']} yükleme",
        "kirilimlar": esim["kirilimlar"],
        "gunler": esim_gunlugu(bas, bit),
    }


def _genel(aktivasyon, bolumler):
    """Bölüm başına tek satır ve hepsinin toplamı. Satışta gelir satış, gider alıştır."""
    satirlar = [
        {"kod": "aktivasyon", "ad": "Aktivasyon", "eksik": 0,
         **{ad: aktivasyon[ad] for ad in ("adet", "gelir", "gider", "kar")}},
    ] + [
        {"kod": b["kod"], "ad": b["ad"], "adet": b["toplam"]["adet"], "gelir": b["toplam"]["satis"],
         "gider": b["toplam"]["alis"], "kar": b["toplam"]["kar"], "eksik": b["toplam"]["eksik"]}
        for b in bolumler
    ]
    toplam = {ad: sum((s[ad] for s in satirlar), SIFIR).quantize(SIFIR) for ad in ("gelir", "gider", "kar")}
    toplam |= {ad: sum(s[ad] for s in satirlar) for ad in ("adet", "eksik")}
    return {"satirlar": satirlar, "toplam": toplam}


def _gunluk_tablo(baslangic, bitis, kaynaklar):
    """Gün gün kâr, bölüm sütunlu. `kaynaklar`: [(bölüm adı, {gün: satır})].

    O gün işi olmayan bölümün hücresi boştur (`None`), sıfır değil.
    """
    satirlar = []
    gun = baslangic
    while gun <= bitis:
        karlar = [gunler[gun]["kar"] if gun in gunler else None for _, gunler in kaynaklar]
        satirlar.append({
            "gun": gun,
            "karlar": karlar,
            "kar": sum((k for k in karlar if k is not None), SIFIR).quantize(SIFIR),
            "bos": all(k is None for k in karlar),
        })
        gun += timedelta(days=1)
    return {"basliklar": [ad for ad, _ in kaynaklar], "satirlar": satirlar}


@staff_member_required
def karlilik(request):
    from apps.basvurular.models import Basvuru
    from apps.ozet import admin_baglami

    form, (baslangic, bitis) = _araligi_coz(request)
    bas, bit = _gun_baslangici(baslangic), _gun_baslangici(bitis) + timedelta(days=1)

    # Sonuçlanma tarihine göre: kâr ancak işlem sonuçlanınca kesinleşir.
    # Henüz sonuçlanmamış başvurunun parası da yarım işlenmiş olur.
    sorgu = Basvuru.objects.filter(sonuclanma_tarihi__gte=bas, sonuclanma_tarihi__lt=bit)

    ham = _toplamlar(sorgu)
    toplam = _satir(ham, adet=ham["adet"] or 0)
    aktivasyon_gunleri = {s["etiket"]: s for s in _gunluk(sorgu, baslangic, bitis) if s["adet"]}

    # Menüdeki sıra: kontör, fatura, oyun & pin, eSIM.
    kontor, oyun = _kontor_bolumleri(bas, bit)
    bolumler = [kontor, _fatura_bolumu(bas, bit), oyun, _esim_bolumu(bas, bit)]

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
            "genel": _genel(toplam, bolumler),
            # Aktivasyon: başvuruların beş para kalemi.
            "toplam": toplam,
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
                    "satirlar": _kirilim(
                        sorgu, "bayi_id", *etiket_sutunlari("bayi__"),
                        etiket=lambda ham: etiket_satirdan(ham, "bayi__"),
                    )[:10],
                },
            ],
            "bolumler": bolumler,
            "gunluk": _gunluk_tablo(
                baslangic, bitis,
                [("Aktivasyon", aktivasyon_gunleri)] + [(b["ad"], b["gunler"]) for b in bolumler],
            ),
            "basvuru_listesi": reverse("admin:basvurular_basvuru_changelist"),
        },
    )
