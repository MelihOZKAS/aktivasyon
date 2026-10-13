"""Popup duyuru: bayi sayfalarının altına çizilir.

Bağlam işlemcisinde değil burada durur: işlemci her şablonda (HTMX
parçaları, yönetim paneli) çalışıyor, sorgu yalnızca tam sayfada atılsın.
"""

from django import template

from apps.bayi.models import PopupDuyuru

register = template.Library()


@register.inclusion_tag("bayi/parca_popup.html", takes_context=True)
def popup_duyuru(context):
    request = context.get("request")
    kullanici = getattr(request, "user", None)
    if not kullanici or not kullanici.is_authenticated or not context.get("bayi_mi"):
        return {"duyuru": None}
    return {
        "duyuru": PopupDuyuru.okunmamis(kullanici),
        "request": request,
        "csrf_token": context.get("csrf_token"),
    }
