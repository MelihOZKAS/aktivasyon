from django.shortcuts import render,redirect
from .form import GecisNormal,GecisPass,KontorluYeniform,FaturaliYeniform,Sebekeiciform,internetform
from .models import Duyuru
from django.contrib.auth.models import auth
from django.contrib.auth.decorators import login_required

# Create your views here.
def home(request):
    if request.method == "POST":
        username = request.POST["numara"]
        password = request.POST["password"]
        print("Nasip1")

        user = auth.authenticate(username=username,password=password)
        if user is not None:
            print("Nasip2")
            auth.login(request,user)
            return redirect('panel')


    return render(request,"login/giris.html")



@login_required(login_url = 'home')
def basvuru(request):
    return render(request,"system/bayi.html")

@login_required(login_url = 'home')
def altYapi(request):
    return render(request,"system/alt-yapi.html")

@login_required(login_url = 'home')
def kontor(request):
    return render(request,"system/kontor.html")

@login_required(login_url = 'home')
def panel(request):
    duyurular = Duyuru.objects.all()

    return render(request,"system/panel.html", {'duyurular': duyurular})



@login_required(login_url = 'home')
def evrak(request):
    if request.method == 'POST':
        form = GecisNormal(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır


    else:
        form = GecisNormal()

    return render(request,"system/evrak-gir.html", {'form': form})



@login_required(login_url = 'home')
def kontorluYeni(request):
    if request.method == 'POST':
        form = KontorluYeniform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
    else:
        form = KontorluYeniform()

    return render(request,"system/kontorlu-yeni-hat.html", {'form': form})

@login_required(login_url = 'home')
def FaturaliYeni(request):
    if request.method == 'POST':
        form = FaturaliYeniform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
    else:
        form = FaturaliYeniform()

    return render(request,"system/faturali-yeni-hat.html", {'form': form})

@login_required(login_url = 'home')
def sebekeicigecis(request):
    if request.method == 'POST':
        form = Sebekeiciform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
    else:
        form = Sebekeiciform()

    return render(request,"system/sebeke-ici-gecis.html", {'form': form})

@login_required(login_url = 'home')
def internet(request):
    if request.method == 'POST':
        form = internetform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
    else:
        form = internetform()

    return render(request,"system/internet.html", {'form': form})




@login_required(login_url = 'home')
def evrakpass(request):
    if request.method == 'POST':
        form = GecisPass(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
    else:
        form = GecisPass()

    return render(request,"system/evrak-gir-pass.html", {'form': form})



@login_required(login_url = 'home')
def logout(request):
    auth.logout(request)
    return redirect("home")

@login_required(login_url = 'home')
def duyurular(request):
    duyurular = Duyuru.objects.all()
    return render(request, 'system/panel.html', {'duyurular': duyurular})