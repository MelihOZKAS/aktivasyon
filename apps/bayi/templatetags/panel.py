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
        "renk": okunur_renk(durum.renk),
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


def _hex_to_rgb(renk):
    renk = (renk or "").lstrip("#")
    if len(renk) == 3:
        renk = "".join(k * 2 for k in renk)
    if len(renk) != 6:
        return None
    try:
        return tuple(int(renk[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


@register.filter
def okunur_renk(renk):
    """Marka rengini açık zeminde okunur hale getirir.

    Turkcell sarısı gibi açık renkler kendi zemininde okunmaz. Renk fazla
    açıksa tonu koruyup parlaklığı düşürerek metin için güvenli bir
    karşılık üretir; koyu renkler olduğu gibi kalır.
    """
    rgb = _hex_to_rgb(renk)
    if rgb is None:
        return renk or "#0D1320"

    r, g, b = (k / 255 for k in rgb)

    # Göreli parlaklık (WCAG). Yeterince koyuysa dokunma.
    def kanal(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    parlaklik = 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b)
    if parlaklik <= 0.18:
        return renk

    # Tonu koru, parlaklığı güvenli aralığa çek.
    import colorsys

    h, l, s = colorsys.rgb_to_hls(r, g, b)
    yeni_r, yeni_g, yeni_b = colorsys.hls_to_rgb(h, min(l, 0.3), max(s, 0.55))
    return "#{:02x}{:02x}{:02x}".format(
        round(yeni_r * 255), round(yeni_g * 255), round(yeni_b * 255)
    )
