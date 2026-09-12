"""eSIM yönetimi: sağlayıcılar, paketler, ülkeler, teslimatlar.

Günlük iş üç düğmedir: **Eşitle** (sağlayıcının kataloğunu çek), **Kuru
güncelle** (TCMB), **Kâr oranı uygula** (seçili paketlere yüzde). Paket
tek tek elle girilmez.
"""

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils import timezone
from django.utils.timezone import localtime
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.widgets import UnfoldAdminDecimalFieldWidget

from apps.esim.kur import KurAlinamadi, kuru_guncelle
from apps.esim.models import Paket, Saglayici, Teslimat, TeslimatDurumu, Ulke, Yukleme, YuklemeDurumu
from apps.esim.saglayicilar import SaglayiciHatasi
from apps.esim.services import (
    KurTanimsiz,
    bakiyeyi_sorgula,
    durumu_sorgula,
    fiyatlari_guncelle,
    kar_orani_uygula,
    kur_getir,
    paketleri_esitle,
    profili_getir,
    teslimati_iptal_et,
)

DUGME_STILI = (
    "border:1px solid #e3e8f0;border-radius:.375rem;padding:.25rem .6rem;"
    "font-size:.75rem;font-weight:600;white-space:nowrap;text-decoration:none;"
    "background:transparent;cursor:pointer;color:{}"
)


def _post_dugmesi(adres, metin, renk="#0D1320"):
    """Listenin kendi formunu bu adrese POST'lar; kaydı değiştiren iş GET'le olmaz."""
    return format_html(
        '<button type="submit" form="changelist-form" formmethod="post" '
        'formaction="{}" style="{}">{}</button>',
        adres,
        format_html(DUGME_STILI, renk),
        metin,
    )


def _baglanti_dugmesi(adres, metin, renk="#0D1320"):
    return format_html(
        '<a href="{}" style="{}">{}</a>', adres, format_html(DUGME_STILI, renk), metin
    )


# Kur ve katalog bundan eskiyse liste başlığı uyarır; cron yok, elle basılır.
BAYATLIK = timedelta(days=1)


def _kur_ya_da_none():
    try:
        return kur_getir()
    except KurTanimsiz:
        return None


# -- Sağlayıcı ------------------------------------------------------------


