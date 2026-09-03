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

    return {"cuzdan": Cuzdan.objects.filter(bayi=kullanici).select_related("grup").first()}
