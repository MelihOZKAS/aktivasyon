from django.shortcuts import render,redirect,HttpResponse
from .form import GecisNormal,GecisPass,KontorluYeniform,FaturaliYeniform,Sebekeiciform,internetform
from .models import Evrak,EvrakPass,TurkTarife,YabanciTarife,KontorluYeniHat,YeniTurkTarife,YeniYabanciTarife,FaturaliYeniHat,YeniFaturaliTurkTarife,YeniFaturaliYabanciTarife,Sebekeici,SebekeiciYabanciTarife,SebekeiciTurkTarife,internet,OperatorTarifeleri,Operatorleri,Modemlimi,Telefon,Duyuru,Urun,Bayi_Listesi,BakiyeHareketleri,Banka
from django.contrib.auth.models import auth
from django.contrib.auth.decorators import login_required
import environ
import requests
from django.http import JsonResponse
from django.shortcuts import render
from .models import SimCard, Bayi_Listesi


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
    bayi = Bayi_Listesi.objects.get(user=request.user)

    return render(request,"system/panel.html", {'duyurular': duyurular,'bayi':bayi})



@login_required(login_url = 'home')
def evrak(request):
    if request.method == 'POST':
        form = GecisNormal(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            imei = request.POST.get('simimei')
            sim_card = SimCard.objects.get(imei=imei)
            sim_card.status = 'used'
            sim_card.save()
            joined_message = "MNT Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)


    else:
        form = GecisNormal()
        sim_cards = SimCard.objects.filter(bayi=request.user,status="pending")
    return render(request,"system/evrak-gir.html",{'form': form, 'sim_cards': sim_cards})




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


from django.shortcuts import render
from .models import SimCard

from django.shortcuts import render
from .models import SimCard, Bayi_Listesi





from django.core.paginator import Paginator
from django.shortcuts import render
from .models import BakiyeHareketleri
@login_required(login_url = 'home')
def bakiye_hareketleri(request):
    hareket_list = BakiyeHareketleri.objects.filter(user=request.user).order_by('-tarih')
    paginator = Paginator(hareket_list, 25) # Her sayfada 200 öğe göster
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'system/bakiyetakip.html', {'page_obj': page_obj})




@login_required(login_url = 'home')
def kontorluYeni(request):
    if request.method == 'POST':
        form = KontorluYeniform(request.POST, request.FILES)
        if form.is_valid():
            operator = request.POST.get('operatoru')
            balance = Bayi_Listesi.objects.get(user=request.user)
            oncekiBakiye = balance.Bayi_Bakiyesi
            oncekiBorc   = balance.Borc
            product = Urun.objects.get(fiyat_kategorisi=balance.Fiyati, urun_adi=operator)
            price = product.urun_fiyati

            if balance.Bayi_Bakiyesi >= price:
                form.save()

                imei = request.POST.get('simimei')
                sim_card = SimCard.objects.get(imei=imei)
                sim_card.status = 'used'
                sim_card.save()

                balance.Bayi_Bakiyesi -= price
                balance.save()

                sonrakikiBakiye = balance.Bayi_Bakiyesi
                sonrakiBorc = balance.Borc


                bakiye_hareketi = BakiyeHareketleri.objects.create(
                    user=request.user,
                    islem_tutari=price,
                    onceki_bakiye=oncekiBakiye,
                    sonraki_bakiye=sonrakikiBakiye,
                    onceki_Borc=oncekiBorc,
                    sonraki_Borc=sonrakiBorc,
                    aciklama=f'{price} Tutarında Yeni Kontörlü Hat ücreti Düşüldü',
                )
                bakiye_hareketi.save()

                joined_message = "KontorlüYeni Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
                url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
                r = requests.get(url)
                return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
            else:
                return HttpResponse("Yetersiz Bakiye Lütfen Bakiye Yükleyin.")
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = KontorluYeniform()
        sim_cards = SimCard.objects.filter(bayi=request.user,status="pending")

    return render(request,"system/kontorlu-yeni-hat.html", {'form': form, 'sim_cards': sim_cards})







