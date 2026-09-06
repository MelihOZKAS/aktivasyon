"""Şablonlara bayi bağlamını taşır.

Borç limiti ve kullanılabilir tutar bilinçli olarak dışarıda bırakılmıştır:
bakiyeden farkları limiti ele verir. Bu değerler yalnızca sunucu tarafı
kontrolünde ve yönetim ekranlarında kullanılır.
"""

from apps.finans.models import Cuzdan


def bayi_baglami(request):
    kullanici = getattr(request, "user", None)
    if not kullanici or not kullanici.is_authenticated:
        return {}

    from apps.bayi.yetki import bayi_mi, tedarikci_mi

    return {
        "cuzdan": Cuzdan.objects.filter(bayi=kullanici).select_related("grup").first(),
        "bayi_mi": bayi_mi(kullanici),
        "tedarikci_mi": tedarikci_mi(kullanici),
    }


def genel_ayarlar(request):
    """İletişim bilgilerini kamuya açık sayfalara taşır.

    Giriş ekranı ve tanıtım sayfası oturum açmamış ziyaretçiye de görünür;
    bu yüzden `bayi_baglami`'ndan ayrı durur — o, girişi olmayan kullanıcıya
    boş dönüyor.

    Kayıt yoksa `None` döner ve şablonlar iletişim kutusunu hiç çizmez;
    burada kayıt açılmaz, her istekte yazma yapmanın gereği yok.
    """
    from apps.bayi.models import GenelAyarlar

    return {"genel_ayarlar": GenelAyarlar.objects.filter(pk=GenelAyarlar.TEKIL_PK).first()}
