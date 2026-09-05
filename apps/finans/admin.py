from decimal import Decimal
from uuid import uuid4

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display
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
    UcretKurali,
)
from apps.filtreler import GunAraligiFiltresi
from apps.finans.services import cuzdan_islemi

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
        "cuzdan",
        "tip",
        "tutar_gosterimi",
        "sonraki_bakiye",
        "sonraki_borc",
        "kaynak",
        "olusturan",
        "aciklama",
    )
    # Tarih aralığı: yönetici "1–5 Eylül arasında bu bayiye ne işlendi"
    # sorusuna tek ekranda bakabilsin.
    list_filter = (
        "tip",
        ("tarih", GunAraligiFiltresi),
        "cuzdan__grup",
        "olusturan",
    )
    list_filter_submit = True
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
        "tedarikci",
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
