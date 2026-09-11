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


@register.filter
def qr(ac, olcek=3):
    """Aktivasyon kodundan QR (SVG data URI). Listede küçük, teslim sayfasında büyük."""
    if not ac:
        return ""
    import segno

    return segno.make(ac, error="m").svg_data_uri(scale=int(olcek), border=1, dark="#111")
