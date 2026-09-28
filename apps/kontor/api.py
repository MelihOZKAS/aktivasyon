"""Bayi programlarının bağlandığı kapı: Znet protokolü.

Bayi yüklemeyi panele girmeden, alıştığı kontör programından yapar. Program
bizi bir Znet sağlayıcısı sanır ve iki adrese istek atar:

    /servis/tl_servis.php?bayi_kodu=…&sifre=…&operator=vodafone&tip=ses
                         &kontor=100&gsmno=5321234567&tekilnumara=…
        OK|1|Talebiniz işleme alındı.|<düşülen tutar>
        OK|3|<sebep>|0.00

    /servis/tl_kontrol.php?bayi_kodu=…&sifre=…&tekilnumara=…
        1:<mesaj>:<tutar>     yüklendi
        2:islemde:0           sürüyor (askıdaki işlem de bayiye böyle görünür)
        3:<sebep>:0           iptal; tutar bakiyesine döndü

Şifre hesap parolası değil, `ApiErisimi`'nde ayrı üretilen anahtardır.
Kategori `operator` + `tip` koduyla, paket `kontor` koduyla bulunur —
ikisi de panelde veridir. Aynı `tekilnumara` ile gelen ikinci istek yeni
işlem açmaz, ilkini döndürür: program zaman aşımına uğrayıp yeniden
gönderdiğinde numaraya iki kez yüklenmesin.

İstek transaction'ı dışında çalışır (`ATOMIC_REQUESTS` açık): gönderim
kaydı ağa çıkmadan commit edilmeli, yoksa süreç düşünce kaybolur ve işlem
ikinci kez gönderilirdi.

Sonuç sorgusu gelince, işlem işlemdeyse sağlayıcıya da sorulur (en sık
`SORGU_ARALIGI`'nda bir): işçi çalışmasa bile programın sorgusu işi yürütür.
"""

import logging

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.finans.services import SiparisVerilemez
from apps.kontor.models import ApiErisimi, Islem, IslemDurumu, Kanal, Kategori, Paket
from apps.kontor.services import isle, yukleme_baslat

logger = logging.getLogger(__name__)


def _yanit(metin):
    return HttpResponse(metin, content_type="text/plain; charset=utf-8")


def _temiz(metin):
    """Protokol ayraçları ("|", ":") mesajın içinde geçerse program yanlış böler."""
    return " ".join(str(metin or "").replace("|", " ").replace(":", " ").split())


def _para(tutar):
    return f"{tutar:.2f}"


def _parametre(request, ad):
    deger = request.GET.get(ad)
    if deger is None:
        deger = request.POST.get(ad, "")
    return deger.strip()


def _erisim(request):
    kod = _parametre(request, "bayi_kodu")
    sifre = _parametre(request, "sifre")
    if not kod or not sifre:
        return None
    erisim = (
        ApiErisimi.objects.select_related("kullanici", "kullanici__cuzdan", "kullanici__cuzdan__grup")
        .filter(bayi_kodu=kod, aktif=True, kullanici__is_active=True)
        .first()
    )
    if erisim is None or not erisim.anahtar_dogru_mu(sifre):
        return None
    ApiErisimi.objects.filter(pk=erisim.pk).update(son_kullanim=timezone.now())
    return erisim


def _red(sebep):
    return _yanit(f"OK|3|{_temiz(sebep)}|0.00")


@transaction.non_atomic_requests
@csrf_exempt
@require_http_methods(["GET", "POST"])
def tl_servis(request):
    erisim = _erisim(request)
    if erisim is None:
        return _red("Hatalı bayi kodu veya şifre.")

    operator = _parametre(request, "operator").lower()
    tip = _parametre(request, "tip").lower()
    kod = _parametre(request, "kontor")
    hedef = _parametre(request, "gsmno")
    bayi_ref = _parametre(request, "tekilnumara")
    if not (operator and kod and bayi_ref):
        return _red("Eksik bilgi: operator, kontor ve tekilnumara gerekli.")

    kategori = Kategori.objects.filter(api_operator=operator, api_tip=tip, aktif=True).first()
    if kategori is None:
        return _red(f"Tanımsız operatör/tip: {operator} {tip}.")
    # Bazı programlar kupürü "100.00" diye gönderiyor.
    paket = (
        Paket.objects.filter(kategori=kategori, kod=kod).first()
        or Paket.objects.filter(kategori=kategori, kod=kod.removesuffix(".00")).first()
    )
    if paket is None:
        return _red(f"Tanımsız paket: {kod}.")

    try:
        islem = yukleme_baslat(
            erisim.kullanici, paket, hedef, kanal=Kanal.API, bayi_ref=bayi_ref
        )
    except SiparisVerilemez as hata:
        return _red(str(hata))
    except IntegrityError:
        # Aynı referans aynı anda iki kez geldi; ikincisi ilkini döndürür.
        islem = Islem.objects.filter(bayi=erisim.kullanici, bayi_ref=bayi_ref).first()
        if islem is None:
            return _red("İşlem açılamadı, yeniden deneyin.")
    islem.refresh_from_db()
    if islem.durum == IslemDurumu.IPTAL:
        # Cevap yazılırken hiçbir sağlayıcı kabul etmemiş ve para iade edilmiş.
        return _red(islem.sonuc_mesaji or "İşlem iptal edildi.")
    return _yanit(f"OK|1|Talebiniz işleme alındı.|{_para(islem.siparis.tutar)}")


@transaction.non_atomic_requests
@csrf_exempt
@require_http_methods(["GET", "POST"])
def tl_kontrol(request):
    erisim = _erisim(request)
    if erisim is None:
        return _yanit("3:Hatalı bayi kodu veya şifre:0")
    bayi_ref = _parametre(request, "tekilnumara")
    islem = (
        Islem.objects.select_related("siparis").filter(bayi=erisim.kullanici, bayi_ref=bayi_ref).first()
        if bayi_ref
        else None
    )
    if islem is None:
        return _yanit("3:Bu referansla işlem yok:0")

    if islem.durum in (IslemDurumu.SIRADA, IslemDurumu.ISLEMDE):
        islem = isle(islem.pk) or islem

    if islem.durum == IslemDurumu.BASARILI:
        return _yanit(f"1:{_temiz(islem.sonuc_mesaji) or 'Yuklendi'}:{_para(islem.siparis.tutar)}")
    if islem.durum == IslemDurumu.IPTAL:
        return _yanit(f"3:{_temiz(islem.sonuc_mesaji) or 'Iptal'}:0")
    return _yanit("2:islemde:0")
