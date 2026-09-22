"""Stok ve alacak özeti: tek ekranda "nerede ne var".

SIM kartlar, kimden kaç kart beklendiği ve tedarikçilerin bize borcu ayrı
ayrı listelerde duruyordu; yönetici üçünü ayrı ekranda açıp kafasında
toplamak zorundaydı. Bu sayfa hepsini bir yere getirir ve her satır
kendi filtreli listesine gider — sayı görünsün, ayrıntı bir tık ötede olsun.

Rakamlar hesaplanır, saklanmaz: kaynak yine başvurular, SIM kartlar ve
cüzdanlardır. Burada ikinci bir doğruluk kaynağı yaratılmaz.
"""

from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.urls import reverse

from apps.bayi.etiket import etiket_sutunlari, kisa_ad, kisa_ad_satirdan

SIFIR = Decimal("0.00")


def _sim_durumlari():
    """SIM stoğunun durum dağılımı."""
    from apps.bayi.models import SimKart, SimKartDurumu

    sayilar = dict(
        SimKart.objects.values_list("durum").annotate(adet=Count("id")).values_list(
            "durum", "adet"
        )
    )
    return [
        {
            "etiket": etiket,
            "adet": sayilar.get(deger, 0),
            "adres": f"{reverse('admin:bayi_simkart_changelist')}?durum__exact={deger}",
        }
        for deger, etiket in SimKartDurumu.choices
    ]


def _bayideki_kartlar():
    """Hangi bayide kaç kart zimmetli duruyor?"""
    from apps.bayi.models import SimKart, SimKartDurumu

    liste = reverse("admin:bayi_simkart_changelist")
    return [
        {
            "ad": kisa_ad_satirdan(kayit, "bayi__"),
            "numara": kayit["bayi__username"],
            "adet": kayit["adet"],
            "adres": f"{liste}?bayi__id__exact={kayit['bayi_id']}"
                     f"&durum__exact={SimKartDurumu.ATANDI}",
        }
        for kayit in (
            SimKart.objects.filter(durum=SimKartDurumu.ATANDI, bayi__isnull=False)
            .values("bayi_id", *etiket_sutunlari("bayi__"))
            .annotate(adet=Count("id"))
            .order_by("-adet")
        )
    ]


def _tedarikci_borclari():
    """Tedarikçilere borcumuz: üstlendikleri işlemlerin alış bedeli.

    Aktivasyonu tedarikçi yapıyor, biz ondan satın alıyoruz: işlem
    aktifleşince tutar onun cüzdanına yazılır. Cüzdanında biriken bakiye
    bizim ona ödeyeceğimiz paradır. (Yön bir süre tersti; tutar tedarikçinin
    hesabından düşülüyordu.)
    """
    from apps.finans.models import Cuzdan

    liste = reverse("admin:finans_cuzdan_changelist")
    satirlar = [
        {
            "ad": kisa_ad(cuzdan.bayi),
            "numara": cuzdan.bayi.get_username(),
            "borc": cuzdan.bakiye,
            "adres": f"{liste}{cuzdan.pk}/change/",
        }
        for cuzdan in (
            Cuzdan.objects.filter(
                bakiye__gt=SIFIR, bayi__bayi_profili__tedarikci_mi=True
            )
            .select_related("bayi__bayi_profili")
            .order_by("-bakiye")
        )
    ]
    return {"satirlar": satirlar, "toplam": sum(s["borc"] for s in satirlar)}


