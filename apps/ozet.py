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
            "ad": kayit["bayi__bayi_profili__unvan"] or kayit["bayi__username"],
            "numara": kayit["bayi__username"],
            "adet": kayit["adet"],
            "adres": f"{liste}?bayi__id__exact={kayit['bayi_id']}"
                     f"&durum__exact={SimKartDurumu.ATANDI}",
        }
        for kayit in (
            SimKart.objects.filter(durum=SimKartDurumu.ATANDI, bayi__isnull=False)
            .values("bayi_id", "bayi__username", "bayi__bayi_profili__unvan")
            .annotate(adet=Count("id"))
            .order_by("-adet")
        )
    ]


def _tedarikci_borclari():
    """Tedarikçilerin bize borcu: üstlendikleri işlemin bedeli.

    Tedarikçiden alış, işlem aktifleşince onun cüzdanından düşer. Bakiyesi
    yetmezse borca yazılır — bu borç bizim ondan alacağımızdır.
    """
    from apps.finans.models import Cuzdan

    liste = reverse("admin:finans_cuzdan_changelist")
    satirlar = [
        {
            "ad": cuzdan.bayi.bayi_profili.unvan
            if getattr(cuzdan.bayi, "bayi_profili", None)
            and cuzdan.bayi.bayi_profili.unvan
            else cuzdan.bayi.get_username(),
            "numara": cuzdan.bayi.get_username(),
            "borc": cuzdan.borc,
            "adres": f"{liste}{cuzdan.pk}/change/",
        }
        for cuzdan in (
            Cuzdan.objects.filter(borc__gt=SIFIR, bayi__bayi_profili__tedarikci_mi=True)
            .select_related("bayi__bayi_profili")
            .order_by("-borc")
        )
    ]
    return {"satirlar": satirlar, "toplam": sum(s["borc"] for s in satirlar)}


def _ana_hakedis_ozeti():
    """İşlenen ana hakediş, kaynağına göre.

    Operatörün cüzdanı olmadığı için oradan gelen tutar yalnızca başvuruya
    işlenir; tahsil edilip edilmediği sistemde izlenmez. Tedarikçiden gelen
    ise cüzdandan düşer, karşılığı yukarıdaki borç tablosundadır.
    """
    from apps.basvurular.models import Basvuru

    islenen = Basvuru.objects.filter(ana_hakedis_islendi=True)

    def toplam(sorgu):
        # Toplam kuruşsuz dönebiliyor (400 gibi); para her yerde iki hanesiyle
        # görünmeli, yoksa listede rakamlar hizasız kalıyor.
        return (sorgu.aggregate(t=Sum("ana_hakedis"))["t"] or SIFIR).quantize(SIFIR)

    return {
        "operatorden": toplam(islenen.filter(tedarikci__isnull=True)),
        "tedarikciden": toplam(islenen.filter(tedarikci__isnull=False)),
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
            "tedarikci_borclari": _tedarikci_borclari(),
            "ana_hakedis": _ana_hakedis_ozeti(),
            "basvuru_listesi": reverse("admin:basvurular_basvuru_changelist"),
        },
    )


def admin_baglami(request):
    """Yan menü ve başlık için admin'in kendi bağlamı."""
    from django.contrib import admin

    return admin.site.each_context(request)
