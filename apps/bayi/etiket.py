"""Kullanıcının ekranda görünen adı.

Kullanıcı adı telefon numarasıdır (`5304517888`); numara tek başına kimin
olduğunu anlatmıyor. Yönetici listede, seçim kutusunda ve süzgeçte adı
görmek istiyor. Görünen ad **tek yerden** gelir: `User.__str__` de buradan
geçer (`apps.bayi.apps`), admin sütunları da, raporlar da.

Ad sırası:

1. Hesabın kendi adı-soyadı (`first_name` / `last_name`). Bayi
   başvurusundan açılan her hesapta doludur ve kullanıcı satırının
   üstündedir — seçim kutusu yüz kullanıcıyı çizerken ek sorgu atılmaz.
2. Bayi profilindeki firma ünvanı. Elle açılmış tedarikçi hesabında
   yalnızca o dolu olabilir.
3. Hiçbiri yoksa etiket numaradan ibaret kalır.
"""

from django.utils.html import format_html

AYRAC = " · "


def _birlestir(ad, numara):
    return f"{ad}{AYRAC}{numara}" if ad else numara


def gorunen_ad(kullanici):
    """Yalnızca ad; yoksa boş metin."""
    ad = kullanici.get_full_name().strip()
    if ad:
        return ad
    profil = getattr(kullanici, "bayi_profili", None)
    return (profil.unvan or "").strip() if profil else ""


def kisa_ad(kullanici):
    """Yalnızca ad; yoksa numara. Operatör adının yanında duran yerler için
    ("Alışım: Turkcell 1000 · Ege Tedarik 950") — numara orada gürültü."""
    return gorunen_ad(kullanici) or kullanici.get_username()


def kullanici_etiketi(kullanici):
    """Düz metin: ``Fadil Yiğitdöl · 5304517888`` ya da yalnızca numara."""
    return _birlestir(gorunen_ad(kullanici), kullanici.get_username())


def kullanici_etiketi_html(kullanici):
    """Liste sütunu: ad üstte kalın, numara altında küçük ve gri."""
    ad = gorunen_ad(kullanici)
    numara = kullanici.get_username()
    if not ad:
        return numara
    return format_html(
        '<span style="font-weight:600">{}</span><br>'
        '<span style="color:#6F7B8F;font-size:.75rem">{}</span>',
        ad,
        numara,
    )


# `.values()` ile okuyan raporlar için: etiketin ihtiyaç duyduğu sütunlar,
# kullanıcı FK'sinden itibaren. Sıra `ad_satirdan` ile eşleşir.
_SUTUNLAR = ("username", "first_name", "last_name", "bayi_profili__unvan")


def etiket_sutunlari(onek):
    """`sorgu.values(*etiket_sutunlari("bayi__"))` — raporun çekeceği sütunlar."""
    return tuple(onek + sutun for sutun in _SUTUNLAR)


def ad_satirdan(ham, onek):
    """`.values()` satırından yalnızca ad; yoksa boş. Öncelik `gorunen_ad` ile aynı."""
    _, first_name, last_name, unvan = (ham[onek + sutun] for sutun in _SUTUNLAR)
    return f"{first_name or ''} {last_name or ''}".strip() or (unvan or "").strip()


def kisa_ad_satirdan(ham, onek):
    """`kisa_ad`ın `.values()` karşılığı."""
    return ad_satirdan(ham, onek) or ham[onek + "username"]


def etiket_satirdan(ham, onek):
    """`.values()` satırından ``Ad Soyad · numara``; kaynak nesne yoksa bu kullanılır."""
    return _birlestir(ad_satirdan(ham, onek), ham[onek + "username"])
