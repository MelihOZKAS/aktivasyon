from django import forms
from django.contrib import admin, messages
from django.shortcuts import render
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

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
    fields = ("sira", "etiket", "kod", "tip", "cekirdek_alan", "grup", "zorunlu", "max_uzunluk", "aktif")
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


class AlanKopyalaFormu(forms.Form):
    """Bir kategorinin alanlarını başka kategoriye taşımak için."""

    hedef = forms.ModelChoiceField(
        label="Hangi kategoriye kopyalansın?",
        queryset=BasvuruKategorisi.objects.filter(aktif=True),
    )


@admin.register(KategoriAlani)
class KategoriAlaniAdmin(ModelAdmin):
    list_display = (
        "etiket", "kategori", "tip_gosterimi", "kod", "grup", "zorunlu", "sira", "aktif"
    )
    list_editable = ("sira", "aktif")
    list_filter = ("aktif", "kategori", "tip", "zorunlu", "cekirdek_alan")
    search_fields = ("etiket", "kod", "kategori__ad")
    autocomplete_fields = ("kategori", "kosul_alani")
    actions = ("alanlari_kopyala",)
    fieldsets = (
        (
            "Tanım",
            {
                "fields": ("kategori", "etiket", "kod", "tip", "cekirdek_alan", "grup"),
                "description": (
                    "“Çekirdek Alan” doldurulursa değer başvurunun kendi kolonuna "
                    "yazılır ve aranabilir olur (isim, TC no, telefon gibi). "
                    "Boş bırakılırsa alan bu kategoriye özel ek bilgi olarak saklanır."
                ),
            },
        ),
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

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("kategori")

    @display(description="Tip")
    def tip_gosterimi(self, obj):
        if obj.cekirdek_alan:
            return format_html(
                '{} <span style="color:#0F8A4D;font-size:.72rem">· aranabilir</span>',
                obj.get_tip_display(),
            )
        return obj.get_tip_display()

    @admin.action(description="Seçili alanları başka kategoriye kopyala")
    def alanlari_kopyala(self, request, secilenler):
        """Aynı form yapısını yeniden kurmak yerine kopyalayıp düzenlemek için."""
        if "uygula" in request.POST:
            form = AlanKopyalaFormu(request.POST)
            if form.is_valid():
                hedef = form.cleaned_data["hedef"]
                eklenen = atlanan = 0
                for alan in secilenler:
                    if alan.kategori_id == hedef.pk:
                        atlanan += 1
                        continue
                    _, olusturuldu = KategoriAlani.objects.get_or_create(
                        kategori=hedef,
                        kod=alan.kod,
                        defaults={
                            "etiket": alan.etiket,
                            "tip": alan.tip,
                            # Çekirdek alan bir kategoride tek kez bulunabilir.
                            "cekirdek_alan": alan.cekirdek_alan
                            if not KategoriAlani.objects.filter(
                                kategori=hedef, cekirdek_alan=alan.cekirdek_alan
                            ).exclude(cekirdek_alan="").exists()
                            else "",
                            "grup": alan.grup,
                            "zorunlu": alan.zorunlu,
                            "yardim_metni": alan.yardim_metni,
                            "placeholder": alan.placeholder,
                            "secenekler": alan.secenekler,
                            "dogrulama_deseni": alan.dogrulama_deseni,
                            "min_uzunluk": alan.min_uzunluk,
                            "max_uzunluk": alan.max_uzunluk,
                            "sira": alan.sira,
                        },
                    )
                    eklenen += olusturuldu
                    atlanan += not olusturuldu

                self.message_user(
                    request,
                    f"{hedef.ad}: {eklenen} alan eklendi"
                    + (f", {atlanan} alan zaten vardı." if atlanan else "."),
                    messages.SUCCESS,
                )
                return None
        else:
            form = AlanKopyalaFormu()

        return render(
            request,
            "admin/katalog/alan_kopyala.html",
            {
                **self.admin_site.each_context(request),
                "title": "Alanları kopyala",
                "form": form,
                "alanlar": secilenler,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )
