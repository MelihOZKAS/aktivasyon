from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as TemelGrupAdmin
from django.contrib.auth.admin import UserAdmin as TemelKullaniciAdmin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from django.shortcuts import render

from apps.bayi.models import (
    BayiBasvuruDurumu,
    BayiBasvurusu,
    BayiProfili,
    Duyuru,
    SimKart,
    SimKartDurumu,
)
from apps.bayi.services import HesapAcilamadi, bayi_hesabi_ac
from apps.finans.models import Cuzdan
from apps.katalog.models import Operator


class BayiProfiliInline(StackedInline):
    model = BayiProfili
    can_delete = False
    extra = 0
    fields = (
        ("bayi_mi", "tedarikci_mi"),
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
    fields = (("grup", "islem_yapabilir"), ("bakiye", "borc"))
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
    list_display = ("kullanici", "unvan", "rol_rozeti", "telefon", "sehir")
    search_fields = ("kullanici__username", "unvan", "yetkili_adi", "telefon", "vergi_no")
    autocomplete_fields = ("kullanici",)
    list_filter = ("bayi_mi", "tedarikci_mi", "sehir")
    fieldsets = (
        (
            "Roller",
            {
                "fields": (("bayi_mi", "tedarikci_mi"),),
                "description": (
                    "Roller birbirini dışlamaz. Bayi başvuru getirir ve hakediş alır; "
                    "tedarikçi kendisine atanan işlemleri satın alır, bedeli hesabından düşer."
                ),
            },
        ),
        ("Firma", {"fields": ("kullanici", "unvan", "yetkili_adi", "telefon", "sehir", "adres")}),
        ("Kayıt", {"fields": ("vergi_dairesi", "vergi_no", "notlar")}),
    )

    @admin.display(description="Rol")
    def rol_rozeti(self, obj):
        renkler = {"Bayi": "#0E5E5B", "Tedarikçi": "#B45309", "Bayi ve Tedarikçi": "#0F8A4D"}
        ad = obj.rol_adi
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(ad, "#6F7B8F"),
            ad,
        )


class SimAtamaFormu(forms.Form):
    """SIM kartları bir bayiye zimmetlemek için."""

    bayi = forms.ModelChoiceField(
        label="Hangi bayiye zimmetlensin?",
        queryset=User.objects.filter(is_active=True).order_by("username"),
    )