@login_required(login_url = 'home')
def FaturaliYeni(request):
    if request.method == 'POST':
        form = FaturaliYeniform(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            imei = request.POST.get('simimei')
            sim_card = SimCard.objects.get(imei=imei)
            sim_card.status = 'used'
            sim_card.save()
            joined_message = "FaturaliYeni Başvurusuna Yeni Bayi Başvurusu Geldi Hadi Hemen işlemlere Başla Çooook Para Lazım (: "
            url = f"https://api.telegram.org/bot{env('Telegram_Token')}/sendMessage?chat_id={env('Telegram_Chat_id')}&text={joined_message}"
            r = requests.get(url)
            return redirect('panel')  # Başarılı işlem sonrası yönlendirilecek sayfa
        else:
            print(form.errors)  # Hataları konsola yazdır
            return HttpResponse(form.errors)
    else:
        form = FaturaliYeniform()
        sim_cards = SimCard.objects.filter(bayi=request.user,status="pending")

    return render(request,"system/faturali-yeni-hat.html", {'form': form, 'sim_cards': sim_cards})


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
def internetBasvuru(request):
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
def evrak_list(request):
    evraklar = Evrak.objects.all()[:150]
    kontorluyenihatlar = KontorluYeniHat.objects.all()[:150]
    faturaliyenihatlar = FaturaliYeniHat.objects.all()[:150]
    sebekeiciler = Sebekeici.objects.all()[:150]
    internetler = internet.objects.all()[:150]

    context = {
        'evraklar': evraklar,
        'kontorluyenihatlar': kontorluyenihatlar,
        'faturaliyenihatlar': faturaliyenihatlar,
        'sebekeiciler': sebekeiciler,
        'internetler': internetler,
    }

    return render(request, 'system/takip.html', context)



@login_required(login_url = 'home')
def bankalar(request):
    bankalar = Banka.objects.filter(Aktifmi=True)
    context = {
        'bankalar': bankalar,
    }
    return render(request, 'system/bankalar.html', context)



@login_required(login_url = 'home')
def logout(request):
    auth.logout(request)
    return redirect("home")

@login_required(login_url = 'home')
def duyurular(request):
    duyurular = Duyuru.objects.all()
    return render(request, 'system/panel.html', {'duyurular': duyurular})




def mntmutabakat(request):
    aktivasyon = Evrak.objects.filter(aktivasyon_durumu='Mutabakat Bekliyor', odeme_durumu='OdemeYapilmadi')

    for obj in aktivasyon:
        user = obj.user
        bayi_listesi = user.bayi_listesi

        oncekiBakiye = bayi_listesi.Bayi_Bakiyesi
        oncekiBorc = bayi_listesi.Borc

        bayi_listesi.Bayi_Bakiyesi += obj.tutar
        bayi_listesi.save()
        obj.aktivasyon_durumu = 'Aktif'
        obj.odeme_durumu = 'OdemeYapildi'
        obj.save()

        sonrakikiBakiye = bayi_listesi.Bayi_Bakiyesi
        sonrakiBorc = bayi_listesi.Borc

        bakiye_hareketi = BakiyeHareketleri.objects.create(
            user=request.user,
            islem_tutari=obj.tutar,
            onceki_bakiye=oncekiBakiye,
            sonraki_bakiye=sonrakikiBakiye,
            onceki_Borc=oncekiBorc,
            sonraki_Borc=sonrakiBorc,
            aciklama=f'{obj.id} {obj.isim} {obj.soyisim} {obj.tc} {obj.numara} {obj.tutar} Tutarında MNT primi yüklendi',
        )
        bakiye_hareketi.save()

    return HttpResponse("Tüm MNT işlemleri Bakiyeleri yüklendi.")