def _arizali_kartlar():
    """Bozuk kartların açık işleri.

    Kart için para hareketi yok, takas var: bayiden bozuğu alırız, yerine
    stoktan kart veririz, operatöre bozuğu verip yenisini alırız. Üç iş
    birbirinden bağımsızdır; burada her biri kendi süzgecine gider
    (`ArizaFiltresi`). Kapanmış kartlar sayılmaz.
    """
    from django.db.models import Q

    from apps.bayi.models import SimKart, SimKartDurumu

    liste = reverse("admin:bayi_simkart_changelist")
    arizali = SimKart.objects.filter(durum=SimKartDurumu.ARIZALI)
    bayide = Q(bayi__isnull=False, iade_alinma_tarihi__isnull=True)
    operatorden = Q(degisim_tarihi__isnull=True)

    operatorler = [
        {
            "ad": kayit["operator__ad"] or "Operatörsüz",
            "bayide": kayit["bayide"],
            "operatorden": kayit["operatorden"],
            "adres_bayide": f"{liste}?ariza=bayide&operator__id__exact={kayit['operator_id']}",
            "adres_operatorden": f"{liste}?ariza=operator&operator__id__exact={kayit['operator_id']}",
        }
        for kayit in (
            arizali.values("operator_id", "operator__ad")
            .annotate(
                bayide=Count("id", filter=bayide),
                operatorden=Count("id", filter=operatorden),
            )
            .order_by("operator__ad")
        )
        if kayit["bayide"] or kayit["operatorden"]
    ]
    bayiler = [
        {
            "ad": kisa_ad_satirdan(kayit, "bayi__"),
            "numara": kayit["bayi__username"],
            "adet": kayit["adet"],
            "adres": f"{liste}?ariza=yerine&bayi__id__exact={kayit['bayi_id']}",
        }
        for kayit in (
            arizali.filter(bayi__isnull=False, yerine_verilen__isnull=True)
            .values("bayi_id", *etiket_sutunlari("bayi__"))
            .annotate(adet=Count("id"))
            .order_by("-adet")
        )
    ]
    return {
        "operatorler": operatorler,
        "bayiler": bayiler,
        "acik": arizali.filter(bayide | Q(bayi__isnull=False, yerine_verilen__isnull=True) | operatorden).count(),
        "adres_acik": f"{liste}?ariza=acik",
    }


def _alis_ozeti():
    """Karşı tarafla olan hesap: ödediğimiz maliyet ve aldığımız prim.

    Operatörün cüzdanı olmadığı için oraya ödenen ya da oradan gelen tutar
    yalnızca başvuruya işlenir; sistemde bir borç kaydı doğurmaz.
    Tedarikçiye ödenen maliyet onun cüzdanına yazılır (karşılığı yukarıdaki
    tablodadır), ondan alınan prim ise cüzdanından düşer.
    """
    from apps.basvurular.models import Basvuru

    def toplam(sorgu, alan):
        # Toplam kuruşsuz dönebiliyor (400 gibi); para her yerde iki hanesiyle
        # görünmeli, yoksa listede rakamlar hizasız kalıyor.
        return (sorgu.aggregate(t=Sum(alan))["t"] or SIFIR).quantize(SIFIR)

    alis = Basvuru.objects.filter(alis_bedeli_islendi=True)
    prim = Basvuru.objects.filter(alinan_prim_islendi=True)

    return {
        "operatorden": toplam(alis.filter(tedarikci__isnull=True), "alis_bedeli"),
        "tedarikciden": toplam(alis.filter(tedarikci__isnull=False), "alis_bedeli"),
        "prim_operatorden": toplam(
            prim.filter(tedarikci__isnull=True), "alinan_prim"
        ),
        "prim_tedarikciden": toplam(
            prim.filter(tedarikci__isnull=False), "alinan_prim"
        ),
    }


@staff_member_required
def stok_ve_alacak(request):
    from apps.basvurular.raporlar import sim_alacaklari

    return render(
        request,
        "admin/ozet.html",
        {
            **admin_baglami(request),
            "title": "Stok ve Alacak Özeti",
            "sim_durumlari": _sim_durumlari(),
            "bayideki_kartlar": _bayideki_kartlar(),
            "sim_alacaklari": sim_alacaklari(),
            "arizali_kartlar": _arizali_kartlar(),
            "tedarikci_borclari": _tedarikci_borclari(),
            "alis_bedeli": _alis_ozeti(),
            "basvuru_listesi": reverse("admin:basvurular_basvuru_changelist"),
        },
    )


def admin_baglami(request):
    """Yan menü ve başlık için admin'in kendi bağlamı."""
    from django.contrib import admin

    return admin.site.each_context(request)