@admin.register(Saglayici)
class SaglayiciAdmin(ModelAdmin):
    list_display = (
        "ad",
        "tur_gosterimi",
        "aktif",
        "paket_sayisi",
        "son_esitleme",
        "bakiye_gosterimi",
        "islem_dugmeleri",
    )
    list_filter = ("aktif", "tur")
    readonly_fields = ("son_esitleme", "son_bakiye_usd", "son_bakiye_tarihi")
    fieldsets = (
        (
            "Sağlayıcı",
            {
                "fields": ("ad", "tur", "aktif"),
                "description": (
                    "Paketleri aldığımız API. Kaydedip listedeki <b>Eşitle</b> "
                    "düğmesine basınca katalog çekilir; yeni paketler aşağıdaki "
                    "kâr oranıyla <b>aktif</b> açılır. Oranı sonradan değiştirince "
                    "listedeki <b>Fiyatları güncelle</b> düğmesi bütün paketleri yeni "
                    "orana çeker. İstemediğiniz ülke ya da paketi kendi ekranından "
                    "kapatırsınız."
                ),
            },
        ),
        (
            "API anahtarları",
            {
                "fields": ("erisim_kodu", "gizli_anahtar"),
                "description": "Sağlayıcının panelinden alınır. Buraya yazılır, koda girmez.",
            },
        ),
        ("Fiyatlandırma", {"fields": ("varsayilan_kar_orani",)}),
        ("Durum", {"fields": ("son_esitleme", "son_bakiye_usd", "son_bakiye_tarihi")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_paket_sayisi=Count("paketler"))

    @display(description="Paket", ordering="_paket_sayisi")
    def paket_sayisi(self, obj):
        return obj._paket_sayisi

    @display(description="Sağlayıcı", ordering="tur")
    def tur_gosterimi(self, obj):
        """Belgeden yazılıp canlı anahtarla doğrulanmamış adaptör işaretlenir."""
        if not obj.denenmedi:
            return obj.get_tur_display()
        return format_html(
            '{} <span title="Adaptör sağlayıcının belgesinden yazıldı, canlı anahtarla '
            'doğrulanmadı. İlk eşitleme ve ilk siparişi göz önünde yapın." '
            'style="color:#B45309;font-size:.7rem;font-weight:600">denenmedi</span>',
            obj.get_tur_display(),
        )

    @display(description="Bakiye ($)")
    def bakiye_gosterimi(self, obj):
        if obj.son_bakiye_usd is None:
            return format_html('<span style="color:#94A3B8">sorgulanmadı</span>')
        renk = "#D42046" if obj.son_bakiye_usd < 20 else "#0D1320"
        return format_html(
            '<b style="color:{}">{} $</b><br><span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            renk,
            obj.son_bakiye_usd,
            localtime(obj.son_bakiye_tarihi).strftime("%d.%m.%Y %H:%M") if obj.son_bakiye_tarihi else "",
        )

    @display(description="")
    def islem_dugmeleri(self, obj):
        """Eşitle kataloğu çeker; Fiyatları güncelle varsayılan oranı hepsine yazar.

        Fiyat düğmesi paket gelmeden anlamsız: eşitleme yapılmamış
        sağlayıcıda çizilmez, sonra çıkar.
        """
        dugmeler = [
            (_post_dugmesi(reverse("admin:esim_saglayici_esitle", args=[obj.pk]), "Eşitle"),),
        ]
        if obj._paket_sayisi:
            dugmeler.append(
                (
                    _post_dugmesi(
                        reverse("admin:esim_saglayici_fiyat_guncelle", args=[obj.pk]),
                        f"Fiyatları güncelle (%{obj.varsayilan_kar_orani:g})",
                        "#0E5E5B",
                    ),
                )
            )
        dugmeler.append(
            (_post_dugmesi(reverse("admin:esim_saglayici_bakiye", args=[obj.pk]), "Bakiye sorgula"),)
        )
        return format_html_join(" ", "{}", dugmeler)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/esitle/",
                self.admin_site.admin_view(self.esitle),
                name="esim_saglayici_esitle",
            ),
            path(
                "<int:object_id>/bakiye/",
                self.admin_site.admin_view(self.bakiye),
                name="esim_saglayici_bakiye",
            ),
            path(
                "<int:object_id>/fiyat-guncelle/",
                self.admin_site.admin_view(self.fiyat_guncelle),
                name="esim_saglayici_fiyat_guncelle",
            ),
            *super().get_urls(),
        ]

    def fiyat_guncelle(self, request, object_id):
        """Sağlayıcının bütün paketlerini varsayılan kâr oranına çeker. Yalnızca POST."""
        if request.method != "POST":
            return redirect("admin:esim_saglayici_changelist")
        saglayici = self.get_object(request, object_id)
        if saglayici is None:
            raise Http404("Sağlayıcı bulunamadı.")
        adet = fiyatlari_guncelle(saglayici)
        self.message_user(
            request,
            f"{saglayici}: {adet} paketin kâr oranı %{saglayici.varsayilan_kar_orani} yapıldı; "
            "bayi fiyatları bu orana göre hesaplanıyor.",
            messages.SUCCESS,
        )
        return redirect("admin:esim_saglayici_changelist")

    def esitle(self, request, object_id):
        if request.method != "POST":
            return redirect("admin:esim_saglayici_changelist")
        saglayici = self.get_object(request, object_id)
        if saglayici is None:
            raise Http404("Sağlayıcı bulunamadı.")
        try:
            eklenen, guncellenen, dusen = paketleri_esitle(saglayici)
        except SaglayiciHatasi as hata:
            self.message_user(request, f"{saglayici}: {hata}", messages.ERROR)
        else:
            self.message_user(
                request,
                f"{saglayici}: {eklenen} yeni paket, {guncellenen} güncellendi, "
                f"{dusen} paket sağlayıcının listesinden düştü.",
                messages.SUCCESS,
            )
        return redirect("admin:esim_saglayici_changelist")

    def bakiye(self, request, object_id):
        if request.method != "POST":
            return redirect("admin:esim_saglayici_changelist")
        saglayici = self.get_object(request, object_id)
        if saglayici is None:
            raise Http404("Sağlayıcı bulunamadı.")
        try:
            bakiye = bakiyeyi_sorgula(saglayici)
        except SaglayiciHatasi as hata:
            self.message_user(request, f"{saglayici}: {hata}", messages.ERROR)
        else:
            self.message_user(request, f"{saglayici} bakiyesi: {bakiye} $", messages.SUCCESS)
        return redirect("admin:esim_saglayici_changelist")


