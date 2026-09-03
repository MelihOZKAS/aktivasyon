"""Yüklenen görselleri küçültüp WebP'ye çevirir.

Telefon kameraları 4000×3000 çekiyor; kimlikteki yazıyı okumak için bu
gereksiz. Kimlik kartı kadrajın çoğunu kapladığından uzun kenar 1000px'e
indiğinde bile karttaki yazı ~18px kalıyor ve rahat okunuyor. Dosya yaklaşık
kırkta birine iniyor — hem disk hem de bayinin mobil verisi kazanıyor.

EXIF verisi de temizlenir: telefon fotoğrafları konum bilgisi taşır ve
bunun kimlik görüntüsünde işi yoktur. Silmeden önce EXIF'teki döndürme
bilgisi uygulanır, yoksa fotoğraf yan yatar.
"""

import logging
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

CEVRILEBILIR = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _ayar(ad, varsayilan):
    return getattr(settings, ad, varsayilan)


def gorseli_kucult(dosya):
    """Görseli küçültüp WebP'ye çevirir; çevrilemezse olduğu gibi döner.

    Dönüşüm başarısız olursa yükleme iptal edilmez: bayinin işi yarıda
    kalmasın diye özgün dosya kullanılır, hata günlüğe düşer.
    """
    if not dosya:
        return dosya

    uzanti = Path(dosya.name).suffix.lower()
    if uzanti not in CEVRILEBILIR:
        # PDF ve diğerleri olduğu gibi kalır.
        return dosya

    maks = _ayar("GORSEL_MAKS_KENAR", 1000)
    kalite = _ayar("GORSEL_WEBP_KALITE", 85)

    try:
        dosya.seek(0)
        with Image.open(dosya) as gorsel:
            # EXIF'teki döndürmeyi uygula, sonra veriyi at.
            gorsel = ImageOps.exif_transpose(gorsel)

            if gorsel.mode not in ("RGB", "RGBA"):
                gorsel = gorsel.convert("RGBA" if "A" in gorsel.mode else "RGB")
            if gorsel.mode == "RGBA":
                # WebP saydamlığı destekler ama kimlik görüntüsünde gereksiz;
                # beyaz zemine yerleştirip küçültüyoruz.
                zemin = Image.new("RGB", gorsel.size, (255, 255, 255))
                zemin.paste(gorsel, mask=gorsel.split()[-1])
                gorsel = zemin

            gorsel.thumbnail((maks, maks), Image.LANCZOS)

            tampon = BytesIO()
            gorsel.save(tampon, "WEBP", quality=kalite, method=6)
    except (UnidentifiedImageError, OSError, ValueError) as hata:
        logger.warning("Görsel dönüştürülemedi (%s): %s", dosya.name, hata)
        dosya.seek(0)
        return dosya

    boyut = tampon.tell()
    tampon.seek(0)
    yeni_ad = Path(dosya.name).with_suffix(".webp").name

    logger.info(
        "Görsel küçültüldü: %s → %s (%.0f KB → %.0f KB)",
        dosya.name, yeni_ad, dosya.size / 1024, boyut / 1024,
    )

    return InMemoryUploadedFile(
        tampon, None, yeni_ad, "image/webp", boyut, None
    )
