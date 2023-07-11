from django.shortcuts import render,redirect,HttpResponse
from .form import GecisNormal,GecisPass,KontorluYeniform,FaturaliYeniform,Sebekeiciform,internetform
from .models import Evrak,EvrakPass,TurkTarife,YabanciTarife,KontorluYeniHat,YeniTurkTarife,YeniYabanciTarife,FaturaliYeniHat,YeniFaturaliTurkTarife,YeniFaturaliYabanciTarife,Sebekeici,SebekeiciYabanciTarife,SebekeiciTurkTarife,internet,OperatorTarifeleri,Operatorleri,Modemlimi,Telefon,Duyuru
from django.contrib.auth.models import auth
from django.contrib.auth.decorators import login_required
import environ
import requests
from django.http import JsonResponse


env = environ.Env(DEBUG=(bool,False))
environ.Env.read_env()


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
    #selected_operator = request.GET.get('operator4')
    if request.method == 'POST':
        form = GecisNormal(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "MNT Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır


    else:
        form = GecisNormal()
        #form.fields['tarifeTurk'].queryset = TurkTarife.objects.filter(operator=selected_operator)
        #form.fields['tarifeYabanci'].queryset = YabanciTarife.objects.filter(operator=selected_operator)

    return render(request,"system/evrak-gir.html", {'form': form})




def get_tariffs(request):
    if request.GET.get('operator'):
        operator = request.GET.get('operator')
        tarifeTurk = list(YeniTurkTarife.objects.filter(operator=operator).values('id', 'ad'))
        tarifeYabanci = list(YeniYabanciTarife.objects.filter(operator=operator).values('id', 'ad'))
    elif request.GET.get('operator2'):
        operator = request.GET.get('operator2')
        tarifeTurk = list(YeniFaturaliTurkTarife.objects.filter(operator=operator).values('id', 'ad'))
        tarifeYabanci = list(YeniFaturaliYabanciTarife.objects.filter(operator=operator).values('id', 'ad'))
    elif request.GET.get('operator3'):
        operator = request.GET.get('operator3')
        tarifeTurk = list(SebekeiciTurkTarife.objects.filter(operator=operator).values('id', 'ad'))
        tarifeYabanci = list(SebekeiciYabanciTarife.objects.filter(operator=operator).values('id', 'ad'))
    elif request.GET.get('operator4'):
        operator = request.GET.get('operator4')
        tarifeTurk = list(TurkTarife.objects.filter(operator=operator).values('id', 'ad'))
        tarifeYabanci = list(YabanciTarife.objects.filter(operator=operator).values('id', 'ad'))

    return JsonResponse({'tarifeTurk': tarifeTurk, 'tarifeYabanci': tarifeYabanci})


@login_required(login_url = 'home')
def kontorluYeni(request):
    if request.method == 'POST':
        form = KontorluYeniform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "KontorlüYeni Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = KontorluYeniform()

    return render(request,"system/kontorlu-yeni-hat.html", {'form': form,})




@login_required(login_url = 'home')
def FaturaliYeni(request):
    if request.method == 'POST':
        form = FaturaliYeniform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "FaturaliYeni Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = FaturaliYeniform()

    return render(request,"system/faturali-yeni-hat.html", {'form': form})

@login_required(login_url = 'home')
def sebekeicigecis(request):
    if request.method == 'POST':
        form = Sebekeiciform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "Şebeke içi Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = Sebekeiciform()
    return render(request,"system/sebeke-ici-gecis.html",{'form': form})

@login_required(login_url = 'home')
def internet(request):
    if request.method == 'POST':
        form = internetform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "İnternet Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = internetform()

    return render(request,"system/internet.html", {'form': form})




@login_required(login_url = 'home')
def evrakpass(request):
    if request.method == 'POST':
        form = GecisPass(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            joined_message = "EvrakPass Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
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