"""Rol tabanlı erişim.

Bir kullanıcı hem bayi hem tedarikçi olabilir. Bayi ekranları (başvuru
girme, hakedişler) yalnızca bayi rolüne, tedarikçi ekranları yalnızca
tedarikçi rolüne açıktır. Profili olmayan eski kullanıcılar bayi sayılır.
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def _profil(kullanici):
    return getattr(kullanici, "bayi_profili", None)


def bayi_mi(kullanici):
    profil = _profil(kullanici)
    # Profil yoksa bayi kabul edilir: eski kayıtlar kilitlenmesin.
    return profil.bayi_mi if profil else True


def tedarikci_mi(kullanici):
    profil = _profil(kullanici)
    return bool(profil and profil.tedarikci_mi)


def baslangic_sayfasi(kullanici):
    """Kullanıcı giriş yaptığında hangi ekrana düşmeli?"""
    if kullanici.is_staff:
        return "admin:index"
    if not bayi_mi(kullanici) and tedarikci_mi(kullanici):
        return "bayi:tedarikci-panel"
    return "bayi:panel"


def bayi_gerekli(gorunum):
    """Yalnızca bayi rolü olanlara açar."""

    @wraps(gorunum)
    def sarmalayici(request, *args, **kwargs):
        if not bayi_mi(request.user):
            messages.info(
                request, "Bu bölüm bayi hesapları içindir."
            )
            return redirect(baslangic_sayfasi(request.user))
        return gorunum(request, *args, **kwargs)

    return sarmalayici


def tedarikci_gerekli(gorunum):
    """Yalnızca tedarikçi rolü olanlara açar."""

    @wraps(gorunum)
    def sarmalayici(request, *args, **kwargs):
        if not tedarikci_mi(request.user):
            messages.info(
                request, "Bu bölüm tedarikçi hesapları içindir."
            )
            return redirect(baslangic_sayfasi(request.user))
        return gorunum(request, *args, **kwargs)

    return sarmalayici
