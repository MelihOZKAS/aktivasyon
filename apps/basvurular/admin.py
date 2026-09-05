from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action as unfold_islem
from unfold.decorators import display

from apps.basvurular.detay_alanlari import (
    admin_gizli_alanlar,
    fieldset_alanlari,
    fieldsetleri_suz,
)
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


class BasvuruAdminFormu(forms.ModelForm):
    """Görünümden kapatılan alana yazılan hata formu çökertmesin.

    Model doğrulaması hatayı alan adıyla veriyor (`{"tarife": ...}`).
    Kullanıcı o alanı kapattıysa alan formda yok ve Django `add_error`
    çağrısında `ValueError` atıyor — kayıt hiç kaydedilemez hâle geliyordu.
    Karşılığı olmayan hata, alan adıyla birlikte genel hataya düşer.
    """

    class Meta:
        model = Basvuru
        fields = "__all__"

    def _update_errors(self, errors):
        # Model doğrulamasından gelen hatalar buradan geçiyor; Django alanı
        # formda bulamazsa `add_error`a hiç varmadan ValueError atıyor.
        if hasattr(errors, "error_dict"):
            errors = ValidationError(self._hatalari_yerlestir(errors.error_dict))
        super()._update_errors(errors)

    def _hatalari_yerlestir(self, hata_sozlugu):
        """Formda karşılığı olmayan hatayı genel hataya taşır."""
        yerinde = {}
        genel = []
        for alan, hatalar in hata_sozlugu.items():
            if alan == NON_FIELD_ERRORS or alan in self.fields:
                yerinde.setdefault(alan, []).extend(hatalar)
                continue
            for hata in hatalar:
                genel.extend(f"{alan}: {mesaj}" for mesaj in hata.messages)

        if genel:
            yerinde.setdefault(NON_FIELD_ERRORS, []).append(ValidationError(genel))
        return yerinde

    def add_error(self, field, error):
        if field is not None and field not in self.fields:
            mesajlar = getattr(error, "messages", None) or [str(error)]
            error = ValidationError([f"{field}: {mesaj}" for mesaj in mesajlar])
            field = None
        super().add_error(field, error)


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
    form = BasvuruAdminFormu
    actions_detail = ["gorunum_ayarla"]
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
                    "giris_bedeli", "tahsil_edilen", "hakedis", "para_islendi",
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

    def get_fieldsets(self, request, obj=None):
        """Kullanıcının kapattığı alanlar çizilmez.

        Başvuru detayı uzun; herkes hepsiyle ilgilenmiyor. Kapatmak yalnızca
        görünümü etkiler — alan formdan çıktığı için değeri olduğu gibi
        kalır, kaydetmek onu bozmaz.

        Ekleme ekranında süzme yapılmaz: yeni kayıt açarken zorunlu bir alan
        gizli kalırsa kayıt hiç açılamaz.
        """
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        return fieldsetleri_suz(fieldsets, admin_gizli_alanlar(request.user))

    @unfold_islem(
        description="Görünüm",
        url_path="gorunum",
        permissions=["change"],
        icon="tune",
    )
    def gorunum_ayarla(self, request, object_id):
        """Bu ekranda hangi alanların görüneceğini kullanıcı kendisi seçer."""
        from apps.bayi.models import DetayGorunumTercihi

        basvuru = self.get_object(request, object_id)
        if basvuru is None:
            raise Http404("Başvuru bulunamadı.")

        # Süzülmemiş liste: kapatılan alan da kutuda dursun, geri açılabilsin.
        tumu = fieldset_alanlari(super().get_fieldsets(request, basvuru))
        etiketler = self._alan_etiketleri(request, basvuru, tumu)

        if request.method == "POST":
            acik = set(request.POST.getlist("alan"))
            tercih, _ = DetayGorunumTercihi.objects.get_or_create(kullanici=request.user)
            tercih.admin_gizli_alanlar = [a for a in tumu if a not in acik]
            tercih.save(update_fields=["admin_gizli_alanlar", "guncelleme_tarihi"])
            self.message_user(request, "Görünüm ayarların kaydedildi.", messages.SUCCESS)
            return redirect("admin:basvurular_basvuru_change", basvuru.pk)

        gizli = admin_gizli_alanlar(request.user)
        return render(
            request,
            "admin/basvurular/gorunum.html",
            {
                **self.admin_site.each_context(request),
                "title": "Neler görünsün?",
                "opts": self.model._meta,
                "basvuru": basvuru,
                "satirlar": [
                    {"ad": ad, "etiket": etiketler.get(ad, ad), "acik": ad not in gizli}
                    for ad in tumu
                ],
                "geri_adresi": reverse(
                    "admin:basvurular_basvuru_change", args=[basvuru.pk]
                ),
            },
        )

    def _alan_etiketleri(self, request, obj, adlar):
        """Alan adlarını ekranda görünen başlıklarına çevirir."""
        etiketler = {}
        for ad in adlar:
            try:
                etiketler[ad] = self.model._meta.get_field(ad).verbose_name
            except Exception:
                # Hesaplanan alanlar (kar_ozeti gibi) modelde yok; admin
                # metodunun kendi başlığını kullan.
                metot = getattr(self, ad, None)
                etiketler[ad] = getattr(metot, "short_description", ad)
        return etiketler

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
                Tarife.objects.filter(kategoriler=kategori_id, aktif=True)
                .select_related("operator")
                .order_by("operator__ad", "sira", "ad")
            )
        elif db_field.name == "kampanya" and kategori_id:
            kwargs["queryset"] = (
                Kampanya.objects.filter(tarife__kategoriler=kategori_id, aktif=True)
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
        if not (obj.para_islendi or obj.giris_bedeli_islendi):
            return format_html('<span style="color:#94a3b8">işlenmedi</span>')
        # Giriş bedeli de bayiden çıkan paradır; kesinti hanesinde toplanır.
        return format_html(
            '<span style="color:#D42046">-{}</span> / <span style="color:#0F8A4D">+{}</span>',
            obj.giris_bedeli + obj.tahsil_edilen,
            obj.hakedis,
        )

    @display(description="Kâr", ordering="ana_hakedis")
    def kar_gosterimi(self, obj):
        """Tedarikçiden aldığımız + bayiden kestiğimiz − bayiye ödediğimiz."""
        if not (obj.para_islendi or obj.ana_hakedis_islendi or obj.giris_bedeli_islendi):
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
            ("Giriş bedeli (başvuru girilirken)", obj.giris_bedeli, "#0F8A4D"),
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
