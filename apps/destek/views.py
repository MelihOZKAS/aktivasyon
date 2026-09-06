"""Bayi tarafındaki destek ekranları.

Talep her rolde açılabilir: bayi de tedarikçi de yönetime ulaşabilmeli,
bu yüzden görünümler role göre kısıtlanmaz — yalnızca giriş yeterlidir.
Herkes **kendi** taleplerini görür; başkasının referansı denenirse 404.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.destek.forms import TalepFormu, YanitFormu
from apps.destek.models import DestekTalebi, TalepDurumu
from apps.destek.services import mesaj_ekle, talep_ac


def _talebi_getir(kullanici, referans):
    return get_object_or_404(
        DestekTalebi.objects.filter(bayi=kullanici).select_related("basvuru"),
        referans_no=referans,
    )


@login_required
def liste(request):
    talepler = DestekTalebi.objects.filter(bayi=request.user).select_related("basvuru")

    sayfalayici = Paginator(talepler, 20)
    return render(
        request,
        "destek/liste.html",
        {
            "sayfa": sayfalayici.get_page(request.GET.get("sayfa")),
            "toplam": sayfalayici.count,
        },
    )


@login_required
def yeni(request):
    if request.method == "POST":
        form = TalepFormu(request.POST, bayi=request.user)
        if form.is_valid():
            talep = talep_ac(
                request.user,
                form.cleaned_data["konu"],
                form.cleaned_data["icerik"],
                basvuru=form.cleaned_data.get("basvuru"),
            )
            messages.success(
                request,
                f"Talebin alındı. Talep numaran: {talep.referans_no}. "
                "Yanıt geldiğinde bu sayfada görürsün.",
            )
            return redirect("destek:detay", referans=talep.referans_no)
    else:
        form = TalepFormu(bayi=request.user)

    return render(request, "destek/yeni.html", {"form": form})


@login_required
def detay(request, referans):
    talep = _talebi_getir(request.user, referans)

    if request.method == "POST":
        form = YanitFormu(request.POST)
        if form.is_valid():
            mesaj_ekle(talep, request.user, form.cleaned_data["icerik"])
            return redirect("destek:detay", referans=referans)
    else:
        form = YanitFormu()

    return render(
        request,
        "destek/detay.html",
        {
            "talep": talep,
            "mesajlar": talep.mesajlar.select_related("gonderen"),
            "form": form,
        },
    )


@login_required
@require_POST
def kapat(request, referans):
    """Bayi işi bitince talebi kendisi kapatabilir.

    Kapalı talebe yazılan yeni mesaj onu yeniden açar (`mesaj_ekle`);
    kapatmak konuşmayı bitirmez, yalnızca kuyruktan düşürür.
    """
    talep = _talebi_getir(request.user, referans)
    if talep.acik_mi:
        talep.durum = TalepDurumu.KAPALI
        talep.save(update_fields=["durum", "guncelleme_tarihi"])
        messages.success(request, "Talep kapatıldı.")
    return redirect("destek:detay", referans=referans)
