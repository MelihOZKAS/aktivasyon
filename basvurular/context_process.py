from .models import Bayi_Listesi
from django.shortcuts import render,redirect,HttpResponse


def get_User_Cash(request):
    if request.user.is_authenticated:
        try:
            bayi = Bayi_Listesi.objects.get(user=request.user)
        except:
            return redirect('home')

        return dict(bayi=bayi)
    else:
        return {}
