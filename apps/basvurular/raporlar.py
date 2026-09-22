"""Operasyon raporları."""

from django.db.models import Count, Q

from apps.bayi.etiket import etiket_sutunlari, kisa_ad_satirdan


def sim_alacaklari(sorgu=None):
    """Kimden kaç SIM kart alacağımızı çıkarır.

    İşlemi bir tedarikçi üstlendiyse alacak ondan, üstlenilmemişse
    doğrudan operatördendir. İki grup ayrı sayılıp birleştirilir.
    """
    from apps.basvurular.models import Basvuru

    if sorgu is None:
        sorgu = Basvuru.objects.all()

    bekleyen = sorgu.filter(
        kategori__sim_karsiligi_gerekir=True,
        durum__hakedis_tetikler=True,
        sim_karsiligi_alindi=False,
    )

    satirlar = []

    # Tedarikçiye satılmış işlemler: alacak tedarikçiden.
    for kayit in (
        bekleyen.filter(tedarikci__isnull=False)
        .values("tedarikci_id", *etiket_sutunlari("tedarikci__"))
        .annotate(adet=Count("id"))
        .order_by("-adet")
    ):
        satirlar.append(
            {
                "ad": kisa_ad_satirdan(kayit, "tedarikci__"),
                "tur": "Tedarikçi",
                "adet": kayit["adet"],
                "filtre": f"tedarikci__id__exact={kayit['tedarikci_id']}",
            }
        )

    # Tedarikçisiz işlemler: alacak operatörden.
    for kayit in (
        bekleyen.filter(tedarikci__isnull=True, operator__isnull=False)
        .values("operator_id", "operator__ad", "operator__renk")
        .annotate(adet=Count("id"))
        .order_by("-adet")
    ):
        satirlar.append(
            {
                "ad": kayit["operator__ad"],
                "tur": "Operatör",
                "renk": kayit["operator__renk"],
                "adet": kayit["adet"],
                "filtre": f"operator__id__exact={kayit['operator_id']}",
            }
        )

    satirlar.sort(key=lambda s: -s["adet"])
    return {"satirlar": satirlar, "toplam": sum(s["adet"] for s in satirlar)}
