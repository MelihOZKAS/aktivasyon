"""Sorgu robotunun kapısı. Sözleşme: znetfaturasorgu/DJANGO_API.md.

Robot laptopta çalışır ve **bize sorar** (pull): laptop dışarı port açmaz.
Her istek `Authorization: Bearer <anahtar>` taşır; anahtar robotun kaydında
yalnızca özetiyle durur. Her doğrulanmış istek nabız sayılır — nabız ucu
çökse de robot çevrimiçi görünür.
"""

import json
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from apps.fatura.models import Robot, anahtar_ozeti
from apps.fatura.services import is_ver, katalog_yaz, nabiz, sonuc_yaz


def _robot(request):
    baslik = request.headers.get("Authorization", "")
    if not baslik.startswith("Bearer "):
        return None
    anahtar = baslik[7:].strip()
    if not anahtar:
        return None
    return Robot.objects.filter(aktif=True, anahtar_ozeti=anahtar_ozeti(anahtar)).first()


def _robot_gerekli(yontem):
    def sarmala(gorunum):
        @wraps(gorunum)
        def sarmalayici(request):
            if request.method != yontem:
                return JsonResponse({"hata": f"{yontem} bekleniyor"}, status=405)
            robot = _robot(request)
            if robot is None:
                return JsonResponse({"hata": "yetkisiz"}, status=401)
            Robot.objects.filter(pk=robot.pk).update(son_nabiz=timezone.now())
            return gorunum(request, robot)

        return csrf_exempt(sarmalayici)

    return sarmala


def _govde(request):
    try:
        veri = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return veri if isinstance(veri, dict) else None


@_robot_gerekli("GET")
def is_(request, robot):
    sorgu = is_ver(robot)
    if sorgu is None:
        return JsonResponse({"var": False})
    return JsonResponse({
        "var": True,
        "talep": {
            "talep_id": sorgu.pk,
            "kurum_id": sorgu.kurum.kod,
            "kurum_adi": sorgu.kurum.ad,
            "numara": sorgu.numara,
        },
    })


@_robot_gerekli("POST")
def sonuc(request, robot):
    veri = _govde(request)
    if veri is None or not str(veri.get("talep_id", "")).isdigit():
        return JsonResponse({"hata": "talep_id gerekli"}, status=400)
    if veri.get("basarisiz"):
        sonuc_yaz(robot, int(veri["talep_id"]), hata=str(veri.get("hata") or "robot hatası"))
    else:
        sonuc_yaz(robot, int(veri["talep_id"]), veri=veri.get("veri") or {})
    return JsonResponse({"ok": True})


@_robot_gerekli("POST")
def kalp(request, robot):
    veri = _govde(request) or {}
    nabiz(
        robot,
        durum=str(veri.get("durum") or ""),
        oturum=str(veri.get("oturum") or ""),
        mesai=str(veri.get("mesai") or ""),
    )
    return JsonResponse({"ok": True})


@_robot_gerekli("POST")
def katalog(request, robot):
    veri = _govde(request)
    if veri is None or not isinstance(veri.get("kurumlar"), list):
        return JsonResponse({"hata": "kurumlar listesi gerekli"}, status=400)
    eklenen, guncellenen = katalog_yaz(veri["kurumlar"], yeni_aktif=False)
    return JsonResponse({"eklenen": eklenen, "guncellenen": guncellenen})
