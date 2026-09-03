from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from apps.basvurular.models import (
    Basvuru,
    BasvuruBelgesi,
    BasvuruDurumu,
    DurumGecmisi,
)
from apps.finans.services import YetersizBakiye


class BasvuruBelgesiInline(TabularInline):
    model = BasvuruBelgesi
    extra = 0
    fields = ("etiket", "alan_kodu", "dosya", "onizleme", "yuklenme_tarihi")
    readonly_fields = ("onizleme", "yuklenme_tarihi")

    @admin.display(description="Önizleme")
    def onizleme(self, obj):
        if not obj.dosya:
            return "—"
        ad = obj.dosya.name.lower()
        if ad.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">'
                '<img src="{}" style="max-height:64px;border-radius:.375rem"></a>',
                obj.dosya.url,
                obj.dosya.url,
            )
        return format_html('<a href="{}" target="_blank" rel="noopener">Dosyayı aç</a>', obj.dosya.url)


class DurumGecmisiInline(TabularInline):
    model = DurumGecmisi
    extra = 0
    fields = ("tarih", "onceki_durum", "yeni_durum", "degistiren", "aciklama")
    readonly_fields = fields
    ordering = ("-tarih",)
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class CuzdanHareketiInline(TabularInline):
    from apps.finans.models import CuzdanHareketi

    model = CuzdanHareketi
    extra = 0
    fields = ("tarih", "tip", "tutar", "onceki_bakiye", "sonraki_bakiye", "aciklama")
    readonly_fields = fields
    ordering = ("-tarih",)
    can_delete = False
    verbose_name_plural = "Bu Başvurunun Para Hareketleri"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BasvuruDurumu)
class BasvuruDurumuAdmin(ModelAdmin):
    list_display = (
        "ad",
        "rozet",
        "baslangic_durumu",
        "hakedis_tetikler",
        "olumsuz_sonuc",
        "bayi_duzenleyebilir",
        "sinyal_seviyesi",
        "sira",
        "aktif",
    )
    list_editable = ("sira", "aktif")
    prepopulated_fields = {"slug": ("ad",)}
    search_fields = ("ad",)
    fieldsets = (
        ("Tanım", {"fields": ("ad", "slug", "aciklama")}),
        (
            "Davranış",
            {
                "fields": (
                    "baslangic_durumu",
                    "hakedis_tetikler",
                    "olumsuz_sonuc",
                    "bayi_duzenleyebilir",
                ),
                "description": (
                    "“Para Hareketini Tetikler” işaretli duruma geçildiğinde ücret "
                    "kuralları çalışır. “Olumsuz Sonuç” işaretliyse işlenmiş para geri alınır."
                ),
            },
        ),
        ("Görünüm", {"fields": ("renk", "ikon", "sinyal_seviyesi", "sira", "aktif")}),
    )

    @admin.display(description="Rozet")
    def rozet(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            obj.renk,
            obj.ad,
        )


@admin.register(Basvuru)
class BasvuruAdmin(ModelAdmin):
    list_display = (
        "referans_no",
        "ad_soyad",
        "kategori",
        "operator",
        "bayi",
        "durum_rozeti",
        "tutar_ozeti",
        "olusturma_tarihi",
    )
    list_filter = (
        "durum",
        "kategori",
        "operator",
        "musteri_tipi",
        "para_islendi",
        "olusturma_tarihi",
    )
    search_fields = (
        "referans_no",
        "isim",
        "soyisim",
        "kimlik_no",
        "numara",
        "irtibat",
        "bayi__username",
    )
    autocomplete_fields = ("bayi", "kategori", "operator", "tarife", "kampanya", "durum")
    readonly_fields = (
        "referans_no",
        "tahsil_edilen",
        "hakedis",
        "para_islendi",
        "olusturma_tarihi",
        "guncelleme_tarihi",
        "ek_bilgiler_tablosu",
    )
    inlines = [BasvuruBelgesiInline, CuzdanHareketiInline, DurumGecmisiInline]
    date_hierarchy = "olusturma_tarihi"
    list_per_page = 50
    fieldsets = (
        (
            "Başvuru",
            {"fields": ("referans_no", "bayi", "kategori", "operator", "tarife", "kampanya")},
        ),
        (
            "Müşteri Bilgileri",
            {
                "fields": (
                    "musteri_tipi",
                    "kimlik_tipi",
                    "kimlik_no",
                    ("isim", "soyisim"),
                    "irtibat",
                    "numara",
                    "adres",
                )
            },
        ),
        ("Kategoriye Özel Alanlar", {"fields": ("ek_bilgiler_tablosu",)}),
        ("Durum", {"fields": ("durum", "bayi_aciklamasi", "operasyon_notu")}),
        (
            "Para",
            {
                "fields": ("tahsil_edilen", "hakedis", "para_islendi", "sonuclanma_tarihi"),
                "description": (
                    "Bu alanlar ücret kuralları tarafından otomatik doldurulur, elle değiştirilmez."
                ),
            },
        ),
        (
            "Kayıt",
            {"classes": ("collapse",), "fields": ("olusturma_tarihi", "guncelleme_tarihi")},
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("bayi", "kategori", "operator", "tarife", "durum")
        )

    @display(description="Durum")
    def durum_rozeti(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600;white-space:nowrap">{}</span>',
            obj.durum.renk,
            obj.durum.ad,
        )

    @display(description="Tahsilat / Hakediş")
    def tutar_ozeti(self, obj):
        if not obj.para_islendi:
            return format_html('<span style="color:#94a3b8">işlenmedi</span>')
        return format_html(
            '<span style="color:#dc2626">-{}</span> / <span style="color:#16a34a">+{}</span>',
            obj.tahsil_edilen,
            obj.hakedis,
        )

    @admin.display(description="Kategoriye özel alanlar")
    def ek_bilgiler_tablosu(self, obj):
        if not obj.ek_bilgiler:
            return "—"
        etiketler = {
            alan.kod: alan.etiket for alan in obj.kategori.alanlar.all()
        }
        satirlar = "".join(
            format_html(
                "<tr><th style='text-align:left;padding:.35rem .75rem .35rem 0;"
                "font-weight:600;white-space:nowrap'>{}</th>"
                "<td style='padding:.35rem 0'>{}</td></tr>",
                etiketler.get(kod, kod),
                deger if deger not in (None, "") else "—",
            )
            for kod, deger in obj.ek_bilgiler.items()
        )
        return format_html("<table>{}</table>", satirlar)

    def save_model(self, request, obj, form, change):
        """Bakiye yetersizse durum değişikliğini reddedip anlaşılır mesaj göster."""
        try:
            super().save_model(request, obj, form, change)
        except YetersizBakiye as hata:
            messages.error(request, f"Durum değiştirilemedi: {hata}")
            raise

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for nesne in instances:
            if isinstance(nesne, DurumGecmisi) and not nesne.degistiren_id:
                nesne.degistiren = request.user
            nesne.save()
        for nesne in formset.deleted_objects:
            nesne.delete()
        formset.save_m2m()
