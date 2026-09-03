"""Şablonlara bayi bağlamını (cüzdan, bekleyen başvuru sayısı) taşır."""

from apps.finans.models import Cuzdan


def bayi_baglami(request):
    kullanici = getattr(request, "user", None)
    if not kullanici or not kullanici.is_authenticated:
        return {}

    cuzdan = Cuzdan.objects.filter(bayi=kullanici).select_related("grup").first()
    return {
        "cuzdan": cuzdan,
        "kullanilabilir_tutar": cuzdan.kullanilabilir_tutar if cuzdan else None,
    }