# -- Ülke ------------------------------------------------------------------


@admin.register(Ulke)
class UlkeAdmin(ModelAdmin):
    list_display = ("bayrakli_ad", "kod", "paket_sayisi", "aktif")
    list_editable = ("aktif",)
    list_filter = ("aktif",)
    search_fields = ("ad", "kod")
    ordering = ("ad",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_paket_sayisi=Count("paketler"))

    @display(description="Ülke", ordering="ad")
    def bayrakli_ad(self, obj):
        return f"{obj.bayrak} {obj.ad}"

    @display(description="Paket", ordering="_paket_sayisi")
    def paket_sayisi(self, obj):
        return obj._paket_sayisi


# -- Paket -----------------------------------------------------------------


class KarOraniFormu(forms.Form):
    oran = forms.DecimalField(
        label="Kâr oranı (%)",
        min_value=Decimal(0),
        max_digits=6,
        decimal_places=2,
        widget=UnfoldAdminDecimalFieldWidget(attrs={"step": "0.01", "inputmode": "decimal"}),
        help_text="Alışın üzerine eklenecek yüzde. 88 → alış × 1,88.",
    )


class UlkeFiltresi(admin.SimpleListFilter):
    """Ülkeye göre süz: 200 ülke arasından seçim, ad ile."""

    title = "Ülke"
    parameter_name = "ulke"

    def lookups(self, request, model_admin):
        return [(u.kod, f"{u.bayrak} {u.ad}") for u in Ulke.objects.order_by("ad")]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(ulkeler__kod=self.value())
        return queryset


