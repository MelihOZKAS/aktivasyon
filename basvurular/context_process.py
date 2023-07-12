from .models import Bayi_Listesi

def get_User_Cash(request):
    bayi = Bayi_Listesi.objects.get(user=request.user)
    return dict(bayi=bayi)