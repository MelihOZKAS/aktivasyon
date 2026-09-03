"""Bayi panelinde kullanılan şablon yardımcıları."""

from django import template

register = template.Library()


@register.inclusion_tag("parcalar/sinyal.html")
def sinyal(durum):
    """Başvuru durumunu 5 çubuklu sinyal göstergesi olarak çizer."""
    seviye = getattr(durum, "sinyal_seviyesi", 1)
    return {
        "cubuklar": range(1, 6),
        "seviye": seviye,
        "renk": durum.renk,
        "kirik": durum.olumsuz_sonuc,
        "ad": durum.ad,
    }


@register.filter
def para(deger):
    """Tutarı Türkçe biçimde yazar: 12450.5 -> 12.450,50"""
    if deger is None:
        return "—"
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return deger
    tam, _, kusurat = f"{abs(sayi):,.2f}".partition(".")
    tam = tam.replace(",", ".")
    isaret = "-" if sayi < 0 else ""
    return f"{isaret}{tam},{kusurat}"
