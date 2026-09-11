from django import template

from apps.esim.models import hacim_metni

register = template.Library()


@register.filter
def hacim(bayt):
    return hacim_metni(bayt)


@register.filter
def lira(deger):
    """Tam lira, binlik ayraçlı: 1250 → 1.250. eSIM fiyatları kuruşsuzdur."""
    if deger is None:
        return "—"
    try:
        sayi = int(deger)
    except (TypeError, ValueError):
        return deger
    return f"{sayi:,}".replace(",", ".")
