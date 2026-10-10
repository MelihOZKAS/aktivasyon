"""Sorgu robotunun kapısı. Sözleşme: znetfaturasorgu/DJANGO_API.md.

Robot laptopta ya da Windows sunucuda çalışır ve **bize sorar** (pull):
robotun makinesi dışarı port açmaz. Aynı kapıdan iki iş verilir: fatura
sorgusu ve kontörün aboneye özel paket sorgusu (`tur`).
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
from apps.fatura.services import katalog_yaz, nabiz, siradaki_is, sonuc_yaz
from apps.kontor.sorgu import kontorbizde


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
    # Robot hangi işleri yapabildiğini her istekte söyler (`isler=fatura,paket`).
    # Eski sürüm söylemez: ona paket işi verilmez, paket için çevrimiçi sayılmaz.
    paket = "paket" in request.GET.get("isler", "").split(",")
    if robot.paket_sorgusu != paket:
        Robot.objects.filter(pk=robot.pk).update(paket_sorgusu=paket)
    sira = siradaki_is(robot, paket=paket)
    if sira is None:
        return JsonResponse({"var": False})
    tur, kayit = sira
    if tur == "paket":
        return JsonResponse({
            "var": True,
            "tur": "paket",
            "talep": {"talep_id": kayit.pk, "numara": kayit.numara, "operator": kayit.operator},
        })
    return JsonResponse({
        "var": True,
        "tur": "fatura",
        "talep": {
            "talep_id": kayit.pk,
            "kurum_id": kayit.kurum.kod,
            "kurum_adi": kayit.kurum.ad,
            "numara": kayit.numara,
        },
    })


@_robot_gerekli("POST")
def sonuc(request, robot):
    veri = _govde(request)
    if veri is None or not str(veri.get("talep_id", "")).isdigit():
        return JsonResponse({"hata": "talep_id gerekli"}, status=400)
    # Talep numaraları kuyruk başınadır; tür yoksa (eski robot) fatura.
    yaz = kontorbizde.sonuc_yaz if veri.get("tur") == "paket" else sonuc_yaz
    if veri.get("basarisiz"):
        yaz(robot, int(veri["talep_id"]), hata=str(veri.get("hata") or "robot hatası"))
    else:
        yaz(robot, int(veri["talep_id"]), veri=veri.get("veri") or {})
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
