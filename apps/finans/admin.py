from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from apps.finans.models import (
    Banka,
    BayiGrubu,
    Cuzdan,
    CuzdanHareketi,
    UcretKurali,
)
from apps.finans.services import bakiye_yukle

SIFIR = Decimal("0.00")


@admin.register(BayiGrubu)
class BayiGrubuAdmin(ModelAdmin):
    list_display = ("ad", "varsayilan_borc_limiti", "bayi_sayisi", "aktif")
    search_fields = ("ad",)
    list_filter = ("aktif",)

    @admin.display(description="Bayi Sayısı")
    def bayi_sayisi(self, obj):
        return obj.cuzdanlar.count()


class BakiyeYuklemeFormu(forms.Form):
    """Admin'den tek bayiye bakiye yüklemek için kullanılan form."""

    tutar = forms.DecimalField(label="Tutar", max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    banka = forms.ModelChoiceField(
        label="Banka", queryset=Banka.objects.filter(aktif=True), required=False
    )
    aciklama = forms.CharField(label="Açıklama", max_length=255, required=False)


@admin.register(Cuzdan)
class CuzdanAdmin(ModelAdmin):
    list_display = (
        "bayi",
        "grup",
        "bakiye_gosterimi",
        "borc_gosterimi",
        "limit_gosterimi",
        "kullanilabilir_gosterimi",
        "islem_yapabilir",
        "bakiye_yukle_baglantisi",
    )
    list_filter = ("grup", "islem_yapabilir")
    search_fields = ("bayi__username", "bayi__first_name", "bayi__last_name")
    autocomplete_fields = ("bayi", "grup")
    readonly_fields = ("bakiye", "borc", "kullanilabilir_gosterimi")
    fieldsets = (
        ("Bayi", {"fields": ("bayi", "grup", "islem_yapabilir")}),
        (
            "Durum",
            {
                "fields": ("bakiye", "borc", "kullanilabilir_gosterimi"),
                "description": (
                    "Bakiye ve borç elle değiştirilemez. Değişiklik için "
                    "“Cüzdan Hareketleri” üzerinden işlem yapın."
                ),
            },
        ),
        (
            "Limit",
            {
                "fields": ("borc_limiti",),
                "description": "Boş bırakılırsa bayi grubunun varsayılan limiti geçerli olur.",
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi", "grup")

    @display(description="Bakiye", ordering="bakiye")
    def bakiye_gosterimi(self, obj):
        renk = "#16a34a" if obj.bakiye >= SIFIR else "#dc2626"
        return format_html('<b style="color:{}">{} ₺</b>', renk, obj.bakiye)

    @display(description="Borç", ordering="borc")
    def borc_gosterimi(self, obj):
        if obj.borc <= SIFIR:
            return format_html('<span style="color:#94a3b8">yok</span>')
        return format_html('<b style="color:#dc2626">{} ₺</b>', obj.borc)

    @display(description="Borç Limiti")
    def limit_gosterimi(self, obj):
        kaynak = "bayiye özel" if obj.borc_limiti is not None else "grup varsayılanı"
        return format_html(
            '{} ₺ <span style="color:#94a3b8;font-size:.75rem">({})</span>',
            obj.gecerli_borc_limiti,
            kaynak,
        )

    @display(description="Kullanılabilir")
    def kullanilabilir_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.kullanilabilir_tutar)

    def get_urls(self):
        return [
            path(
                "<int:cuzdan_id>/bakiye-yukle/",
                self.admin_site.admin_view(self.bakiye_yukle_gorunumu),
                name="finans_cuzdan_bakiye_yukle",
            ),
            *super().get_urls(),
        ]

    def bakiye_yukle_gorunumu(self, request, cuzdan_id):
        """Tek bayiye bakiye yükleme ekranı. Borç varsa önce borçtan düşer."""
        cuzdan = self.get_object(request, cuzdan_id)
        if cuzdan is None:
            messages.error(request, "Cüzdan bulunamadı.")
            return redirect("admin:finans_cuzdan_changelist")

        if request.method == "POST":
            form = BakiyeYuklemeFormu(request.POST)
            if form.is_valid():
                tutar = form.cleaned_data["tutar"]
                bakiye_yukle(
                    cuzdan,
                    tutar,
                    aciklama=form.cleaned_data["aciklama"],
                    banka=form.cleaned_data["banka"],
                    olusturan=request.user,
                    anahtar=f"admin:{request.user.pk}:{cuzdan.pk}:{timezone.now().timestamp()}",
                )
                messages.success(
                    request,
                    f"{cuzdan.bayi.get_username()} hesabına {tutar} ₺ işlendi.",
                )
                return redirect("admin:finans_cuzdan_change", cuzdan.pk)
        else:
            form = BakiyeYuklemeFormu()

        baglam = {
            **self.admin_site.each_context(request),
            "title": f"Bakiye Yükle · {cuzdan.bayi.get_username()}",
            "cuzdan": cuzdan,
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/finans/bakiye_yukle.html", baglam)

    @display(description="İşlem")
    def bakiye_yukle_baglantisi(self, obj):
        url = reverse("admin:finans_cuzdan_bakiye_yukle", args=[obj.pk])
        return format_html(
            '<a href="{}" style="background:#4f46e5;color:#fff;padding:.3rem .7rem;'
            'border-radius:.375rem;font-size:.75rem;font-weight:600;text-decoration:none">'
            "Bakiye Yükle</a>",
            url,
        )


@admin.register(CuzdanHareketi)
class CuzdanHareketiAdmin(ModelAdmin):
    list_display = (
        "tarih",
        "cuzdan",
        "tip",
        "tutar_gosterimi",
        "sonraki_bakiye",
        "sonraki_borc",
        "kaynak",
        "aciklama",
    )
    list_filter = ("tip", "tarih", "cuzdan__grup")
    search_fields = (
        "cuzdan__bayi__username",
        "aciklama",
        "basvuru__referans_no",
        "idempotency_anahtari",
    )
    date_hierarchy = "tarih"
    list_per_page = 100

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("cuzdan__bayi", "basvuru", "kural", "banka", "olusturan")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description="Tutar", ordering="tutar")
    def tutar_gosterimi(self, obj):
        renk = "#16a34a" if obj.tutar >= SIFIR else "#dc2626"
        isaret = "+" if obj.tutar >= SIFIR else ""
        return format_html('<b style="color:{}">{}{} ₺</b>', renk, isaret, obj.tutar)

    @display(description="Kaynak")
    def kaynak(self, obj):
        if obj.basvuru_id:
            return obj.basvuru.referans_no
        if obj.banka_id:
            return obj.banka.banka_adi
        return "—"


@admin.register(UcretKurali)
class UcretKuraliAdmin(ModelAdmin):
    list_display = (
        "ad",
        "yon_rozeti",
        "tutar_gosterimi",
        "kapsam_ozeti",
        "tetikleyici_durum",
        "oncelik",
        "aktif",
    )
    list_editable = ("oncelik", "aktif")
    list_filter = ("yon", "aktif", "kategori", "operator", "bayi_grubu", "tetikleyici_durum")
    search_fields = ("ad",)
    autocomplete_fields = (
        "kategori",
        "operator",
        "tarife",
        "kampanya",
        "bayi_grubu",
        "bayi",
        "tetikleyici_durum",
    )
    fieldsets = (
        ("Kural", {"fields": ("ad", "yon", "tutar", "tetikleyici_durum")}),
        (
            "Kapsam",
            {
                "fields": (
                    "kategori",
                    "operator",
                    "tarife",
                    "kampanya",
                    "bayi_grubu",
                    "bayi",
                ),
                "description": (
                    "Boş bırakılan her alan “hepsi” anlamına gelir. Bir başvuruya "
                    "birden fazla kural uyarsa en dar kapsamlı olan uygulanır; "
                    "eşitlik durumunda önceliği yüksek olan kazanır."
                ),
            },
        ),
        (
            "Geçerlilik",
            {"fields": ("baslangic_tarihi", "bitis_tarihi", "oncelik", "aktif")},
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "kategori", "operator", "tarife", "kampanya", "bayi_grubu", "bayi", "tetikleyici_durum"
            )
        )

    @display(description="Yön")
    def yon_rozeti(self, obj):
        renk = "#dc2626" if obj.yon == "tahsilat" else "#16a34a"
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renk,
            obj.get_yon_display(),
        )

    @display(description="Tutar", ordering="tutar")
    def tutar_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.tutar)

    @display(description="Kapsam")
    def kapsam_ozeti(self, obj):
        parcalar = [
            (obj.bayi, "Bayi"),
            (obj.kampanya, "Kampanya"),
            (obj.tarife, "Tarife"),
            (obj.bayi_grubu, "Grup"),
            (obj.operator, "Operatör"),
            (obj.kategori, "Kategori"),
        ]
        etiketler = [f"{ad}: {nesne}" for nesne, ad in parcalar if nesne]
        if not etiketler:
            return format_html('<span style="color:#94a3b8">tüm başvurular</span>')
        return format_html(
            '<span style="font-size:.8rem">{}</span>', " · ".join(etiketler)
        )


@admin.register(Banka)
class BankaAdmin(ModelAdmin):
    list_display = ("banka_adi", "hesap_sahibi", "iban", "bakiye", "bayiye_gorunur", "aktif")
    list_editable = ("bayiye_gorunur", "aktif")
    search_fields = ("banka_adi", "hesap_sahibi", "iban")
    list_filter = ("aktif", "bayiye_gorunur")
    readonly_fields = ("bakiye",)
