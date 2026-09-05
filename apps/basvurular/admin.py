from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.db.models import Sum
from django.shortcuts import render
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from apps.basvurular.raporlar import sim_alacaklari
from apps.katalog.models import Kampanya, Tarife
from apps.basvurular.models import (
    Basvuru,
    BasvuruBelgesi,
    BasvuruDurumu,
    DurumGecmisi,
)


class BasvuruBelgesiInline(TabularInline):
    model = BasvuruBelgesi
    extra = 0
    fields = ("etiket", "alan_kodu", "dosya", "onizleme", "yuklenme_tarihi")
    readonly_fields = ("onizleme", "yuklenme_tarihi")

    @admin.display(description="Önizleme")
    def onizleme(self, obj):
        """Kişisel veri olduğu için önizleme de izin kontrollü yoldan geçer."""
        if not obj.dosya or not obj.pk:
            return "—"
        url = obj.get_absolute_url()
        if obj.resim_mi:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">'
                '<img src="{}" style="max-height:64px;border-radius:.375rem"></a>',
                url,
                url,
            )
        return format_html('<a href="{}" target="_blank" rel="noopener">Dosyayı aç</a>', url)


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
        "bildirim_gonder",
        "belgeleri_sil",
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
                    "bildirim_gonder",
                    "belgeleri_sil",
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


class TedarikciAtamaFormu(forms.Form):
    """Seçili işlemleri bir tedarikçiye satmak için."""

    tedarikci = forms.ModelChoiceField(
        label="Hangi tedarikçiye satılsın?",
        queryset=User.objects.filter(
            is_active=True, bayi_profili__tedarikci_mi=True
        ).order_by("username"),
        help_text="Yalnızca tedarikçi rolü açık hesaplar listelenir.",
    )


