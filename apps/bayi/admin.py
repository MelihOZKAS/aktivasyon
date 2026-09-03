from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as TemelGrupAdmin
from django.contrib.auth.admin import UserAdmin as TemelKullaniciAdmin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from apps.bayi.models import BayiProfili, Duyuru, SimKart
from apps.finans.models import Cuzdan


class BayiProfiliInline(StackedInline):
    model = BayiProfili
    can_delete = False
    extra = 0
    fields = (
        ("unvan", "yetkili_adi"),
        ("telefon", "sehir"),
        "adres",
        ("vergi_dairesi", "vergi_no"),
        "notlar",
    )


class CuzdanInline(StackedInline):
    model = Cuzdan
    can_delete = False
    extra = 0
    fields = (("grup", "islem_yapabilir"), ("bakiye", "borc"), ("borc_izni", "borc_limiti"))
    readonly_fields = ("bakiye", "borc")


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class KullaniciAdmin(TemelKullaniciAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    inlines = [BayiProfiliInline, CuzdanInline]
    list_display = (
        "username",
        "unvan_gosterimi",
        "bakiye_gosterimi",
        "email",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "cuzdan__grup")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi_profili", "cuzdan")

    @admin.display(description="Ünvan")
    def unvan_gosterimi(self, obj):
        profil = getattr(obj, "bayi_profili", None)
        return profil.unvan if profil and profil.unvan else "—"

    @admin.display(description="Bakiye")
    def bakiye_gosterimi(self, obj):
        cuzdan = getattr(obj, "cuzdan", None)
        if not cuzdan:
            return format_html('<span style="color:#94a3b8">cüzdan yok</span>')
        renk = "#16a34a" if cuzdan.bakiye >= 0 else "#dc2626"
        return format_html('<b style="color:{}">{} ₺</b>', renk, cuzdan.bakiye)


@admin.register(Group)
class GrupAdmin(TemelGrupAdmin, ModelAdmin):
    pass


@admin.register(BayiProfili)
class BayiProfiliAdmin(ModelAdmin):
    list_display = ("kullanici", "unvan", "yetkili_adi", "telefon", "sehir")
    search_fields = ("kullanici__username", "unvan", "yetkili_adi", "telefon", "vergi_no")
    autocomplete_fields = ("kullanici",)
    list_filter = ("sehir",)


@admin.register(SimKart)
class SimKartAdmin(ModelAdmin):
    list_display = ("imei", "bayi", "operator", "durum_rozeti", "basvuru", "olusturma_tarihi")
    list_filter = ("durum", "operator", "bayi")
    search_fields = ("imei", "bayi__username", "basvuru__referans_no")
    autocomplete_fields = ("bayi", "operator", "basvuru")
    date_hierarchy = "olusturma_tarihi"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi", "operator", "basvuru")

    @admin.display(description="Durum")
    def durum_rozeti(self, obj):
        renkler = {
            "stokta": "#3b82f6",
            "kullanildi": "#16a34a",
            "arizali": "#dc2626",
            "iade": "#78716c",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#64748b"),
            obj.get_durum_display(),
        )


@admin.register(Duyuru)
class DuyuruAdmin(ModelAdmin):
    list_display = ("baslik", "onemli", "yayin_tarihi", "aktif", "olusturma_tarihi")
    list_editable = ("onemli", "aktif")
    list_filter = ("aktif", "onemli")
    search_fields = ("baslik", "icerik")
    date_hierarchy = "olusturma_tarihi"
