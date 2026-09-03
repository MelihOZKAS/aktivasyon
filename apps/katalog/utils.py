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


def kucult(alan):
    """Yeni yüklenen görseli küçültüp WebP'ye çevirir.

    Yalnızca bu kaydetmede yüklenmiş dosyalarda çalışır; daha önce
    kaydedilmiş bir görsel her kaydetmede yeniden işlenmez.
    """
    from apps.basvurular.gorsel import gorseli_kucult

    if not alan:
        return alan
    # Zaten diske yazılmış dosyanın _file'ı yoktur; yalnızca taze yüklemeler
    # InMemoryUploadedFile / TemporaryUploadedFile taşır.
    dosya = getattr(alan, "file", None)
    if dosya is None or not hasattr(dosya, "content_type"):
        return alan
    return gorseli_kucult(dosya)
