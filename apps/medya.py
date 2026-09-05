"""Bayiye gösterilen görselleri üretimde de sunar.

Tarife, kampanya ve operatör görselleri admin'den yüklenir ve diske yazılır.
Django'nun `static()` yardımcısı yalnızca DEBUG açıkken URL üretir, WhiteNoise
ise açılışta taradığı `STATIC_ROOT`'u sunar — sonradan yüklenen bir görsel
ikisine de girmez. Yerelde görünüp üretimde 404 veren fark buradan geliyordu;
bu yüzden açık görseller DEBUG'dan bağımsız olarak buradan sunulur.

Kimlik ve pasaport görüntüleri (`basvuru/`, eski sistemin `evrak/` klasörü)
bu yoldan **sunulmaz**. Onlar kişisel veridir ve yalnızca izin kontrolünden
geçen `apps.basvurular.views.belge` görünümünden gelir. Yeni bir açık görsel
alanı eklersen klasörünü `ACIK_KLASORLER`'e yaz; kişisel veri taşıyan bir alan
eklersen buraya **yazma**, belge görünümünü örnek al.
"""

import posixpath
import re

from django.conf import settings
from django.http import Http404
from django.urls import re_path
from django.views.static import serve

# Yalnızca herkese açık içerik. Sıra önemsiz, ad `upload_to` ile aynı olmalı.
ACIK_KLASORLER = ("operator", "tarife")

# Görseller değişince dosya adı da değişiyor (yeni yükleme yeni ad alır),
# bu yüzden bir gün önbellek güvenli.
ONBELLEK = "public, max-age=86400"


def acik_gorsel(request, yol):
    """`MEDIA_ROOT` altındaki açık klasörlerden bir dosya sunar."""
    # URL deseni normalleştirmeden önce eşleşiyor: "tarife/../basvuru/kimlik.webp"
    # desene uyar ama kişisel veriye çıkar. İlk klasör normalleştirmeden sonra
    # yeniden denetlenir; kalan yol güvenliğini `serve` (safe_join) üstlenir.
    temiz = posixpath.normpath(yol).lstrip("/")
    if temiz.split("/", 1)[0] not in ACIK_KLASORLER:
        raise Http404("Bu klasör dışarıya açık değil.")

    yanit = serve(request, temiz, document_root=settings.MEDIA_ROOT)
    yanit["Cache-Control"] = ONBELLEK
    yanit["X-Content-Type-Options"] = "nosniff"
    return yanit


def acik_gorsel_yollari():
    """`config.urls` bunu koşulsuz ekler; DEBUG'a bakmaz."""
    klasorler = "|".join(ACIK_KLASORLER)
    onek = re.escape(settings.MEDIA_URL.lstrip("/"))
    return [
        re_path(
            rf"^{onek}(?P<yol>(?:{klasorler})/.+)$", acik_gorsel, name="acik-gorsel"
        )
    ]
