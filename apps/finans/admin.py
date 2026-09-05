from decimal import Decimal
from uuid import uuid4

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from django.http import Http404
from unfold.decorators import action, display
from unfold.decorators import action as unfold_islem
from unfold.widgets import (
    UnfoldAdminDecimalFieldWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextInputWidget,
)

from apps.finans.models import (
    Banka,
    BayiGrubu,
    Cuzdan,
    CuzdanHareketi,
    CuzdanIslemi,
    KuralYonu,
    OdemeBildirimi,
    OdemeBildirimiDurumu,
    OperatorAlisi,
    TedarikciAlisi,
    UcretKurali,
)
from unfold.contrib.filters.admin import AutocompleteSelectFilter

from apps.filtreler import GunAraligiFiltresi
from apps.finans.services import (
    cuzdan_islemi,
    odeme_bildirimini_onayla,
    odeme_bildirimini_reddet,
)

SIFIR = Decimal("0.00")


def _kullanici_kutusunu_sadelestir(alan):
    """Kullanıcı seçtiren kutuda ekle/düzenle/sil düğmelerini kapatır.

    Kutunun yanındaki kırmızı çöp kutusu seçimi değil, seçili kullanıcının
    kendisini siler; yanlış kişi seçilince ilk refleks ona basmak oluyor.
    """
    for ozellik in ("can_add_related", "can_change_related", "can_delete_related"):
        if hasattr(alan.widget, ozellik):
            setattr(alan.widget, ozellik, False)
    return alan



class TarifeParaKuraliInline(TabularInline):
    """Tarifenin parası tarifenin sayfasında girilir.

    Kural motoru genel: kampanyaya, bayi grubuna, tek bayiye, tarih aralığına
    göre kural yazılabiliyor. Ama günlük iş bu değil — günlük iş "bu tarifede
    bayiye ne veriyorum, ben ne alıyorum" sorusu. O iki rakamı ayrı bir ekranda,
    kapsam alanlarını doldurarak aramak gereksiz; tarifeyi açan burada görür ve
    girer. Kayıtlar yine `UcretKurali` — motor tek kaynaktan okumaya devam eder.
    """

    model = UcretKurali
    fk_name = "tarife"
    extra = 0
    verbose_name = "Para kuralı"
    verbose_name_plural = "Bu tarifenin parası"
    fields = ("yon", "tutar", "tedarikci", "bayi_grubu", "tetikleyici_durum", "aktif")
    autocomplete_fields = ("bayi_grubu", "tedarikci")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        alan = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if alan is None:
            return alan

        # Para hemen her zaman "Aktif"te işler; yönetici her satırda aynı
        # durumu tekrar seçmesin.
        if db_field.name == "tetikleyici_durum":
            from apps.basvurular.models import BasvuruDurumu

            varsayilan = BasvuruDurumu.objects.filter(hakedis_tetikler=True).first()
            if varsayilan:
                alan.initial = varsayilan.pk

        # Kullanıcı seçtiren kutuların yanındaki çöp kutusu seçimi değil,
        # seçili kullanıcının kendisini siler.
        if db_field.name == "tedarikci":
            _kullanici_kutusunu_sadelestir(alan)
        return alan


@admin.register(BayiGrubu)
class BayiGrubuAdmin(ModelAdmin):
    list_display = ("ad", "bayi_sayisi", "aktif")
    search_fields = ("ad",)
    list_filter = ("aktif",)

    @admin.display(description="Bayi Sayısı")
    def bayi_sayisi(self, obj):
        return obj.cuzdanlar.count()


