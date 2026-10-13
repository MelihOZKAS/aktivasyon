"""Bayinin kontör, oyun-pin ve fatura kazancı: günlük döküm ve dönem toplamı.

Kazanç müşteriden alınan ile bayinin ödediğinin farkıdır. Müşteriden ne
alındığını sistem bilmez; **tavsiye fiyatla** hesaplanır — dekontta yazan
rakamın aynısı (`apps/bayi/dekont.py`): kontörde `Islem.tavsiye_fiyati`,
faturada `Odeme.tavsiye_fiyati`. Tavsiyesi olmayan satışta kazanç 0'dır.
eSIM'deki kuralın aynısı: bu bizim ödediğimiz bir hakediş değildir, cüzdana
girmez.

Yalnızca sonuçlanmış işler sayılır: yüklenen kontör, ödenen fatura. Gün,
satışın yapıldığı gündür (`olusturma_tarihi`; bayinin tezgâhtaki günü).

Aralık **en fazla 31 gün**: sayfa her açılışta bayinin işlemlerini toplar;
indeksli (`bayi`, `-olusturma_tarihi`) olsa da yıllık aralık sunucuyu boşuna
yorar. Rakamlar saklanmaz, her seferinde kayıtlardan hesaplanır.
"""

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Sum, When
from django.db.models.functions import TruncDate
from django.utils import timezone

SIFIR = Decimal("0.00")
EN_UZUN_ARALIK = 31

# Bölümler ekrandaki sırayla; menüdeki sırayla aynı.
BOLUMLER = OrderedDict([("kontor", "Kontör"), ("oyun", "Oyun & Pin"), ("fatura", "Fatura")])


class AralikHatasi(ValueError):
    pass


def hazir_araliklar(bugun=None):
    """Tek dokunuşla seçilen aralıklar: (kod, ad, başlangıç, bitiş)."""
    bugun = bugun or timezone.localdate()
    ay_basi = bugun.replace(day=1)
    gecen_ay_sonu = ay_basi - timedelta(days=1)
    return [
        ("bugun", "Bugün", bugun, bugun),
        ("dun", "Dün", bugun - timedelta(days=1), bugun - timedelta(days=1)),
        ("7gun", "Son 7 gün", bugun - timedelta(days=6), bugun),
        ("buay", "Bu ay", ay_basi, bugun),
        ("gecenay", "Geçen ay", gecen_ay_sonu.replace(day=1), gecen_ay_sonu),
    ]


def araligi_coz(baslangic, bitis, bugun=None):
    """Metin tarihleri (`2026-10-01`) aralığa çevirir; geçersizse `AralikHatasi`.

    Boşsa bu ay. Bitiş günü dahildir.
    """
    bugun = bugun or timezone.localdate()
    if not baslangic and not bitis:
        return bugun.replace(day=1), bugun
    try:
        bas = date.fromisoformat(baslangic or bitis)
        bit = date.fromisoformat(bitis or baslangic)
    except ValueError:
        raise AralikHatasi("Tarih anlaşılamadı.")
    if bit < bas:
        raise AralikHatasi("Bitiş tarihi başlangıçtan önce olamaz.")
    gun = (bit - bas).days + 1
    if gun > EN_UZUN_ARALIK:
        raise AralikHatasi(f"Aralık en fazla {EN_UZUN_ARALIK} gün olabilir, sen {gun} gün seçtin.")
    return bas, bit


def _an(gun):
    return timezone.make_aware(datetime.combine(gun, time.min))


def _musteri_fiyati(tavsiye):
    """Tavsiye varsa o, yoksa bayinin ödediği (kazanç 0) — dekontun rakamı."""
    return Case(
        When(**{f"{tavsiye}__gt": 0}, then=F(tavsiye)),
        default=F("siparis__tutar"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _bos():
    return {"adet": 0, "satis": SIFIR, "maliyet": SIFIR, "kazanc": SIFIR}


def _ekle(hedef, satir):
    hedef["adet"] += satir["adet"]
    hedef["satis"] += satir["satis"] or SIFIR
    hedef["maliyet"] += satir["maliyet"] or SIFIR
    hedef["kazanc"] = (hedef["satis"] - hedef["maliyet"]).quantize(SIFIR)


def kazanc(bayi, baslangic, bitis):
    """Aralığın kazancı: `{"toplam", "bolumler", "gunler"}`.

    `bolumler`: bölüm → toplam (yalnızca satışı olan bölümler).
    `gunler`: en yeni gün önce, yalnızca satış olan günler; her günde
    bölüm → satır ve günün toplamı.
    """
    from apps.fatura.models import Odeme, OdemeDurumu
    from apps.kontor.models import Islem, IslemDurumu

    aralik = {"olusturma_tarihi__gte": _an(baslangic), "olusturma_tarihi__lt": _an(bitis + timedelta(days=1))}
    toplamlar = {"adet": Count("id"), "maliyet": Sum("siparis__tutar")}

    satirlar = []
    for ham in (
        Islem.objects.filter(bayi=bayi, durum=IslemDurumu.BASARILI, **aralik)
        .annotate(gun=TruncDate("olusturma_tarihi"))
        .values("gun", "kategori__oyun")
        .annotate(satis=Sum(_musteri_fiyati("tavsiye_fiyati")), **toplamlar)
        .order_by()
    ):
        satirlar.append(("oyun" if ham["kategori__oyun"] else "kontor", ham))
    for ham in (
        Odeme.objects.filter(bayi=bayi, durum=OdemeDurumu.ODENDI, **aralik)
        .annotate(gun=TruncDate("olusturma_tarihi"))
        .values("gun")
        .annotate(satis=Sum(_musteri_fiyati("tavsiye_fiyati")), **toplamlar)
        .order_by()
    ):
        satirlar.append(("fatura", ham))

    toplam, bolumler, gunler = _bos(), {}, {}
    for bolum, ham in satirlar:
        _ekle(toplam, ham)
        _ekle(bolumler.setdefault(bolum, _bos()), ham)
        gun = gunler.setdefault(ham["gun"], {"gun": ham["gun"], "toplam": _bos(), "bolumler": {}})
        _ekle(gun["toplam"], ham)
        _ekle(gun["bolumler"].setdefault(bolum, _bos()), ham)

    return {
        "toplam": toplam,
        "bolumler": [(kod, ad, bolumler[kod]) for kod, ad in BOLUMLER.items() if kod in bolumler],
        "gunler": [
            {**g, "satirlar": [g["bolumler"].get(kod) for kod in BOLUMLER if kod in bolumler]}
            for _, g in sorted(gunler.items(), reverse=True)
        ],
    }