@admin.register(SimKart)
class SimKartAdmin(ModelAdmin):
    list_display = ("imei", "bayi", "operator", "durum_rozeti", "basvuru", "olusturma_tarihi")
    list_filter = ("durum", "operator", "bayi")
    search_fields = ("imei", "bayi__username", "basvuru__referans_no")
    autocomplete_fields = ("bayi", "operator", "basvuru")
    date_hierarchy = "olusturma_tarihi"
    actions = ("bayiye_ata", "bayiden_geri_al", "arizali_isaretle")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi", "operator", "basvuru")

    @admin.display(description="Durum")
    def durum_rozeti(self, obj):
        renkler = {
            "beklemede": "#6F7B8F",
            "atandi": "#0E5E5B",
            "kullanildi": "#0F8A4D",
            "arizali": "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#64748b"),
            obj.get_durum_display(),
        )

    # -- toplu işlemler ---------------------------------------------------

    @admin.action(description="Seçili SIM kartları bir bayiye zimmetle")
    def bayiye_ata(self, request, secilenler):
        if "uygula" in request.POST:
            form = SimAtamaFormu(request.POST)
            if form.is_valid():
                bayi = form.cleaned_data["bayi"]
                # Kullanılmış kartlar başka bayiye devredilmez.
                atanabilir = secilenler.exclude(durum=SimKartDurumu.KULLANILDI)
                adet = atanabilir.update(bayi=bayi, durum=SimKartDurumu.ATANDI)
                atlanan = secilenler.count() - adet
                self.message_user(
                    request,
                    f"{adet} SIM kart {bayi.get_username()} bayisine zimmetlendi"
                    + (f", {atlanan} tanesi kullanılmış olduğu için atlandı." if atlanan else "."),
                    messages.SUCCESS,
                )
                return None
        else:
            form = SimAtamaFormu()

        return render(
            request,
            "admin/bayi/sim_ata.html",
            {
                **self.admin_site.each_context(request),
                "title": "SIM kart zimmetle",
                "form": form,
                "kartlar": secilenler,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Seçili SIM kartları bayiden geri al (Beklemede'ye döner)")
    def bayiden_geri_al(self, request, secilenler):
        """Kartın bayiyle bağını koparır ve Beklemede'ye döndürür.

        Kullanılmış kartlara dokunulmaz: onlar bir başvuruya bağlı.
        """
        geri_alinabilir = secilenler.exclude(durum=SimKartDurumu.KULLANILDI)
        adet = geri_alinabilir.update(bayi=None, durum=SimKartDurumu.BEKLEMEDE)
        atlanan = secilenler.count() - adet
        self.message_user(
            request,
            f"{adet} SIM kart geri alındı"
            + (f", {atlanan} tanesi kullanılmış olduğu için atlandı." if atlanan else "."),
            messages.SUCCESS if adet else messages.WARNING,
        )

    @admin.action(description="Seçili SIM kartları arızalı işaretle")
    def arizali_isaretle(self, request, secilenler):
        adet = secilenler.update(durum=SimKartDurumu.ARIZALI)
        self.message_user(request, f"{adet} SIM kart arızalı işaretlendi.", messages.SUCCESS)


@admin.register(Duyuru)
class DuyuruAdmin(ModelAdmin):
    list_display = ("baslik", "onemli", "yayin_tarihi", "aktif", "olusturma_tarihi")
    list_editable = ("onemli", "aktif")
    list_filter = ("aktif", "onemli")
    search_fields = ("baslik", "icerik")
    date_hierarchy = "olusturma_tarihi"


@admin.register(BayiBasvurusu)
class BayiBasvurusuAdmin(ModelAdmin):
    """Bayi olmak isteyenlerin bıraktığı talepler."""

    list_display = (
        "ad_soyad", "irtibat_baglantisi", "durum_rozeti",
        "olusturulan_kullanici", "olusturma_tarihi",
    )
    list_filter = ("durum", "olusturma_tarihi")
    search_fields = ("isim", "soyisim", "irtibat")
    date_hierarchy = "olusturma_tarihi"
    readonly_fields = ("isim", "soyisim", "irtibat", "olusturma_tarihi")
    autocomplete_fields = ("olusturulan_kullanici",)
    actions = ("hesap_ac", "gorusuldu_isaretle", "reddet")
    fieldsets = (
        (
            "Başvuran",
            {
                "fields": ("isim", "soyisim", "irtibat", "olusturma_tarihi"),
                "description": "Bu bilgiler başvuran tarafından girildi, değiştirilemez.",
            },
        ),
        (
            "Değerlendirme",
            {
                "fields": ("durum", "notlar", "olusturulan_kullanici"),
                "description": (
                    "Hesabı açmak için listeden başvuruyu seçip “Seçili "
                    "başvurular için bayi hesabı aç” işlemini kullanın. "
                    "Kullanıcı adı telefon numarası olur, parola başvuranın "
                    "kendi seçtiğidir."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("olusturulan_kullanici")

    @admin.display(description="Ad Soyad", ordering="isim")
    def ad_soyad(self, obj):
        return obj.ad_soyad

    @admin.display(description="Telefon")
    def irtibat_baglantisi(self, obj):
        return format_html(
            '<a href="tel:{}" style="font-weight:600">{}</a>', obj.irtibat, obj.irtibat
        )

    @admin.display(description="Durum")
    def durum_rozeti(self, obj):
        renkler = {
            "yeni": "#0E5E5B",
            "gorusuldu": "#B45309",
            "onaylandi": "#0F8A4D",
            "reddedildi": "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    @admin.action(description="Seçili başvurular için bayi hesabı aç")
    def hesap_ac(self, request, secilenler):
        """Kullanıcı adı telefon, parola başvuranın seçtiği parola."""
        acilan, atlanan, hatalar = [], 0, []

        for basvuru in secilenler:
            try:
                kullanici, yeni = bayi_hesabi_ac(basvuru)
            except HesapAcilamadi as hata:
                hatalar.append(f"{basvuru.ad_soyad}: {hata}")
                continue
            if yeni:
                acilan.append(kullanici.get_username())
            else:
                atlanan += 1

        if acilan:
            self.message_user(
                request,
                format_html(
                    "{} hesap açıldı: {}. Kullanıcı adı telefon numarasıdır; "
                    "parolayı başvuran kendisi seçti. Cüzdan grubunu (fiyat "
                    "kademesi) belirlemeyi unutmayın.",
                    len(acilan),
                    ", ".join(acilan),
                ),
                messages.SUCCESS,
            )
        if atlanan:
            self.message_user(
                request, f"{atlanan} başvurunun hesabı zaten açılmıştı.", messages.INFO
            )
        for satir in hatalar:
            self.message_user(request, satir, messages.ERROR)

    @admin.action(description="Görüşüldü olarak işaretle")
    def gorusuldu_isaretle(self, request, secilenler):
        adet = secilenler.update(durum=BayiBasvuruDurumu.GORUSULDU)
        self.message_user(request, f"{adet} başvuru görüşüldü işaretlendi.", messages.SUCCESS)

    @admin.action(description="Reddet")
    def reddet(self, request, secilenler):
        adet = secilenler.update(durum=BayiBasvuruDurumu.REDDEDILDI)
        self.message_user(request, f"{adet} başvuru reddedildi.", messages.SUCCESS)