class CuzdanIslemFormu(forms.Form):
    """Yöneticinin cüzdana elle yaptığı işlem."""

    tip = forms.ChoiceField(
        label="İşlem",
        choices=CuzdanIslemi.choices,
        initial=CuzdanIslemi.TAHSILAT,
        # Şablonda kart olarak elle çizilir; unfold'un varsayılan radyosu
        # üç seçeneği de tek satıra diziyor ve hangisinin ne yaptığı
        # okunmuyordu.
        widget=forms.RadioSelect,
    )
    # Girdiler unfold'un kendi bileşenlerini kullanır: yönetim panelinde
    # bizim static/app.css yüklü değil, sınıf uydurulamaz.
    tutar = forms.DecimalField(
        label="Tutar",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=UnfoldAdminDecimalFieldWidget(attrs={"placeholder": "0,00"}),
    )
    banka = forms.ModelChoiceField(
        label="Banka",
        queryset=Banka.objects.filter(aktif=True),
        required=False,
        help_text="Tahsilatta paranın girdiği hesap. Bankanın bakiyesi de artar.",
        widget=UnfoldAdminSelectWidget,
    )
    aciklama = forms.CharField(
        label="Açıklama",
        max_length=255,
        required=False,
        widget=UnfoldAdminTextInputWidget(
            attrs={"placeholder": "Defterde bu hareketin yanında görünür"}
        ),
    )
    # Sayfa yenilenince aynı işlem ikinci kez yazılmasın: anahtar formda
    # taşınır, defter aynı anahtarı ikinci kez kabul etmez.
    islem_anahtari = forms.CharField(widget=forms.HiddenInput)

    # Bankalı işlemler: para fiilen bir hesaba giriyor ya da oradan çıkıyor.
    BANKALI = {CuzdanIslemi.TAHSILAT, CuzdanIslemi.IADE}

    def __init__(self, *args, cuzdan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cuzdan = cuzdan

    def clean(self):
        temiz = super().clean()
        tip = temiz.get("tip")

        # Banka yalnızca para giren/çıkan işlemlerde anlamlı: kredide ve borç
        # artırımında kasaya dokunulmuyor, yazılan hesap yanıltıcı olurdu.
        # Kutu zaten gizleniyor ama kural sunucuda da durur.
        if tip not in self.BANKALI:
            temiz["banka"] = None
        elif tip == CuzdanIslemi.IADE and not temiz.get("banka"):
            self.add_error("banka", "İade havalenin çıktığı hesaptan düşer; banka seçin.")

        tutar = temiz.get("tutar")
        if (
            tip == CuzdanIslemi.IADE
            and tutar
            and self.cuzdan
            and tutar > self.cuzdan.bakiye
        ):
            self.add_error(
                "tutar",
                f"Bakiyesi {self.cuzdan.bakiye} ₺; bundan fazlası düşürülemez.",
            )
        return temiz


@admin.register(Cuzdan)
class CuzdanAdmin(ModelAdmin):
    list_display = (
        "bayi",
        "grup",
        "bakiye_gosterimi",
        "borc_gosterimi",
        "islem_yapabilir",
        "bakiye_yukle_baglantisi",
    )
    list_filter = ("grup", "islem_yapabilir")
    search_fields = ("bayi__username", "bayi__first_name", "bayi__last_name")
    autocomplete_fields = ("bayi", "grup")
    readonly_fields = ("bakiye", "borc")
    fieldsets = (
        ("Bayi", {"fields": ("bayi", "grup", "islem_yapabilir")}),
        (
            "Durum",
            {
                "fields": ("bakiye", "borc"),
                "description": (
                    "Bakiye ve borç elle değiştirilemez; “Bakiye Yükle” ile işlem yapın. "
                    "Borç için üst sınır yoktur: bakiye yetmediğinde kalan tutar borca "
                    "yazılır. Bayiyi tamamen durdurmak için “İşlem Yapabilir”i kapatın."
                ),
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
        """Cüzdana elle işlem: kredi, borç ya da tahsilat.

        Üçü de para ekler; farkları paranın hangi haneye yazıldığı.
        Tahsilat borcu varsa önce onu kapatır. Kimin yaptığı defterde durur.
        """
        cuzdan = self.get_object(request, cuzdan_id)
        if cuzdan is None:
            messages.error(request, "Cüzdan bulunamadı.")
            return redirect("admin:finans_cuzdan_changelist")

        if request.method == "POST":
            form = CuzdanIslemFormu(request.POST, cuzdan=cuzdan)
            if form.is_valid():
                tutar = form.cleaned_data["tutar"]
                tip = form.cleaned_data["tip"]
                cuzdan_islemi(
                    cuzdan,
                    tip,
                    tutar,
                    aciklama=form.cleaned_data["aciklama"],
                    banka=form.cleaned_data["banka"],
                    olusturan=request.user,
                    anahtar=f"admin:{form.cleaned_data['islem_anahtari']}",
                )
                cuzdan.refresh_from_db()
                messages.success(
                    request,
                    f"{cuzdan.bayi.get_username()}: {dict(CuzdanIslemi.choices)[tip]} "
                    f"· {tutar} ₺ işlendi. Yeni bakiye {cuzdan.bakiye} ₺, "
                    f"borç {cuzdan.borc} ₺.",
                )
                return redirect("admin:finans_cuzdan_change", cuzdan.pk)
        else:
            form = CuzdanIslemFormu(
                cuzdan=cuzdan, initial={"islem_anahtari": uuid4().hex}
            )

        baglam = {
            **self.admin_site.each_context(request),
            "title": f"Cüzdan işlemi · {cuzdan.bayi.get_username()}",
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
            "Bakiye / borç</a>",
            url,
        )


@admin.register(CuzdanHareketi)
class CuzdanHareketiAdmin(ModelAdmin):
    list_display = (
        "tarih",
        "bayi_gosterimi",
        "tip",
        "tutar_gosterimi",
        "bakiye_akisi",
        "borc_akisi",
        "kaynak",
        "olusturan",
        "aciklama",
    )
    # Tarih aralığı: yönetici "1–5 Eylül arasında bu bayiye ne işlendi"
    # sorusuna tek ekranda bakabilsin.
    #
    # Bayi filtresi aramalı: numarasını kimse ezbere bilmiyor, ünvanından
    # aranır. "İşlemi Yapan" ise yalnızca defterde gerçekten geçen
    # kullanıcıları listeler — elle işlem yapan personel birkaç kişidir,
    # bütün bayileri sıralamak listeyi kullanılmaz hâle getiriyordu.
    list_filter = (
        "tip",
        ("tarih", GunAraligiFiltresi),
        ("cuzdan__bayi", AutocompleteSelectFilter),
        "cuzdan__grup",
        ("olusturan", admin.RelatedOnlyFieldListFilter),
    )
    list_filter_submit = True
    search_fields = (
        "cuzdan__bayi__username",
        "cuzdan__bayi__bayi_profili__unvan",
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

    @display(description="Bakiye", ordering="sonraki_bakiye")
    def bakiye_akisi(self, obj):
        """Hareketten önceki ve sonraki bakiye.

        Yalnızca sonrasını göstermek "bu rakam nereden çıktı" sorusunu
        cevapsız bırakıyordu; bayi de yönetici de aramak zorunda kalıyordu.
        """
        return format_html(
            "<span style='color:#6F7B8F'>{}</span> → <b>{} ₺</b>",
            obj.onceki_bakiye,
            obj.sonraki_bakiye,
        )

    @display(description="Borç", ordering="sonraki_borc")
    def borc_akisi(self, obj):
        # Borç hiç değişmediyse sıfır kalabalığı yapmasın.
        if not obj.onceki_borc and not obj.sonraki_borc:
            return format_html("<span style='color:#94a3b8'>—</span>")
        return format_html(
            "<span style='color:#6F7B8F'>{}</span> → <b style='color:#D42046'>{} ₺</b>",
            obj.onceki_borc,
            obj.sonraki_borc,
        )

    @display(description="Bayi", ordering="cuzdan__bayi__username")
    def bayi_gosterimi(self, obj):
        """Numara tek başına hangi firma olduğunu anlatmıyor; ünvanı da yaz."""
        bayi = obj.cuzdan.bayi
        profil = getattr(bayi, "bayi_profili", None)
        unvan = profil.unvan if profil and profil.unvan else ""
        if not unvan:
            return bayi.get_username()
        return format_html(
            "{}<br><span style='color:#6F7B8F;font-size:.8125rem'>{}</span>",
            bayi.get_username(),
            unvan,
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
        "tedarikci",
        "tetikleyici_durum",
    )
    readonly_fields = ("kar_tablosu",)
    fieldsets = (
        ("Kural", {"fields": ("ad", "yon", "tutar", "tetikleyici_durum")}),
        (
            "Bu kapsamın hesabı",
            {
                "fields": ("kar_tablosu",),
                "description": (
                    "Bu kural tek bir yönü tutar. Aynı kapsamdaki diğer yönler "
                    "aşağıda listelenir; eksik olan varsa yazar."
                ),
            },
        ),
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
                    "tedarikci",
                ),
                "description": (
                    "Boş bırakılan her alan “hepsi” anlamına gelir. Bir başvuruya "
                    "birden fazla kural uyarsa en dar kapsamlı olan uygulanır; "
                    "eşitlik durumunda önceliği yüksek olan kazanır.<br>"
                    "<b>Alışım</b> kurallarında: tedarikçi boşsa tutar operatörden "
                    "gelir, tedarikçi seçiliyse o tedarikçinin hesabından düşer."
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
                "kategori", "operator", "tarife", "kampanya", "bayi_grubu",
                "bayi", "tedarikci", "tetikleyici_durum",
            )
        )

    @admin.display(description="Alışım, bayiye ödediğim ve kâr")
    def kar_tablosu(self, obj):
        """Aynı kapsamdaki üç yönü ve kârı tek yerde gösterir.

        Kural sayfası tek yön tutuyor: yönetici bayiye ödediğini girip
        "alışımı nereden gireceğim" diye soruyordu. Alış da aynı kapsamda
        ikinci bir kuraldır; burada okunur, eksikse söylenir. Girme yeri
        tarifenin kendi sayfasıdır — üçü orada yan yana durur.
        """
        if obj is None or obj.pk is None:
            return "Kural kaydedildikten sonra hesap burada görünür."

        kardesler = UcretKurali.objects.filter(
            aktif=True,
            kategori=obj.kategori,
            operator=obj.operator,
            tarife=obj.tarife,
            kampanya=obj.kampanya,
            bayi_grubu=obj.bayi_grubu,
            bayi=obj.bayi,
        )

        tutarlar = {}
        for kural in kardesler:
            # Aynı yönde birden çok kural varsa en yükseği yazmak yanıltıcı
            # olur; motorun seçtiği gibi en son eklenen kazanır.
            tutarlar[kural.yon] = kural.tutar

        alis = tutarlar.get(KuralYonu.ANA_HAKEDIS)
        odenen = tutarlar.get(KuralYonu.HAKEDIS)
        tahsil = tutarlar.get(KuralYonu.TAHSILAT)

        def hucre(deger):
            if deger is None:
                return format_html('<span style="color:#B45309">girilmedi</span>')
            return format_html("<b>{} ₺</b>", deger)

        satirlar = [
            ("Alışım (operatör ya da tedarikçiden)", hucre(alis)),
            ("Bayiden tahsilat", hucre(tahsil)),
            ("Bayiye ödediğim", hucre(odenen)),
        ]

        if alis is None and tahsil is None:
            kar_satiri = format_html(
                '<span style="color:#B45309">Alış girilmeden kâr hesaplanamaz.</span>'
            )
        else:
            kar = (alis or SIFIR) + (tahsil or SIFIR) - (odenen or SIFIR)
            kar_satiri = format_html(
                '<b style="color:{}">{} ₺</b>',
                "#0F8A4D" if kar >= SIFIR else "#D42046",
                kar,
            )
        satirlar.append(("Kâr", kar_satiri))

        govde = format_html_join(
            "",
            "<tr><td style='padding:.25rem 1.5rem .25rem 0'>{}</td><td>{}</td></tr>",
            satirlar,
        )
        tablo = format_html("<table style='font-size:.875rem'>{}</table>", govde)

        if obj.tarife_id:
            return format_html(
                '{}<p style="margin-top:.75rem;font-size:.8125rem;color:#6F7B8F">'
                'Üçünü aynı ekranda girmek için: '
                '<a href="{}" style="font-weight:600">{} · tarifenin parası</a></p>',
                tablo,
                reverse("admin:katalog_tarife_change", args=[obj.tarife_id]),
                obj.tarife.ad,
            )
        return format_html(
            '{}<p style="margin-top:.75rem;font-size:.8125rem;color:#6F7B8F">'
            "Eksik yönü aynı kapsamda ikinci bir kural açarak girersiniz; "
            "tarifeye bağlı fiyatlarda tarifenin kendi sayfası daha kolaydır.</p>",
            tablo,
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        alan = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if alan is not None and db_field.name in {"bayi", "tedarikci"}:
            _kullanici_kutusunu_sadelestir(alan)
        return alan

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
            (obj.tedarikci, "Tedarikçi"),
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


@admin.register(OdemeBildirimi)
class OdemeBildirimiAdmin(ModelAdmin):
    """Bayinin "parayı gönderdim" bildirimleri.

    Bildirim para hareketi değildir: onaylanana kadar cüzdana dokunulmaz.
    Onay tutarı tahsilat gibi işler — borç varsa önce o kapanır, artan
    bakiyeye geçer, bankanın bakiyesi de artar.
    """

    list_display = (
        "olusturma_tarihi",
        "bayi",
        "tutar_gosterimi",
        "banka",
        "gonderen_adi",
        "durum_rozeti",
        "karar_veren",
        "karar_dugmeleri",
    )
    list_filter = (
        "durum",
        ("olusturma_tarihi", GunAraligiFiltresi),
        "banka",
    )
    list_filter_submit = True
    search_fields = (
        "bayi__username", "gonderen_adi", "aciklama", "banka__banka_adi"
    )
    autocomplete_fields = ("bayi", "banka")
    readonly_fields = ("karar_veren", "karar_tarihi", "olusturma_tarihi")
    actions = ("onayla", "reddet")
    fieldsets = (
        (
            "Bildirim",
            {
                "fields": ("bayi", "banka", "tutar", "gonderen_adi", "aciklama",
                           "olusturma_tarihi"),
                "description": "Bu bilgileri bayi girdi.",
            },
        ),
        (
            "Karar",
            {
                "fields": ("durum", "karar_notu", "karar_veren", "karar_tarihi"),
                "description": (
                    "Onaylandığında tutar bakiyeye işlenir; borç varsa önce o "
                    "kapanır. Reddedilirse para hiç hareket etmez — sebebini "
                    "yazarsanız bayi cüzdan sayfasında görür."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("bayi", "banka", "karar_veren")
        )

    def save_model(self, request, obj, form, change):
        """Durum formdan değiştirilse de karar servisten geçer.

        `durum` alanı formda düzenlenebilir; yönetici "Onaylandı" seçip
        kaydedince bildirim onaylanmış **görünüyor** ama para hiç hareket
        etmiyordu — bayi "bakiyem yüklenmedi" diyene kadar kimse fark etmez.
        Bayi başvurusundaki onayla aynı kural: karar hangi yoldan verilirse
        verilsin tek servisten geçer.
        """
        onceki = (
            type(obj).objects.filter(pk=obj.pk).values_list("durum", flat=True).first()
            if change
            else None
        )
        kararlar = {OdemeBildirimiDurumu.ONAYLANDI, OdemeBildirimiDurumu.REDDEDILDI}
        yeni_karar = (
            obj.durum
            if onceki == OdemeBildirimiDurumu.BEKLIYOR and obj.durum in kararlar
            else None
        )

        if yeni_karar is None:
            super().save_model(request, obj, form, change)
            return

        # Servis bekleyen bir kayıt bekliyor; kararı o versin.
        obj.durum = OdemeBildirimiDurumu.BEKLIYOR
        super().save_model(request, obj, form, change)

        if yeni_karar == OdemeBildirimiDurumu.ONAYLANDI:
            odeme_bildirimini_onayla(obj, olusturan=request.user)
            self.message_user(
                request,
                f"{obj.bayi.get_username()} · {obj.tutar} ₺ bakiyeye işlendi.",
                messages.SUCCESS,
            )
        else:
            odeme_bildirimini_reddet(obj, olusturan=request.user, not_=obj.karar_notu)
            self.message_user(request, "Bildirim reddedildi.", messages.WARNING)
        obj.refresh_from_db()

    @display(description="Tutar", ordering="tutar")
    def tutar_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.tutar)

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        renkler = {
            OdemeBildirimiDurumu.BEKLIYOR: "#B45309",
            OdemeBildirimiDurumu.ONAYLANDI: "#0F8A4D",
            OdemeBildirimiDurumu.REDDEDILDI: "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    @display(description="")
    def karar_dugmeleri(self, obj):
        """Onayla/Reddet yalnızca bekleyen satırda çıkar.

        unfold'un satır işlemleri satır başına süzülemiyor (`get_actions_row`
        kaydı bilmiyor); sonuçlanmış bildirimde de düğmeler duruyor ve
        yönetici basınca "zaten sonuçlandırılmış" uyarısı alıyordu.
        """
        if not obj.bekliyor:
            return ""
        return format_html_join(
            " ",
            '<a href="{}" style="border:1px solid #e3e8f0;border-radius:.375rem;'
            'padding:.25rem .6rem;font-size:.75rem;font-weight:600;'
            'white-space:nowrap;text-decoration:none;color:{}">{}</a>',
            (
                (
                    reverse(f"admin:finans_odemebildirimi_{yol}", args=[obj.pk]),
                    renk,
                    etiket,
                )
                for yol, renk, etiket in (
                    ("bildirim_onayla", "#0F8A4D", "Onayla"),
                    ("bildirim_reddet", "#D42046", "Reddet"),
                )
            ),
        )

    # --- karar adresleri -------------------------------------------------
    #
    # unfold'un satır işlemleri kullanılmıyor: `get_actions_row` kaydı
    # bilmediği için düğmeler satır başına süzülemiyor ve sonuçlanmış
    # bildirimde de duruyorlardı. Adresleri kendimiz tanımlayıp düğmeyi
    # `karar_dugmeleri` sütununda koşullu çiziyoruz.

    def get_urls(self):
        return [
            path(
                "<int:object_id>/onayla/",
                self.admin_site.admin_view(self.bildirim_onayla),
                name="finans_odemebildirimi_bildirim_onayla",
            ),
            path(
                "<int:object_id>/reddet/",
                self.admin_site.admin_view(self.bildirim_reddet),
                name="finans_odemebildirimi_bildirim_reddet",
            ),
            *super().get_urls(),
        ]

    def bildirim_onayla(self, request, object_id):
        bildirim = self.get_object(request, object_id)
        if bildirim is None:
            raise Http404("Bildirim bulunamadı.")

        if not bildirim.bekliyor:
            self.message_user(
                request, "Bu bildirim zaten sonuçlandırılmış.", messages.INFO
            )
        else:
            odeme_bildirimini_onayla(bildirim, olusturan=request.user)
            self.message_user(
                request,
                f"{bildirim.bayi.get_username()} · {bildirim.tutar} ₺ bakiyeye işlendi.",
                messages.SUCCESS,
            )
        return redirect("admin:finans_odemebildirimi_changelist")

    def bildirim_reddet(self, request, object_id):
        bildirim = self.get_object(request, object_id)
        if bildirim is None:
            raise Http404("Bildirim bulunamadı.")

        if not bildirim.bekliyor:
            self.message_user(
                request, "Bu bildirim zaten sonuçlandırılmış.", messages.INFO
            )
        else:
            odeme_bildirimini_reddet(bildirim, olusturan=request.user)
            self.message_user(
                request,
                f"Bildirim reddedildi. Sebebini yazmak için kaydı açıp "
                f"“Karar Notu” alanını doldurabilirsiniz.",
                messages.WARNING,
            )
        return redirect("admin:finans_odemebildirimi_changelist")

    # --- toplu işlemler -------------------------------------------------

    @admin.action(description="Seçili bildirimleri onayla")
    def onayla(self, request, secilenler):
        islenen = 0
        for bildirim in secilenler:
            if bildirim.bekliyor:
                odeme_bildirimini_onayla(bildirim, olusturan=request.user)
                islenen += 1
        self.message_user(
            request, f"{islenen} bildirim onaylandı ve bakiyeye işlendi.", messages.SUCCESS
        )

    @admin.action(description="Seçili bildirimleri reddet")
    def reddet(self, request, secilenler):
        islenen = 0
        for bildirim in secilenler:
            if bildirim.bekliyor:
                odeme_bildirimini_reddet(bildirim, olusturan=request.user)
                islenen += 1
        self.message_user(request, f"{islenen} bildirim reddedildi.", messages.WARNING)


class AlisAdmin(ModelAdmin):
    """Alış ekranlarının ortak iskeleti.

    "Alışım nereye giriliyor" sorusunun cevabı yön kutusunun içinde saklı
    kalmasın diye her alış türü kendi sayfasında durur. Kayıt yine
    `UcretKurali`: motor tek kaynaktan okumaya devam eder, yalnızca giriş
    yeri ayrıldı.
    """

    yon = KuralYonu.ANA_HAKEDIS
    tedarikciden_mi = False

    list_display = ("kapsam_yazisi", "kaynak", "tutar_gosterimi", "tetikleyici_durum", "aktif")
    list_filter = ("aktif", "kategori", "operator", "tetikleyici_durum")
    search_fields = ("ad", "tarife__ad", "kategori__ad")
    autocomplete_fields = ("kategori", "operator", "tarife", "tetikleyici_durum")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(yon=self.yon, tedarikci__isnull=not self.tedarikciden_mi)
            .select_related("kategori", "operator", "tarife", "tedarikci", "tetikleyici_durum")
        )

    def get_changeform_initial_data(self, request):
        # Yön bu ekranda sabit; yönetici her kayıtta yeniden seçmesin.
        return {"yon": self.yon}

    def save_model(self, request, obj, form, change):
        obj.yon = self.yon
        super().save_model(request, obj, form, change)

    @display(description="Neyin alışı")
    def kapsam_yazisi(self, obj):
        parcalar = [
            p for p in (
                obj.tarife.ad if obj.tarife_id else "",
                obj.kategori.ad if obj.kategori_id else "",
            ) if p
        ]
        return " · ".join(parcalar) or "Tüm işlemler"

    @display(description="Tutar", ordering="tutar")
    def tutar_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.tutar)


@admin.register(OperatorAlisi)
class OperatorAlisiAdmin(AlisAdmin):
    """Operatörden alış: tutar operatörden gelir, cüzdan hareketi oluşmaz."""

    tedarikciden_mi = False
    fieldsets = (
        (
            "Neyin alışı",
            {
                "fields": ("kategori", "operator", "tarife"),
                "description": (
                    "Boş bırakılan alan “hepsi” demektir. En dar kapsamlı kural "
                    "uygulanır."
                ),
            },
        ),
        (
            "Alış fiyatım",
            {
                "fields": ("tutar", "tetikleyici_durum"),
                "description": (
                    "Bu işlemden operatörden aldığınız tutar. Operatörün cüzdanı "
                    "olmadığı için hareket yazılmaz; tutar başvuruya işlenir ve "
                    "kâr hesabına girer."
                ),
            },
        ),
        ("Geçerlilik", {"fields": ("ad", "baslangic_tarihi", "bitis_tarihi", "oncelik", "aktif")}),
    )

    @display(description="Kaynak")
    def kaynak(self, obj):
        return obj.operator.ad if obj.operator_id else "Tüm operatörler"


@admin.register(TedarikciAlisi)
class TedarikciAlisiAdmin(AlisAdmin):
    """Tedarikçiden alış: tutar o tedarikçinin hesabından düşer."""

    tedarikciden_mi = True
    list_filter = ("aktif", "kategori", "operator", "tedarikci", "tetikleyici_durum")
    autocomplete_fields = (
        "kategori", "operator", "tarife", "tedarikci", "tetikleyici_durum",
    )
    fieldsets = (
        (
            "Tedarikçi",
            {
                "fields": ("tedarikci",),
                "description": (
                    "İşlemi üstlenen taraf. Girdiğiniz tutar bu tedarikçinin "
                    "hesabından düşer; boş bırakılamaz."
                ),
            },
        ),
        (
            "Neyin alışı",
            {
                "fields": ("kategori", "operator", "tarife"),
                "description": "Boş bırakılan alan “hepsi” demektir.",
            },
        ),
        ("Alış fiyatım", {"fields": ("tutar", "tetikleyici_durum")}),
        ("Geçerlilik", {"fields": ("ad", "baslangic_tarihi", "bitis_tarihi", "oncelik", "aktif")}),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "tedarikci" in form.base_fields:
            form.base_fields["tedarikci"].required = True
            _kullanici_kutusunu_sadelestir(form.base_fields["tedarikci"])
        return form

    @display(description="Kaynak")
    def kaynak(self, obj):
        if not obj.tedarikci_id:
            return "—"
        profil = getattr(obj.tedarikci, "bayi_profili", None)
        return profil.unvan if profil and profil.unvan else obj.tedarikci.get_username()