@admin.register(Basvuru)
class BasvuruAdmin(ModelAdmin):
    list_display = (
        "referans_no",
        "ad_soyad",
        "kategori",
        "bayi",
        "tedarikci",
        "durum_rozeti",
        "tutar_ozeti",
        "kar_gosterimi",
        "sim_karsiligi_rozeti",
        "olusturma_tarihi",
    )
    list_filter = (
        "durum",
        "kategori",
        "operator",
        "tedarikci",
        "musteri_tipi",
        "para_islendi",
        "ana_hakedis_islendi",
        "sim_karsiligi_alindi",
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
    # tarife/kampanya bilinçli olarak autocomplete değil: autocomplete
    # kutusu bağlı olduğu admin'in tüm kayıtlarını gösterir ve kategoriye
    # göre daraltılamaz. Düz seçim kutusu kategoriye göre filtreleniyor.
    autocomplete_fields = ("bayi", "tedarikci", "kategori", "operator", "durum")
    readonly_fields = (
        "referans_no",
        "tahsil_edilen",
        "hakedis",
        "ana_hakedis",
        "para_islendi",
        "ana_hakedis_islendi",
        "belgeler_silindi",
        "sim_karsiligi_tarihi",
        "kar_ozeti",
        "olusturma_tarihi",
        "guncelleme_tarihi",
        "ek_bilgiler_tablosu",
    )
    inlines = [BasvuruBelgesiInline, CuzdanHareketiInline, DurumGecmisiInline]
    date_hierarchy = "olusturma_tarihi"
    list_per_page = 50
    actions = (
        "tedarikciye_ata",
        "tedarikci_atamasini_kaldir",
        "sim_karsiligi_alindi_isaretle",
        "sim_karsiligi_geri_al",
    )
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
            "SIM karşılığı",
            {
                "fields": ("sim_karsiligi_alindi", "sim_karsiligi_tarihi"),
                "description": (
                    "Bu aktivasyonun tükettiği SIM'in yenisi operatörden "
                    "alındığında işaretleyin. Yalnızca kategorisinde “SIM "
                    "Karşılığı Takip Edilsin” açık olan işlemlerde anlamlıdır."
                ),
            },
        ),
        (
            "Ana hakediş",
            {
                "fields": ("tedarikci", "ana_hakedis", "ana_hakedis_islendi"),
                "description": (
                    "Ana hakediş operatörden ya da işlemi üstlenen tedarikçiden "
                    "gelir. Tedarikçi atanmışsa tutar onun hesabından düşer; "
                    "atanmamışsa operatörden alınır ve yalnızca kâr hesabına yazılır."
                ),
            },
        ),
        (
            "Para",
            {
                "fields": (
                    "tahsil_edilen", "hakedis", "para_islendi",
                    "kar_ozeti", "sonuclanma_tarihi",
                ),
                "description": (
                    "Bu alanlar ücret kuralları tarafından otomatik doldurulur, elle değiştirilmez."
                ),
            },
        ),
        (
            "Kayıt",
            {
                "classes": ("collapse",),
                "fields": ("olusturma_tarihi", "guncelleme_tarihi", "belgeler_silindi"),
                "description": (
                    "Kimlik görüntüleri kişisel veridir; “Belgeleri Sil” işaretli "
                    "bir duruma geçildiğinde hemen silinir. Başvuru kaydı ve "
                    "para geçmişi kalır."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("bayi", "tedarikci", "kategori", "operator", "tarife", "durum")
        )

    def get_form(self, request, obj=None, **kwargs):
        """Düzenlenen başvurunun kategorisini forma taşır."""
        form = super().get_form(request, obj, **kwargs)
        form._duzenlenen_kategori_id = obj.kategori_id if obj else None
        return form

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Tarife ve kampanya seçeneklerini başvurunun kategorisiyle sınırlar.

        Kutu tüm tarifeleri gösterdiği için başka kategorinin tarifesi
        seçilip kaydetmede reddediliyordu; artık yanlış seçenek hiç
        listelenmiyor.
        """
        kategori_id = getattr(self, "_duzenlenen_kategori_id", None)

        if db_field.name == "tarife" and kategori_id:
            kwargs["queryset"] = (
                Tarife.objects.filter(kategori_id=kategori_id, aktif=True)
                .select_related("operator")
                .order_by("operator__ad", "sira", "ad")
            )
        elif db_field.name == "kampanya" and kategori_id:
            kwargs["queryset"] = (
                Kampanya.objects.filter(tarife__kategori_id=kategori_id, aktif=True)
                .select_related("tarife")
                .order_by("tarife__ad", "sira", "ad")
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_object(self, request, object_id, from_field=None):
        nesne = super().get_object(request, object_id, from_field)
        # formfield_for_foreignkey nesneyi görmediği için kategoriyi burada saklıyoruz.
        self._duzenlenen_kategori_id = nesne.kategori_id if nesne else None
        return nesne

    def add_view(self, request, form_url="", extra_context=None):
        self._duzenlenen_kategori_id = None
        return super().add_view(request, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        """Listenin üstünde, uygulanan filtreye göre kâr özeti gösterir."""
        yanit = super().changelist_view(request, extra_context)

        try:
            sorgu = yanit.context_data["cl"].queryset
        except (AttributeError, KeyError):
            return yanit

        toplam = sorgu.aggregate(
            gelir=Sum("ana_hakedis"),
            kesinti=Sum("tahsil_edilen"),
            odenen=Sum("hakedis"),
        )
        gelir = toplam["gelir"] or Decimal("0")
        kesinti = toplam["kesinti"] or Decimal("0")
        odenen = toplam["odenen"] or Decimal("0")

        yanit.context_data["kar_ozeti"] = {
            "ana_hakedis": gelir,
            "tahsilat": kesinti,
            "hakedis": odenen,
            "kar": gelir + kesinti - odenen,
        }
        # Kimden kaç SIM kart alacağımız: tedarikçiye satılmışsa ondan,
        # değilse operatörden.
        yanit.context_data["sim_alacaklari"] = sim_alacaklari(sorgu)
        return yanit

    @display(description="Durum")
    def durum_rozeti(self, obj):
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600;white-space:nowrap">{}</span>',
            obj.durum.renk,
            obj.durum.ad,
        )

    @display(description="Bayi (kesinti / hakediş)")
    def tutar_ozeti(self, obj):
        if not obj.para_islendi:
            return format_html('<span style="color:#94a3b8">işlenmedi</span>')
        return format_html(
            '<span style="color:#D42046">-{}</span> / <span style="color:#0F8A4D">+{}</span>',
            obj.tahsil_edilen,
            obj.hakedis,
        )

    @display(description="Kâr", ordering="ana_hakedis")
    def kar_gosterimi(self, obj):
        """Tedarikçiden aldığımız + bayiden kestiğimiz − bayiye ödediğimiz."""
        if not (obj.para_islendi or obj.ana_hakedis_islendi):
            return format_html('<span style="color:#94a3b8">—</span>')
        kar = obj.kar
        renk = "#0F8A4D" if kar > 0 else ("#D42046" if kar < 0 else "#6F7B8F")
        return format_html('<b style="color:{}">{} ₺</b>', renk, kar)

    @admin.display(description="Kâr hesabı")
    def kar_ozeti(self, obj):
        if not obj.pk:
            return "—"
        satirlar = [
            (f"Ana hakediş ({obj.ana_hakedis_kaynagi})", obj.ana_hakedis, "#0F8A4D"),
            ("Bayiden kesilen", obj.tahsil_edilen, "#0F8A4D"),
            ("Bayiye ödenen", -obj.hakedis, "#D42046"),
        ]
        # format_html_join gerekli: "".join(...) düz str döndürür ve dıştaki
        # format_html onu kaçışlayıp HTML'i metin olarak basar.
        govde = format_html_join(
            "",
            "<tr><td style='padding:.2rem 1rem .2rem 0'>{}</td>"
            "<td style='text-align:right;color:{};font-weight:600'>{} ₺</td></tr>",
            ((etiket, renk, tutar) for etiket, tutar, renk in satirlar),
        )
        kar = obj.kar
        renk = "#0F8A4D" if kar > 0 else ("#D42046" if kar < 0 else "#6F7B8F")
        return format_html(
            "<table style='font-size:.9rem'>{}"
            "<tr><td style='padding-top:.4rem;border-top:1px solid rgba(0,0,0,.15)'>"
            "<b>Kâr</b></td>"
            "<td style='text-align:right;padding-top:.4rem;"
            "border-top:1px solid rgba(0,0,0,.15);color:{}'><b>{} ₺</b></td></tr></table>",
            govde, renk, kar,
        )

    @admin.display(description="Kategoriye özel alanlar")
    def ek_bilgiler_tablosu(self, obj):
        if not obj.ek_bilgiler:
            return "—"
        etiketler = {
            alan.kod: alan.etiket for alan in obj.kategori.alanlar.all()
        }
        satirlar = format_html_join(
            "",
            "<tr><th style='text-align:left;padding:.35rem .75rem .35rem 0;"
            "font-weight:600;white-space:nowrap'>{}</th>"
            "<td style='padding:.35rem 0'>{}</td></tr>",
            (
                (etiketler.get(kod, kod), deger if deger not in (None, "") else "—")
                for kod, deger in obj.ek_bilgiler.items()
            ),
        )
        return format_html("<table>{}</table>", satirlar)

    @display(description="SIM karşılığı")
    def sim_karsiligi_rozeti(self, obj):
        if not obj.kategori.sim_karsiligi_gerekir:
            return format_html('<span style="color:#9AA5B7">—</span>')
        if obj.sim_karsiligi_alindi:
            return format_html('<span style="color:#0F8A4D;font-weight:600">alındı</span>')
        if obj.durum.hakedis_tetikler:
            return format_html(
                '<span style="color:#B45309;font-weight:600">bekliyor</span>'
                '<br><span style="color:#6F7B8F;font-size:.72rem">{}</span>',
                obj.sim_karsiligi_kimden,
            )
        return format_html('<span style="color:#9AA5B7">—</span>')

    @admin.action(description="SIM karşılığı alındı olarak işaretle")
    def sim_karsiligi_alindi_isaretle(self, request, secilenler):
        """Operatörden yeni kartlar geldiğinde toplu işaretlemek için."""
        adet = 0
        for basvuru in secilenler.filter(sim_karsiligi_alindi=False):
            basvuru.sim_karsiligi_alindi = True
            basvuru.save(update_fields=["sim_karsiligi_alindi", "sim_karsiligi_tarihi"])
            adet += 1
        self.message_user(
            request,
            f"{adet} işlemin SIM karşılığı alındı olarak işaretlendi.",
            messages.SUCCESS if adet else messages.WARNING,
        )

    @admin.action(description="SIM karşılığı işaretini geri al")
    def sim_karsiligi_geri_al(self, request, secilenler):
        adet = 0
        for basvuru in secilenler.filter(sim_karsiligi_alindi=True):
            basvuru.sim_karsiligi_alindi = False
            basvuru.save(update_fields=["sim_karsiligi_alindi", "sim_karsiligi_tarihi"])
            adet += 1
        self.message_user(request, f"{adet} işlemin işareti geri alındı.", messages.SUCCESS)

    @admin.action(description="Seçili işlemleri bir tedarikçiye sat")
    def tedarikciye_ata(self, request, secilenler):
        """Birden çok işlemi tek seferde tedarikçiye atar.

        Zaten aktif olan işlemlerde bedel atama anında tedarikçinin
        hesabından düşer.
        """
        if "uygula" in request.POST:
            form = TedarikciAtamaFormu(request.POST)
            if form.is_valid():
                tedarikci = form.cleaned_data["tedarikci"]
                atanan = atlanan = 0
                for basvuru in secilenler:
                    if basvuru.ana_hakedis_islendi:
                        atlanan += 1
                        continue
                    basvuru.tedarikci = tedarikci
                    # save() sinyali tetikler: aktifse bedel hemen işlenir.
                    basvuru.save()
                    atanan += 1

                self.message_user(
                    request,
                    f"{atanan} işlem {tedarikci.get_username()} hesabına satıldı"
                    + (f", {atlanan} tanesi zaten işlenmişti." if atlanan else "."),
                    messages.SUCCESS,
                )
                return None
        else:
            form = TedarikciAtamaFormu()

        return render(
            request,
            "admin/basvurular/tedarikci_ata.html",
            {
                **self.admin_site.each_context(request),
                "title": "İşlemleri tedarikçiye sat",
                "form": form,
                "basvurular": secilenler,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Tedarikçi atamasını kaldır (bedeli işlenmemişse)")
    def tedarikci_atamasini_kaldir(self, request, secilenler):
        kaldirilan = secilenler.filter(ana_hakedis_islendi=False).update(tedarikci=None)
        atlanan = secilenler.count() - kaldirilan
        self.message_user(
            request,
            f"{kaldirilan} işlemin tedarikçisi kaldırıldı"
            + (f", {atlanan} tanesinde bedel işlendiği için dokunulmadı." if atlanan else "."),
            messages.SUCCESS if kaldirilan else messages.WARNING,
        )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for nesne in instances:
            if isinstance(nesne, DurumGecmisi) and not nesne.degistiren_id:
                nesne.degistiren = request.user
            nesne.save()
        for nesne in formset.deleted_objects:
            nesne.delete()
        formset.save_m2m()
