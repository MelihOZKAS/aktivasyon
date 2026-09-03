from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.katalog.models import (
    BasvuruKategorisi,
    Kampanya,
    KategoriAlani,
    Operator,
    Tarife,
)


class KategoriAlaniInline(TabularInline):
    model = KategoriAlani
    extra = 0
    fields = ("sira", "kod", "etiket", "tip", "grup", "zorunlu", "aktif")
    ordering = ("sira",)
    show_change_link = True


class TarifeInline(TabularInline):
    model = Tarife
    extra = 0
    fields = ("operator", "ad", "musteri_tipi", "sira", "aktif")
    ordering = ("operator", "sira")
    show_change_link = True


class KampanyaInline(TabularInline):
    model = Kampanya
    extra = 0
    fields = ("ad", "baslangic_tarihi", "bitis_tarihi", "sira", "aktif")
    show_change_link = True


@admin.register(Operator)
class OperatorAdmin(ModelAdmin):
    list_display = ("ad", "renk_rozeti", "sira", "aktif")
    list_editable = ("sira", "aktif")
    search_fields = ("ad",)
    list_filter = ("aktif",)
    prepopulated_fields = {"slug": ("ad",)}

    @admin.display(description="Renk")
    def renk_rozeti(self, obj):
        return format_html(
            '<span style="display:inline-block;width:1.5rem;height:1.5rem;'
            'border-radius:.375rem;background:{};border:1px solid rgba(0,0,0,.1)"></span>',
            obj.renk,
        )


@admin.register(BasvuruKategorisi)
class BasvuruKategorisiAdmin(ModelAdmin):
    list_display = ("ad", "musteri_tipi", "alan_sayisi", "tarife_sayisi", "sira", "aktif")
    list_editable = ("sira", "aktif")
    list_filter = ("aktif", "musteri_tipi")
    search_fields = ("ad", "aciklama")
    prepopulated_fields = {"slug": ("ad",)}
    filter_horizontal = ("operatorler",)
    inlines = [KategoriAlaniInline, TarifeInline]
    fieldsets = (
        ("Tanım", {"fields": ("ad", "slug", "aciklama", "ikon")}),
        ("Kapsam", {"fields": ("operatorler", "musteri_tipi", "tarife_zorunlu")}),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )

    @admin.display(description="Form Alanı")
    def alan_sayisi(self, obj):
        return obj.alanlar.count()

    @admin.display(description="Tarife")
    def tarife_sayisi(self, obj):
        return obj.tarifeler.count()


@admin.register(Tarife)
class TarifeAdmin(ModelAdmin):
    list_display = ("ad", "kategori", "operator", "musteri_tipi", "kampanya_sayisi", "aktif")
    list_filter = ("aktif", "kategori", "operator", "musteri_tipi")
    search_fields = ("ad", "kategori__ad", "operator__ad")
    autocomplete_fields = ("kategori", "operator")
    inlines = [KampanyaInline]

    @admin.display(description="Kampanya")
    def kampanya_sayisi(self, obj):
        return obj.kampanyalar.count()


@admin.register(Kampanya)
class KampanyaAdmin(ModelAdmin):
    list_display = ("ad", "tarife", "baslangic_tarihi", "bitis_tarihi", "gecerli_mi", "aktif")
    list_filter = ("aktif", "tarife__kategori", "tarife__operator")
    search_fields = ("ad", "tarife__ad")
    autocomplete_fields = ("tarife",)

    @admin.display(description="Şu An Geçerli", boolean=True)
    def gecerli_mi(self, obj):
        return obj.su_an_gecerli


@admin.register(KategoriAlani)
class KategoriAlaniAdmin(ModelAdmin):
    list_display = ("etiket", "kategori", "kod", "tip", "grup", "zorunlu", "sira", "aktif")
    list_editable = ("sira", "aktif")
    list_filter = ("aktif", "kategori", "tip", "zorunlu")
    search_fields = ("etiket", "kod", "kategori__ad")
    autocomplete_fields = ("kategori", "kosul_alani")
    fieldsets = (
        ("Tanım", {"fields": ("kategori", "kod", "etiket", "tip", "grup")}),
        ("Davranış", {"fields": ("zorunlu", "yardim_metni", "placeholder", "secenekler")}),
        (
            "Doğrulama",
            {
                "classes": ("collapse",),
                "fields": ("dogrulama_deseni", "min_uzunluk", "max_uzunluk"),
            },
        ),
        (
            "Koşullu Gösterim",
            {"classes": ("collapse",), "fields": ("kosul_alani", "kosul_degeri")},
        ),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )
