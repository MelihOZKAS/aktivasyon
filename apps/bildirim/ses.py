"""Yönetim panelindeki "çın" sesinin kaynağı.

Panel (`static/yonetim-ses.js`) bu adresi aralıkla sorar ve dört kayıt
türünün en son numarasını alır; sayılardan biri arttıysa yeni bir şey
gelmiş demektir ve ses çalar. Sayı değil en son `pk` döner: bekleyen iş
sayısı aynı anda hem artıp hem azalabilir (biri gelir, biri onaylanır),
en son numara yalnızca yeni kayıtla artar.

Telegram'dan ayrıdır: Telegram gruba gider, ses yalnızca paneli açık olan
yöneticinin ekranında çalar. Listeyi büyütmeden önce Telegram'daki
dersi hatırla — her şeyde çalan ses hiçbir şeyde çalmamakla aynıdır.
"""

from django.apps import apps
from django.db.models import Max
from django.http import JsonResponse
from django.views.decorators.cache import never_cache

KAYNAKLAR = {
    "basvuru": "basvurular.Basvuru",
    "bayi_basvurusu": "bayi.BayiBasvurusu",
    "odeme": "finans.OdemeBildirimi",
    "kontor": "kontor.Islem",
    "fatura": "fatura.Odeme",
}


@never_cache
def yeni_kayitlar(request):
    # Giriş sayfasına yönlendirme değil 403: oturumu düşen sekme HTML'i JSON
    # sanıp her turda yeniden denemesin, sormayı bıraksın.
    if not (request.user.is_active and request.user.is_staff):
        return JsonResponse({}, status=403)
    return JsonResponse(
        {
            ad: apps.get_model(model).objects.aggregate(son=Max("pk"))["son"] or 0
            for ad, model in KAYNAKLAR.items()
        }
    )
