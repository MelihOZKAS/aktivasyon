"""Yüklenen belgeler için doğrulama.

Bayi tarafından yüklenen dosyalar personel tarafından açılır. Tarayıcıda
çalışabilen bir dosya (HTML, SVG) yüklenirse, açan personelin oturumunda
betik çalışır. Bu yüzden hem uzantı hem de dosyanın gerçek içeriği
denetlenir; `accept` HTML özniteliği yalnızca tarayıcı ipucudur, sunucuda
bağlayıcı değildir.
"""

from django.core.exceptions import ValidationError

# Uzantı -> dosyanın başlaması gereken imzalar
IZINLI_TURLER = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".webp": [b"RIFF"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".pdf": [b"%PDF-"],
}

# Yalnızca bunlar tarayıcıda gömülü gösterilebilir; gerisi indirilir.
SATIR_ICI_GOSTERILEBILIR = {"image/png", "image/jpeg", "image/webp", "image/gif"}

AZAMI_BOYUT = 10 * 1024 * 1024


def belge_dogrula(dosya):
    """Dosyanın uzantısını, boyutunu ve gerçek içeriğini denetler."""
    from pathlib import Path

    uzanti = Path(dosya.name).suffix.lower()
    if uzanti not in IZINLI_TURLER:
        izinli = ", ".join(sorted(IZINLI_TURLER))
        raise ValidationError(
            f"Bu dosya türü kabul edilmiyor. İzin verilenler: {izinli}"
        )

    if dosya.size > AZAMI_BOYUT:
        raise ValidationError("Dosya 10 MB'tan büyük olamaz.")

    # Uzantı kolayca değiştirilebilir; içeriğin gerçekten o tür olduğunu doğrula.
    konum = dosya.tell()
    dosya.seek(0)
    bas = dosya.read(8)
    dosya.seek(konum)

    if not any(bas.startswith(imza) for imza in IZINLI_TURLER[uzanti]):
        raise ValidationError(
            f"Dosyanın içeriği {uzanti} biçimiyle uyuşmuyor. "
            "Uzantısı değiştirilmiş bir dosya yüklemeye çalışıyor olabilirsiniz."
        )
