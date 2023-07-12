from .models import Bayi_Listesi


def get_User_Cash(request):
    if request.user.is_authenticated:
        bayi = Bayi_Listesi.objects.get(user=request.user)
        return dict(bayi=bayi)
    else:
        return {}
