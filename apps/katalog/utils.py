"""Yardımcılar."""

from django.utils.text import slugify

# Django'nun slugify'ı ASCII dışı harfleri düşürür: "Faturalı" -> "fatural",
# "Taşıma" -> "tasma". Türkçe harfleri önce karşılıklarına çeviriyoruz.
TURKCE_HARFLER = str.maketrans(
    {
        "ı": "i", "İ": "i", "I": "i",
        "ş": "s", "Ş": "s",
        "ğ": "g", "Ğ": "g",
        "ç": "c", "Ç": "c",
        "ö": "o", "Ö": "o",
        "ü": "u", "Ü": "u",
        "â": "a", "Â": "a",
        "î": "i", "Î": "i",
        "û": "u", "Û": "u",
    }
)


def turkce_slug(metin):
    """Türkçe metinden okunabilir, ASCII bir slug üretir.

    >>> turkce_slug("Faturalı Yeni Hat")
    'faturali-yeni-hat'
    >>> turkce_slug("MNT / Numara Taşıma")
    'mnt-numara-tasima'
    """
    return slugify(str(metin).translate(TURKCE_HARFLER))