@admin.register(Paket)
class PaketAdmin(ModelAdmin):
    change_list_template = "admin/esim/paket/change_list.html"
    list_display = (
        "ad",
        "saglayici",
        "kapsam_gosterimi",
        "hacim",
        "sure_gun",
        "alis_usd",
        "alis_tl_gosterimi",
        "kar_orani",
        "satis_gosterimi",
        "aktif",
        "durum_isareti",
    )
    list_display_links = ("ad",)
    list_editable = ("kar_orani", "aktif")
    list_filter = ("saglayici", "aktif", "saglayicida_var", UlkeFiltresi)
    search_fields = ("ad", "kod", "slug", "ulkeler__ad", "ulkeler__kod")
    list_per_page = 100
    actions = ("kar_orani_uygula_islemi", "aktif_yap", "pasif_yap")
    readonly_fields = (
        "saglayici", "kod", "slug", "ad", "kapsam", "ulke_sayisi", "hacim_bayt",
        "sure_gun", "hiz", "operatorler", "alis_usd", "saglayicida_var", "son_gorulme",
    )
    fieldsets = (
        (
            "Yönetimin kararı",
            {
                "fields": ("kar_orani", "aktif", "aciklama"),
                "description": (
                    "Sağlayıcıdan gelen alanlar eşitlemede yazılır, elle değiştirilmez. "
                    "Burada karar verilen iki şey var: kâr oranı ve satışta olup olmadığı. "
                    "<b>Bayi grubunda eSIM fiyat farkı girildiyse o gruptaki bayi bu "
                    "fiyatın üzerine o yüzdeyi eklenmiş görür</b> (Finans → Bayi Grupları)."
                ),
            },
        ),
        (
            "Sağlayıcı verisi",
            {
                "fields": (
                    "saglayici", "kod", "slug", "ad", ("hacim_bayt", "sure_gun"), "hiz",
                    "operatorler", "alis_usd", "kapsam", "ulke_sayisi",
                    ("saglayicida_var", "son_gorulme"),
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        # Paketler sağlayıcıdan gelir; elle açılan paketin sipariş kodu olmaz.
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("saglayici")

    def changelist_view(self, request, extra_context=None):
        """Kur ve katalog elle güncellenir (cron yok); eskiyince başlık uyarır."""
        from apps.bayi.models import GenelAyarlar

        ayar = GenelAyarlar.getir()
        simdi = timezone.now()
        esik = simdi - BAYATLIK
        son_esitleme = (
            Saglayici.objects.filter(aktif=True)
            .order_by("son_esitleme")
            .values_list("son_esitleme", flat=True)
            .first()
        )
        from apps.finans.models import BayiGrubu

        extra_context = {
            **(extra_context or {}),
            # Grup farkı bayi fiyatının üzerine eklenir; liste hangi kademenin ne gördüğünü söylesin.
            "grup_oranlari": list(
                BayiGrubu.objects.filter(aktif=True, esim_kar_orani__isnull=False)
                .order_by("ad")
                .values_list("ad", "esim_kar_orani")
            ),
            "kur": ayar.usd_kuru if ayar.usd_kuru else None,
            "kur_tarihi": ayar.usd_kuru_tarihi,
            "kur_bayat": bool(ayar.usd_kuru) and (not ayar.usd_kuru_tarihi or ayar.usd_kuru_tarihi < esik),
            "son_esitleme": son_esitleme,
            "esitleme_bayat": Saglayici.objects.filter(aktif=True).exists()
            and (son_esitleme is None or son_esitleme < esik),
        }
        return super().changelist_view(request, extra_context=extra_context)

    @display(description="Kapsam", ordering="ulke_sayisi")
    def kapsam_gosterimi(self, obj):
        if obj.ulke_sayisi == 1:
            return obj.kapsam
        # Ülke listesi sütuna sığmaz; üzerine gelince görünür.
        return format_html('<span title="{}">{} ülke</span>', obj.kapsam, obj.ulke_sayisi)

    @display(description="Hacim", ordering="hacim_bayt")
    def hacim(self, obj):
        return obj.hacim

    @display(description="Alış (₺)")
    def alis_tl_gosterimi(self, obj):
        kur = _kur_ya_da_none()
        return f"{obj.alis_tl(kur)} ₺" if kur else "—"

    @display(description="Satış (₺)")
    def satis_gosterimi(self, obj):
        kur = _kur_ya_da_none()
        if not kur:
            return format_html('<span style="color:#D42046">kur yok</span>')
        return format_html("<b>{} ₺</b>", obj.satis_fiyati(kur))

    @display(description="")
    def durum_isareti(self, obj):
        if not obj.saglayicida_var:
            return format_html(
                '<span style="color:#D42046;font-size:.75rem;font-weight:600">'
                "sağlayıcıda yok</span>"
            )
        return ""

    # -- toplu işlemler ---------------------------------------------------

    @admin.action(description="Seçili paketlere kâr oranı uygula")
    def kar_orani_uygula_islemi(self, request, secilenler):
        if "uygula" in request.POST:
            form = KarOraniFormu(request.POST)
            if form.is_valid():
                adet = kar_orani_uygula(secilenler, form.cleaned_data["oran"])
                self.message_user(
                    request,
                    f"{adet} paketin kâr oranı %{form.cleaned_data['oran']} yapıldı.",
                    messages.SUCCESS,
                )
                return None
        else:
            form = KarOraniFormu()

        kur = _kur_ya_da_none()
        ornek = secilenler.first()
        return render(
            request,
            "admin/esim/paket/kar_orani.html",
            {
                **self.admin_site.each_context(request),
                "title": "Kâr oranı uygula",
                "form": form,
                "paketler": secilenler,
                "adet": secilenler.count(),
                "ornek": ornek,
                "kur": kur,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Seçili paketleri satışa aç")
    def aktif_yap(self, request, secilenler):
        adet = secilenler.update(aktif=True)
        self.message_user(request, f"{adet} paket satışa açıldı.", messages.SUCCESS)

    @admin.action(description="Seçili paketleri satıştan kaldır")
    def pasif_yap(self, request, secilenler):
        adet = secilenler.update(aktif=False)
        self.message_user(request, f"{adet} paket satıştan kaldırıldı.", messages.SUCCESS)

    # -- üst düğmeler -----------------------------------------------------

    def get_urls(self):
        return [
            path(
                "esitle/", self.admin_site.admin_view(self.esitle), name="esim_paket_esitle"
            ),
            path(
                "kur-guncelle/",
                self.admin_site.admin_view(self.kur_guncelle),
                name="esim_paket_kur_guncelle",
            ),
            *super().get_urls(),
        ]

    def esitle(self, request):
        """Aktif bütün sağlayıcıların kataloğunu çeker."""
        if request.method != "POST":
            return redirect("admin:esim_paket_changelist")
        saglayicilar = Saglayici.objects.filter(aktif=True)
        if not saglayicilar:
            self.message_user(request, "Aktif sağlayıcı yok.", messages.WARNING)
        for saglayici in saglayicilar:
            try:
                eklenen, guncellenen, dusen = paketleri_esitle(saglayici)
            except SaglayiciHatasi as hata:
                self.message_user(request, f"{saglayici}: {hata}", messages.ERROR)
                continue
            self.message_user(
                request,
                f"{saglayici}: {eklenen} yeni, {guncellenen} güncellendi, {dusen} düştü.",
                messages.SUCCESS,
            )
        return redirect("admin:esim_paket_changelist")

    def kur_guncelle(self, request):
        if request.method != "POST":
            return redirect("admin:esim_paket_changelist")
        try:
            kur = kuru_guncelle()
        except KurAlinamadi as hata:
            self.message_user(request, str(hata), messages.ERROR)
        else:
            self.message_user(request, f"USD kuru TCMB'den alındı: {kur} ₺", messages.SUCCESS)
        return redirect("admin:esim_paket_changelist")


# -- Teslimat --------------------------------------------------------------


@admin.register(Teslimat)
class TeslimatAdmin(ModelAdmin):
    list_display = (
        "referans",
        "olusturma_tarihi",
        "bayi_gosterimi",
        "paket_gosterimi",
        "saglayici",
        "durum_rozeti",
        "kurulum_gosterimi",
        "tutar_gosterimi",
        "iccid",
        "karar_dugmeleri",
    )
    list_filter = ("durum", "saglayici")
    search_fields = (
        "siparis__referans_no", "iccid", "islem_no", "saglayici_siparis_no", "esim_no",
        "paket_kodu", "siparis__urun_adi", "siparis__bayi__username",
        "siparis__bayi__bayi_profili__unvan", "musteri_adi", "musteri_telefonu",
    )
    date_hierarchy = "olusturma_tarihi"
    readonly_fields = tuple(
        a.name
        for a in Teslimat._meta.fields
        if a.name not in ("id", "musteri_adi", "musteri_telefonu")
    ) + ("smdp_adresi", "aktivasyon_kodu", "kar")
    fieldsets = (
        (
            "Sipariş",
            {
                "fields": ("siparis", "saglayici", "paket", "paket_kodu", "durum", "hata"),
                "description": (
                    "Her şey salt okunur: sağlayıcıyla yazışmanın izi. Hazır bir eSIM'i "
                    "iptal etmek için listedeki düğmeyi kullanın — önce sağlayıcıda iptal "
                    "edilir, sonra bayiye iade yapılır."
                ),
            },
        ),
        (
            "Para",
            {
                "fields": (("alis_usd", "kur", "alis_tl"), ("kar_orani", "grup_orani", "tavsiye_fiyati"), "kar"),
                "description": (
                    "<b>Kâr = bayiye satış − sağlayıcıdan alış</b>; bizim kazancımız. "
                    "Tavsiye fiyat bayinin müşteriye satışıdır, bizim hesaba girmez."
                ),
            },
        ),
        (
            "Müşteri",
            {
                "fields": (("musteri_adi", "musteri_telefonu"),),
                "description": "Bayinin kendi notu; müşteri aradığında eSIM'i bulmak için. Sağlayıcıya gitmez.",
            },
        ),
        (
            "Profil",
            {
                "fields": (
                    "islem_no", "saglayici_siparis_no", "esim_no", "iccid",
                    "ac", "smdp_adresi", "aktivasyon_kodu", "qr_url", "kisa_url", "apn",
                    "son_sorgu",
                ),
            },
        ),
        (
            "Telefondaki durum",
            {
                "fields": (
                    ("kurulum_durumu", "esim_durumu"), "eid", "aktivasyon_zamani", "son_durum_sorgusu",
                ),
                "description": (
                    "Sağlayıcının gördüğü kurulum. EID doluysa QR bir telefona okutulmuş; "
                    "ilk bağlantı boşsa hat henüz ağa bağlanmamış (telefonda hat ve Veri Dolaşımı "
                    "açık olmalı). Listedeki <b>Durumu sorgula</b> yeniler."
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("siparis", "siparis__bayi", "siparis__bayi__bayi_profili", "saglayici")
        )

    @display(description="Sipariş", ordering="siparis__referans_no")
    def referans(self, obj):
        return obj.siparis.referans_no

    @display(description="Bayi", ordering="siparis__bayi__username")
    def bayi_gosterimi(self, obj):
        bayi = obj.siparis.bayi
        profil = getattr(bayi, "bayi_profili", None)
        unvan = profil.unvan if profil and profil.unvan else ""
        if not unvan:
            return bayi.get_username()
        return format_html(
            '<span style="font-weight:600">{}</span><br>'
            '<span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            unvan, bayi.get_username(),
        )

    @display(description="Paket")
    def paket_gosterimi(self, obj):
        return obj.siparis.urun_adi.removeprefix("eSIM · ")

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        renkler = {
            TeslimatDurumu.BEKLIYOR: "#B45309",
            TeslimatDurumu.HAZIRLANIYOR: "#B45309",
            TeslimatDurumu.HAZIR: "#0F8A4D",
            TeslimatDurumu.IPTAL: "#6F7B8F",
            TeslimatDurumu.HATA: "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    @display(description="Telefon")
    def kurulum_gosterimi(self, obj):
        """QR okutuldu mu, hat bağlandı mı — "çalışmıyor" şikâyetinde ilk bakılan."""
        if not obj.hazir:
            return ""
        if not obj.son_durum_sorgusu and not obj.eid:
            return format_html('<span style="color:#94A3B8;font-size:.75rem">sorgulanmadı</span>')
        if obj.hatta_baglandi:
            return format_html('<span style="color:#0F8A4D;font-weight:600;font-size:.75rem">bağlandı</span>')
        if obj.telefona_kuruldu:
            return format_html(
                '<span style="color:#B45309;font-weight:600;font-size:.75rem" title="EID {}">'
                "kuruldu, bağlanmadı</span>",
                obj.eid,
            )
        return format_html('<span style="color:#6F7B8F;font-size:.75rem">okutulmadı</span>')

    @display(description="Bayiye satış / sağlayıcı alışı / kârımız")
    def tutar_gosterimi(self, obj):
        """Üç rakam da bizim hesabımız: bayinin müşteriye kârı burada yok."""
        if obj.durum in (TeslimatDurumu.HATA, TeslimatDurumu.IPTAL):
            return format_html(
                "<s style='color:#6F7B8F'>{} ₺</s><br>"
                "<span style='color:#6F7B8F;font-size:.75rem'>iade edildi</span>",
                obj.siparis.tutar,
            )
        return format_html(
            "<b>{} ₺</b><br><span style='color:#6F7B8F;font-size:.75rem'>alış {} ₺ · "
            "<b style='color:#0F8A4D'>kârımız {} ₺</b></span>",
            obj.siparis.tutar, obj.alis_tl, obj.kar,
        )

    @display(description="")
    def karar_dugmeleri(self, obj):
        parcalar = []
        if obj.durum == TeslimatDurumu.HAZIRLANIYOR:
            parcalar.append(
                _post_dugmesi(reverse("admin:esim_teslimat_profil", args=[obj.pk]), "Profili getir")
            )
        if obj.hazir:
            parcalar.append(
                _post_dugmesi(reverse("admin:esim_teslimat_durum", args=[obj.pk]), "Durumu sorgula")
            )
        if obj.iptal_edilebilir:
            parcalar.append(
                _baglanti_dugmesi(
                    reverse("admin:esim_teslimat_iptal", args=[obj.pk]), "İptal et", "#D42046"
                )
            )
        if not parcalar:
            return ""
        return format_html_join(" ", "{}", ((p,) for p in parcalar))

    def get_urls(self):
        return [
            path(
                "<int:object_id>/profil/",
                self.admin_site.admin_view(self.profil),
                name="esim_teslimat_profil",
            ),
            path(
                "<int:object_id>/iptal/",
                self.admin_site.admin_view(self.iptal),
                name="esim_teslimat_iptal",
            ),
            path(
                "<int:object_id>/durum/",
                self.admin_site.admin_view(self.durum),
                name="esim_teslimat_durum",
            ),
            *super().get_urls(),
        ]

    def durum(self, request, object_id):
        """Sağlayıcıdan kurulum durumunu çeker: okutuldu mu, bağlandı mı."""
        if request.method != "POST":
            return redirect("admin:esim_teslimat_changelist")
        teslimat = self.get_object(request, object_id)
        if teslimat is None:
            raise Http404("Teslimat bulunamadı.")
        teslimat = durumu_sorgula(teslimat)
        if teslimat.hatta_baglandi:
            mesaj = f"{teslimat.siparis.referans_no}: telefona kuruldu ve ilk bağlantı {teslimat.aktivasyon_zamani}."
        elif teslimat.telefona_kuruldu:
            mesaj = (
                f"{teslimat.siparis.referans_no}: profil telefona kuruldu (EID {teslimat.eid}) ama hat "
                "henüz ağa bağlanmadı — telefonda hat açık ve Veri Dolaşımı açık olmalı."
            )
        else:
            mesaj = f"{teslimat.siparis.referans_no}: QR henüz bir telefona okutulmamış."
        self.message_user(request, mesaj, messages.INFO)
        return redirect("admin:esim_teslimat_changelist")

    def profil(self, request, object_id):
        if request.method != "POST":
            return redirect("admin:esim_teslimat_changelist")
        teslimat = self.get_object(request, object_id)
        if teslimat is None:
            raise Http404("Teslimat bulunamadı.")
        teslimat = profili_getir(teslimat, zorla=True)
        if teslimat.hazir:
            self.message_user(request, f"{teslimat.siparis.referans_no} profili geldi.", messages.SUCCESS)
        else:
            self.message_user(
                request,
                f"{teslimat.siparis.referans_no} hâlâ hazırlanıyor; sağlayıcı henüz profil vermedi.",
                messages.INFO,
            )
        return redirect("admin:esim_teslimat_changelist")

    def iptal(self, request, object_id):
        """Önce sağlayıcıda iptal, sonra bayiye iade. Onay ekranı, POST ile iş."""
        teslimat = self.get_object(request, object_id)
        if teslimat is None:
            raise Http404("Teslimat bulunamadı.")
        if not teslimat.iptal_edilebilir:
            self.message_user(request, "Bu teslimat iptal edilebilir durumda değil.", messages.INFO)
            return redirect("admin:esim_teslimat_changelist")

        if request.method == "POST":
            try:
                teslimati_iptal_et(teslimat, olusturan=request.user)
            except SaglayiciHatasi as hata:
                self.message_user(
                    request,
                    f"Sağlayıcı iptali kabul etmedi, para iade edilmedi: {hata}",
                    messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"{teslimat.siparis.referans_no} sağlayıcıda iptal edildi; "
                    f"{teslimat.siparis.tutar} ₺ bayinin bakiyesine geri yazıldı.",
                    messages.WARNING,
                )
            return redirect("admin:esim_teslimat_changelist")

        return render(
            request,
            "admin/esim/teslimat_iptal.html",
            {
                **self.admin_site.each_context(request),
                "title": "eSIM'i iptal et",
                "teslimat": teslimat,
                "siparis": teslimat.siparis,
                "opts": self.model._meta,
            },
        )


# -- Yükleme ---------------------------------------------------------------


@admin.register(Yukleme)
class YuklemeAdmin(ModelAdmin):
    """Satılmış eSIM'e yüklenen paketler. Salt okunur; para sipariş ekranında."""

    list_display = (
        "referans", "olusturma_tarihi", "bayi_gosterimi", "esim_gosterimi",
        "paket_adi", "durum_rozeti", "tutar_gosterimi",
    )
    list_filter = ("durum", "teslimat__saglayici")
    search_fields = (
        "siparis__referans_no", "paket_adi", "paket_kodu", "islem_no", "teslimat__iccid",
        "teslimat__musteri_adi", "siparis__bayi__username", "siparis__bayi__bayi_profili__unvan",
    )
    date_hierarchy = "olusturma_tarihi"
    readonly_fields = tuple(a.name for a in Yukleme._meta.fields if a.name != "id") + ("kar",)

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("siparis", "siparis__bayi", "siparis__bayi__bayi_profili", "teslimat", "teslimat__siparis")
        )

    @display(description="Sipariş", ordering="siparis__referans_no")
    def referans(self, obj):
        return obj.siparis.referans_no

    @display(description="Bayi", ordering="siparis__bayi__username")
    def bayi_gosterimi(self, obj):
        bayi = obj.siparis.bayi
        profil = getattr(bayi, "bayi_profili", None)
        return (profil.unvan if profil and profil.unvan else "") or bayi.get_username()

    @display(description="eSIM")
    def esim_gosterimi(self, obj):
        return format_html(
            '<a href="{}" style="text-decoration:underline">{}</a><br>'
            '<span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            reverse("admin:esim_teslimat_change", args=[obj.teslimat_id]),
            obj.teslimat.siparis.referans_no,
            obj.teslimat.musteri_adi or obj.teslimat.iccid,
        )

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        renkler = {
            YuklemeDurumu.BEKLIYOR: "#B45309",
            YuklemeDurumu.TAMAM: "#0F8A4D",
            YuklemeDurumu.IPTAL: "#6F7B8F",
            YuklemeDurumu.HATA: "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    @display(description="Bayiye satış / sağlayıcı alışı / kârımız")
    def tutar_gosterimi(self, obj):
        if obj.durum in (YuklemeDurumu.HATA, YuklemeDurumu.IPTAL):
            return format_html("<s style='color:#6F7B8F'>{} ₺</s>", obj.siparis.tutar)
        return format_html(
            "<b>{} ₺</b><br><span style='color:#6F7B8F;font-size:.75rem'>alış {} ₺ · "
            "<b style='color:#0F8A4D'>kârımız {} ₺</b></span>",
            obj.siparis.tutar, obj.alis_tl, obj.kar,
        )
