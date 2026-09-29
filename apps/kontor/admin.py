"""Kontör yönetimi: sağlayıcılar, kategoriler, paketler, işlemler, bayi API'si.

Günlük iş **İşlemler** listesidir ve orada da çoğu zaman yapılacak bir şey
yoktur: işlemler kendiliğinden gönderilir, sonuçlanır, gerekirse iade
edilir. Yöneticinin elini isteyen tek durum **Askıda**'dır — bir
sağlayıcının cevabı anlaşılamadı; yüklenmiş de olabilir, olmamış da. Rozet
onları sayar, satırdaki **Karar** düğmesi ne yapılabileceğini anlatan
ekranı açar.
"""

from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.timezone import localtime
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from unfold.widgets import (
    UnfoldAdminDecimalFieldWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextInputWidget,
)

from apps.bayi.etiket import kullanici_etiketi_html
from apps.filtreler import GunAraligiFiltresi
from apps.katalog.models import Operator
from apps.kontor.models import (
    ApiErisimi,
    Deneme,
    FiyatGrubu,
    GorulenPaket,
    Islem,
    IslemDurumu,
    Kategori,
    Paket,
    PaketFiyati,
    Rota,
    Saglayici,
    SaglayiciPaketi,
)
from apps.kontor.saglayicilar import SaglayiciHatasi
from apps.kontor.services import (
    IslemMesgul,
    KararVerilemez,
    elle_gonder,
    fiyat_listesini_cek,
    grup_fiyati,
    gorulen_paketi_kataloga_ekle,
    tavsiyeyi_operatorden_al,
    iptal_et,
    sonucu_sorgula,
    yuklendi_say,
)

DUGME_STILI = (
    "border:1px solid #e3e8f0;border-radius:.375rem;padding:.25rem .6rem;"
    "font-size:.75rem;font-weight:600;white-space:nowrap;text-decoration:none;"
    "background:transparent;cursor:pointer;color:{}"
)

DURUM_RENKLERI = {
    IslemDurumu.SIRADA: "#6F7B8F",
    IslemDurumu.ISLEMDE: "#B45309",
    IslemDurumu.ASKIDA: "#D42046",
    IslemDurumu.BASARILI: "#0F8A4D",
    IslemDurumu.IPTAL: "#6F7B8F",
}


def _atomik_degil(gorunum):
    """Sağlayıcıyla konuşan yönetim ekranları istek transaction'ının dışında.

    `ATOMIC_REQUESTS` açık; gönderim kaydı ağa çıkmadan commit edilmezse
    süreç düştüğünde kaybolur ve işlem ikinci kez gönderilirdi.
    """

    def sarmalayici(*args, **kwargs):
        return gorunum(*args, **kwargs)

    return transaction.non_atomic_requests(sarmalayici)


def _post_dugmesi(adres, metin, renk="#0D1320"):
    return format_html(
        '<button type="submit" form="changelist-form" formmethod="post" '
        'formaction="{}" style="{}">{}</button>',
        adres,
        format_html(DUGME_STILI, renk),
        metin,
    )


def _baglanti_dugmesi(adres, metin, renk="#0D1320"):
    return format_html('<a href="{}" style="{}">{}</a>', adres, format_html(DUGME_STILI, renk), metin)


def _rozet(metin, renk):
    return format_html(
        '<span style="background:{};color:#fff;padding:.15rem .6rem;border-radius:999px;'
        'font-size:.75rem;font-weight:600;white-space:nowrap">{}</span>',
        renk,
        metin,
    )


def _kullanici_kutusunu_sadelestir(alan):
    """Kullanıcı seçtiren kutuda ekle/düzenle/sil kapalı: çöp kutusu seçimi değil hesabı siler."""
    widget = getattr(alan, "widget", None)
    for ad in ("can_add_related", "can_change_related", "can_delete_related", "can_view_related"):
        if hasattr(widget, ad):
            setattr(widget, ad, False)
    return alan


# -- Sağlayıcı ------------------------------------------------------------


class SaglayiciFormu(forms.ModelForm):
    class Meta:
        model = Saglayici
        fields = "__all__"
        widgets = {"sifre": forms.PasswordInput(render_value=True)}


@admin.register(Saglayici)
class SaglayiciAdmin(ModelAdmin):
    form = SaglayiciFormu
    list_display = ("ad", "tur_gosterimi", "aktif", "adres", "rota_sayisi", "son_24_saat", "islem_dugmeleri")
    list_filter = ("aktif", "tur")
    readonly_fields = ("son_liste_cekme",)
    fieldsets = (
        (
            "Sağlayıcı",
            {
                "fields": ("ad", "tur", "aktif"),
                "description": (
                    "İşlemleri ilettiğimiz bayi sistemi. Hangi paketin buraya gideceği "
                    "paketin kendi sayfasındaki <b>Sağlayıcı sırası</b> tablosundan "
                    "belirlenir. Kapatılan sağlayıcıya hiçbir işlem gitmez, sıradaki denenir."
                ),
            },
        ),
        (
            "Bağlantı",
            {
                "fields": ("adres", "bayi_kodu", "kullanici_adi", "sifre"),
                "description": "Sağlayıcının verdiği bilgiler. Buraya yazılır, koda girmez.",
            },
        ),
        ("Referans", {"fields": ("ref_sayaci",)}),
        ("Fiyat listesi", {"fields": ("son_liste_cekme",)}),
    )

    def get_queryset(self, request):
        gun_once = timezone.now() - timedelta(days=1)
        return (
            super()
            .get_queryset(request)
            .annotate(
                _rota=Count("rotalar", distinct=True),
                _basarili=Count(
                    "islemler",
                    filter=Q(islemler__durum=IslemDurumu.BASARILI, islemler__olusturma_tarihi__gte=gun_once),
                    distinct=True,
                ),
                _red=Count(
                    "denemeler",
                    filter=Q(denemeler__durum="reddedildi", denemeler__olusturma_tarihi__gte=gun_once),
                    distinct=True,
                ),
            )
        )

    @display(description="Paket", ordering="_rota")
    def rota_sayisi(self, obj):
        """Sağlayıcının paketleri ve alışları: tıklanınca alışlar toplu girilir."""
        adres = reverse("admin:kontor_rota_changelist") + f"?saglayici__id__exact={obj.pk}"
        return format_html('<a href="{}">{} paket · alışlar</a>', adres, obj._rota)

    @display(description="Son 24 saat")
    def son_24_saat(self, obj):
        return format_html(
            '<span style="color:#0F8A4D">{} yüklendi</span><br>'
            '<span style="color:#6F7B8F;font-size:.75rem">{} ret</span>',
            obj._basarili,
            obj._red,
        )

    @display(description="Yazılımı", ordering="tur")
    def tur_gosterimi(self, obj):
        if not obj.denenmedi:
            return obj.get_tur_display()
        return format_html(
            '{} <span title="Protokol eski sistemden aktarıldı ama bu kodla canlı hesapta '
            'denenmedi. İlk işlemi göz önünde yapın." '
            'style="color:#B45309;font-size:.7rem;font-weight:600">denenmedi</span>',
            obj.get_tur_display(),
        )

    @display(description="")
    def islem_dugmeleri(self, obj):
        if not obj.paket_listesi_var:
            return ""
        etiket = "Fiyat listesini çek"
        if obj.son_liste_cekme:
            etiket += f" ({localtime(obj.son_liste_cekme):%d.%m %H:%M})"
        return _post_dugmesi(reverse("admin:kontor_saglayici_liste_cek", args=[obj.pk]), etiket)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/liste-cek/",
                self.admin_site.admin_view(self.liste_cek),
                name="kontor_saglayici_liste_cek",
            ),
            *super().get_urls(),
        ]

    def liste_cek(self, request, object_id):
        """Fiyat listesini çeker; rotaların alış fiyatları güncellenir. Yalnızca POST."""
        if request.method != "POST":
            return redirect("admin:kontor_saglayici_changelist")
        saglayici = self.get_object(request, object_id)
        if saglayici is None:
            raise Http404("Sağlayıcı bulunamadı.")
        try:
            adet, guncellenen = fiyat_listesini_cek(saglayici)
        except SaglayiciHatasi as hata:
            self.message_user(request, f"{saglayici}: {hata}", messages.ERROR)
        else:
            self.message_user(
                request,
                f"{saglayici}: listede {adet} ürün; {guncellenen} paketin alış fiyatı güncellendi. "
                "Satış fiyatlarına dokunulmadı.",
                messages.SUCCESS,
            )
        return redirect("admin:kontor_saglayici_changelist")


@admin.register(Rota)
class RotaAdmin(ModelAdmin):
    """Sağlayıcı Alışları: her sağlayıcıdan her paketin alışı tek listede.

    Aynı paket her sağlayıcıdan farklı fiyata alınır; alış rotanın üstündedir.
    Paket sayfasındaki tablo tek paketin sağlayıcılarını gösterir, burası
    tek sağlayıcının bütün paketlerini — fiyat listesi gelince satır satır
    buradan yazılır. Bayinin fiyatı sıradaki ilk açık sağlayıcının alışından
    hesaplanır.
    """

    list_display = ("paket", "kategori", "saglayici", "sira", "gidecek_kod_gosterimi", "alis_fiyati", "aktif")
    list_display_links = ("paket",)
    list_editable = ("sira", "alis_fiyati", "aktif")
    list_filter = ("saglayici", "paket__kategori__operator", "paket__kategori", "aktif")
    search_fields = ("paket__ad", "paket__kod", "uzak_kod", "paket__kategori__ad")
    list_per_page = 50
    ordering = ("saglayici__ad", "paket__kategori__sira", "paket__kategori__ad", "paket__sira", "paket__ad")
    fields = ("paket", "saglayici", "sira", "uzak_kod", "uzak_operator", "uzak_tip", "alis_fiyati", "aktif")
    autocomplete_fields = ("paket",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("paket__kategori", "saglayici")

    @display(description="Kategori", ordering="paket__kategori__ad")
    def kategori(self, obj):
        return obj.paket.kategori

    @display(description="Sağlayıcıdaki kodu")
    def gidecek_kod_gosterimi(self, obj):
        return obj.gidecek_kod


@admin.register(SaglayiciPaketi)
class SaglayiciPaketiAdmin(ModelAdmin):
    """Sağlayıcının çekilen fiyat listesi: yalnızca okunur, eşleştirme için bakılır."""

    list_display = ("saglayici", "kod", "ad", "operator", "tip", "fiyat", "cekilme")
    list_filter = ("saglayici", "operator")
    search_fields = ("kod", "ad")
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# -- Görülen paketler -------------------------------------------------------


class KatalogFiltresi(admin.SimpleListFilter):
    title = "Katalogda"
    parameter_name = "katalog"

    def lookups(self, request, model_admin):
        return (("yeni", "Yeni (katalogda yok)"), ("var", "Katalogda var"), ("yok_say", "Yok sayılan"))

    def queryset(self, request, queryset):
        katalogda = Paket.objects.filter(kategori_id=OuterRef("kategori_id"), kod=OuterRef("kod"))
        if self.value() == "yeni":
            return queryset.filter(yok_say=False).exclude(Exists(katalogda))
        if self.value() == "var":
            return queryset.filter(Exists(katalogda))
        if self.value() == "yok_say":
            return queryset.filter(yok_say=True)
        return queryset


@admin.register(GorulenPaket)
class GorulenPaketAdmin(ModelAdmin):
    """Operatörün numara sorgusunda görülen paketler.

    Günlük iş rozetteki "yeni" paketlere bakmaktır: satılacaksa **Kataloğa
    ekle** (fiyatsız ve sağlayıcısız açılır, bayiye görünmez; paket
    sayfasında tamamlanır), satılmayacaksa **Yok say**.
    """

    list_display = (
        "ad_gosterimi", "kod", "kategori", "fiyat_gosterimi", "ilk_gorulme", "son_gorulme",
        "gorulme_sayisi", "katalog_durumu",
    )
    list_filter = (KatalogFiltresi, "kaynak", "kategori__operator", "kategori")
    search_fields = ("kod", "ad", "aciklama")
    readonly_fields = (
        "kaynak", "kod", "kategori", "ad", "aciklama", "fiyat", "onceki_fiyat", "fiyat_degisme",
        "ilk_gorulme", "son_gorulme", "gorulme_sayisi",
    )
    fields = readonly_fields + ("yok_say",)
    actions = ("yok_say_isaretle", "yok_saymayi_kaldir")
    list_per_page = 50
    # En yeni yakalanan paket her zaman en üstte. Aynı sorgudan gelenlerin
    # zamanı neredeyse aynı; pk eşitliği bozar, sıra sayfa sayfa oynamaz.
    ordering = ("-ilk_gorulme", "-pk")

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        katalogda = Paket.objects.filter(kategori_id=OuterRef("kategori_id"), kod=OuterRef("kod"))
        return (
            super().get_queryset(request)
            .select_related("kategori")
            .annotate(_katalog_pk=Subquery(katalogda.values("pk")[:1]))
        )

    @display(description="Paket", ordering="ad")
    def ad_gosterimi(self, obj):
        return format_html(
            '{}<br><span style="color:#6F7B8F;font-size:.75rem">{}</span>', obj.ad or obj.kod, obj.aciklama[:90]
        )

    @display(description="Operatör fiyatı", ordering="fiyat")
    def fiyat_gosterimi(self, obj):
        if obj.fiyat is None:
            return "—"
        if obj.onceki_fiyat is not None:
            return format_html(
                '<b>{}</b><br><span style="color:#B45309;font-size:.75rem">önce {} · {}</span>',
                obj.fiyat, obj.onceki_fiyat, localtime(obj.fiyat_degisme).strftime("%d.%m %H:%M") if obj.fiyat_degisme else "",
            )
        return obj.fiyat

    @display(description="Katalog")
    def katalog_durumu(self, obj):
        if obj._katalog_pk:
            return format_html(
                '<a href="{}" style="color:#0F8A4D;font-weight:600">katalogda</a>',
                reverse("admin:kontor_paket_change", args=[obj._katalog_pk]),
            )
        if obj.yok_say:
            return format_html('<span style="color:#94A3B8">yok sayıldı</span>')
        if obj.kategori_id is None:
            return format_html('<b style="color:#D42046">yeni</b>')
        return format_html_join(
            " ",
            "{}",
            (
                (format_html('<b style="color:#D42046">yeni</b>'),),
                (_post_dugmesi(reverse("admin:kontor_gorulenpaket_ekle", args=[obj.pk]), "Kataloğa ekle", "#0E5E5B"),),
            ),
        )

    def get_urls(self):
        return [
            path(
                "<int:object_id>/kataloga-ekle/",
                self.admin_site.admin_view(self.kataloga_ekle),
                name="kontor_gorulenpaket_ekle",
            ),
            *super().get_urls(),
        ]

    def kataloga_ekle(self, request, object_id):
        """Paketi kategorisine açar ve paket sayfasına gider. Yalnızca POST."""
        if request.method != "POST":
            return redirect("admin:kontor_gorulenpaket_changelist")
        gorulen = self.get_object(request, object_id)
        if gorulen is None:
            raise Http404("Paket bulunamadı.")
        try:
            paket, yeni = gorulen_paketi_kataloga_ekle(gorulen)
        except KararVerilemez as hata:
            self.message_user(request, str(hata), messages.ERROR)
            return redirect("admin:kontor_gorulenpaket_changelist")
        self.message_user(
            request,
            f"“{paket.ad}” {'kataloğa eklendi' if yeni else 'zaten katalogdaydı'}. Satış fiyatını ve "
            "sağlayıcı sırasını girin; ikisi girilmeden bayiye görünmez.",
            messages.SUCCESS if yeni else messages.INFO,
        )
        return redirect("admin:kontor_paket_change", paket.pk)

    @admin.action(description="Yok say (rozetten düşür)")
    def yok_say_isaretle(self, request, queryset):
        adet = queryset.update(yok_say=True)
        self.message_user(request, f"{adet} paket yok sayıldı.", messages.SUCCESS)

    @admin.action(description="Yok saymayı kaldır")
    def yok_saymayi_kaldir(self, request, queryset):
        adet = queryset.update(yok_say=False)
        self.message_user(request, f"{adet} paket yeniden takipte.", messages.SUCCESS)


# -- Kategori -------------------------------------------------------------


@admin.register(Kategori)
class KategoriAdmin(ModelAdmin):
    list_display = ("ad", "oyun", "operator", "hedef", "api_kodu", "paket_sayisi", "sira", "aktif")
    list_editable = ("sira", "aktif")
    list_filter = ("oyun", "aktif", "operator", "hedef")
    search_fields = ("ad", "api_operator", "api_tip")
    fieldsets = (
        (None, {"fields": ("ad", "slug", "oyun", "operator", "gorsel", "aciklama", "sira", "aktif")}),
        (
            "Yükleme",
            {
                "fields": ("hedef", "hedef_etiketi", "sorgu_kaynagi", "sorgu_sahibi_goster"),
                "description": "Bayinin formda ne yazacağı: telefon numarası, oyuncu ID ya da hiçbir şey (pin).",
            },
        ),
        (
            "Protokol kodları",
            {
                "fields": ("api_operator", "api_tip"),
                "description": (
                    "Bayi programları kategoriyi bu iki kodla ister (operator=vodafone&amp;tip=ses). "
                    "Sağlayıcıya da, paketin sırasında ayrı kod yazılmadıysa bunlar gider."
                ),
            },
        ),
    )
    def get_queryset(self, request):
        return super().get_queryset(request).select_related("operator").annotate(_paket=Count("paketler"))

    @display(description="Paket", ordering="_paket")
    def paket_sayisi(self, obj):
        adres = reverse("admin:kontor_paket_changelist") + f"?kategori__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', adres, obj._paket)

    @display(description="Protokol")
    def api_kodu(self, obj):
        if not obj.api_operator:
            return format_html('<span style="color:#94A3B8">—</span>')
        return f"{obj.api_operator} / {obj.api_tip or '—'}"


# -- Fiyat grupları ------------------------------------------------------

PAKET_FIYAT_SAYFASI = 50


def _ondalik(metin):
    """Kutudan gelen "444,15" / "1.250,50" / "444.15" → Decimal; boşsa None, bozuksa hata."""
    metin = (metin or "").strip().replace(" ", "")
    if not metin:
        return None
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    deger = Decimal(metin)  # bozuksa InvalidOperation
    if deger < 0:
        raise InvalidOperation
    return deger.quantize(Decimal("0.01"))


@admin.register(FiyatGrubu)
class FiyatGrubuAdmin(ModelAdmin):
    """Perakende, Toptan… Grubun sayfası **tek sayfadır**: üstte ayarlar, altta paket fiyatları.

    Her pakette tek rakam durur: bu gruptaki bayinin ödeyeceği net fiyat.
    Boş kutu = paket bu gruba satılmaz. Alış + % / alış + ₺ yalnızca üstteki
    çubukta **hesap aracıdır**: seçilen paketlerin alışından fiyatı hesaplayıp
    kutulara yazar, yönetici bakar, düzeltir, kaydeder.

    Bu ekran iki kez yanlış kuruldu. Önce grup formu ayrı, paket fiyatları
    listedeki ayrı bir düğmenin arkasındaydı ("içerisi aynı, niye ayrı?").
    Sonra her satıra yöntem kutusu (net / alış + % / alış + ₺) ve grubun genel
    oranı kondu; yönetici "yöntemin hepsi net fiyat olacak, her pakete aynı
    444,10'u yazmanın anlamı yok" dedi. Satıra ikinci bir alan koyma.
    Paketler binlerce olabilir: operatör/kategoriye süzülür, sayfa başı 50.
    """

    list_display = ("ad", "fiyatli_sayisi", "varsayilan", "bayi_sayisi", "aciklama")
    search_fields = ("ad",)
    fields = ("ad", "varsayilan", "aciklama")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Grubun sayfası paket fiyatlarıdır; ayarlar da o sayfanın üstünde durur."""
        return redirect("admin:kontor_fiyatgrubu_paketler", object_id)

    def response_add(self, request, obj, post_url_continue=None):
        return redirect("admin:kontor_fiyatgrubu_paketler", obj.pk)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_bayi=Count("cuzdanlar", distinct=True), _fiyatli=Count("paket_fiyatlari", distinct=True))
        )

    @display(description="Fiyatı yazılı paket", ordering="_fiyatli")
    def fiyatli_sayisi(self, obj):
        return obj._fiyatli or "—"

    @display(description="Bayi", ordering="_bayi")
    def bayi_sayisi(self, obj):
        adres = reverse("admin:finans_cuzdan_changelist") + f"?kontor_grubu__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', adres, obj._bayi)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/paketler/",
                self.admin_site.admin_view(self.paket_fiyatlari),
                name="kontor_fiyatgrubu_paketler",
            ),
            *super().get_urls(),
        ]

    def paket_fiyatlari(self, request, object_id):
        grup = self.get_object(request, object_id)
        if grup is None:
            raise Http404("Fiyat grubu bulunamadı.")
        if not self.has_change_permission(request, grup):
            raise PermissionDenied

        paketler = (
            Paket.objects.select_related("kategori__operator")
            .prefetch_related("rotalar__saglayici")
            .order_by("kategori__operator__sira", "kategori__sira", "kategori__ad", "sira", "ad")
        )
        operator_id = request.GET.get("operator", "")
        kategori_id = request.GET.get("kategori", "")
        ara = request.GET.get("q", "").strip()[:60]
        pasif = request.GET.get("pasif") == "1"
        if not pasif:
            paketler = paketler.filter(aktif=True)
        if operator_id.isdigit():
            paketler = paketler.filter(kategori__operator_id=operator_id)
        if kategori_id.isdigit():
            paketler = paketler.filter(kategori_id=kategori_id)
        for kelime in ara.split():
            paketler = paketler.filter(Q(ad__icontains=kelime) | Q(kod__icontains=kelime))
        sayfa = Paginator(paketler, PAKET_FIYAT_SAYFASI).get_page(request.GET.get("sayfa"))
        sayfadakiler = list(sayfa.object_list)
        kayitlar = {k.paket_id: k for k in grup.paket_fiyatlari.filter(paket__in=sayfadakiler)}

        GrupFormu = forms.modelform_factory(
            FiyatGrubu,
            fields=("ad", "varsayilan", "aciklama"),
            widgets={"ad": UnfoldAdminTextInputWidget, "aciklama": UnfoldAdminTextInputWidget},
        )
        grup_formu = GrupFormu(request.POST if "_grup" in request.POST else None, instance=grup)
        if "_grup" in request.POST:
            if grup_formu.is_valid():
                grup_formu.save()
                self.message_user(request, f"{grup}: grup ayarları kaydedildi.", messages.SUCCESS)
                return HttpResponseRedirect(request.get_full_path())
            self.message_user(request, "Grup ayarları kaydedilmedi; hatayı düzeltin.", messages.ERROR)

        fiyat_postu = request.method == "POST" and "_grup" not in request.POST
        hatalar = {}
        if fiyat_postu:
            yazilacak = []
            for paket in sayfadakiler:
                try:
                    yazilacak.append((paket, _ondalik(request.POST.get(f"fiyat_{paket.pk}", ""))))
                except (InvalidOperation, ValueError):
                    hatalar[paket.pk] = "Rakam anlaşılamadı."
            if not hatalar:
                degisen = 0
                with transaction.atomic():
                    for paket, fiyat in yazilacak:
                        kayit = kayitlar.get(paket.pk)
                        if fiyat is None:
                            if kayit:
                                kayit.delete()
                                degisen += 1
                        elif kayit is None:
                            PaketFiyati.objects.create(paket=paket, grup=grup, fiyat=fiyat)
                            degisen += 1
                        elif kayit.fiyat != fiyat:
                            kayit.fiyat = fiyat
                            kayit.save(update_fields=["fiyat"])
                            degisen += 1
                self.message_user(request, f"{grup}: {degisen} paketin fiyatı kaydedildi.", messages.SUCCESS)
                return HttpResponseRedirect(request.get_full_path())
            self.message_user(request, "Bazı satırlar kaydedilmedi; kırmızı yazan satırları düzeltin.", messages.ERROR)

        satirlar = []
        for paket in sayfadakiler:
            kayit = kayitlar.get(paket.pk)
            if fiyat_postu:
                deger = request.POST.get(f"fiyat_{paket.pk}", "")
            else:
                deger = str(kayit.fiyat).replace(".", ",") if kayit else ""
            alis = paket.ilk_alis()
            satirlar.append(
                {
                    "paket": paket,
                    "alis": alis,
                    "kar": kayit.fiyat - alis if kayit and alis is not None else None,
                    "deger": deger,
                    "hata": hatalar.get(paket.pk, ""),
                }
            )

        sorgu = request.GET.copy()
        sorgu.pop("sayfa", None)
        return render(
            request,
            "admin/kontor/grup_paket_fiyatlari.html",
            {
                **self.admin_site.each_context(request),
                "title": f"{grup} · kontör fiyatları",
                "opts": self.model._meta,
                "grup": grup,
                "grup_formu": grup_formu,
                "satirlar": satirlar,
                "sayfa": sayfa,
                "sorgu": sorgu.urlencode(),
                "operatorler": Operator.objects.filter(kontor_kategorileri__isnull=False).distinct().order_by("sira", "ad"),
                "kategoriler": Kategori.objects.select_related("operator").order_by("oyun", "sira", "ad"),
                "secili_operator": operator_id,
                "secili_kategori": kategori_id,
                "ara": ara,
                "pasif": pasif,
            },
        )


# -- Paket ----------------------------------------------------------------


class RotaInline(TabularInline):
    model = Rota
    extra = 0
    fields = ("sira", "saglayici", "uzak_kod", "uzak_operator", "uzak_tip", "alis_fiyati", "aktif")
    verbose_name = "Sağlayıcı"
    verbose_name_plural = "Sağlayıcı sırası — küçük sıra önce denenir; boş kodlarda paketin kodu gider"


class SaglayiciyaEkleFormu(forms.Form):
    saglayici = forms.ModelChoiceField(
        Saglayici.objects.all(), label="Sağlayıcı", widget=UnfoldAdminSelectWidget
    )
    sira = forms.IntegerField(
        label="Sıra", min_value=1, initial=1, widget=UnfoldAdminTextInputWidget
    )
    uzak_operator = forms.CharField(
        label="Operatör kodu (boşsa kategorininki)", required=False, widget=UnfoldAdminTextInputWidget
    )
    uzak_tip = forms.CharField(
        label="Tip kodu (boşsa kategorininki)", required=False, widget=UnfoldAdminTextInputWidget
    )


# Paket listesinde her satır bütün grupları çizer; gruplar istek başına bir
# kez okunur (ModelAdmin tek nesnedir, iş parçacıkları arasında paylaşılır).
_GRUPLAR = ContextVar("kontor_fiyat_gruplari", default=None)


def _gruplar():
    gruplar = _GRUPLAR.get()
    if gruplar is None:
        gruplar = list(FiyatGrubu.objects.all())
    return gruplar


@admin.register(Paket)
class PaketAdmin(ModelAdmin):
    list_display = (
        "ad",
        "kategori",
        "kod",
        "icerik_gosterimi",
        "alis_gosterimi",
        "grup_fiyatlari",
        "tavsiye_fiyati",
        "rota_gosterimi",
        "aktif",
    )
    list_editable = ("tavsiye_fiyati", "aktif")
    list_filter = ("aktif", "kategori__operator", "kategori", "rotalar__saglayici")
    search_fields = ("ad", "kod", "kategori__ad")
    list_per_page = 50
    # Grup fiyatı burada satır içi tablo olarak da duruyordu; aynı rakam
    # grubun sayfasında da girildiği için yönetici "bu ne işe yarıyor?" dedi.
    # Bayinin fiyatı tek yerden girilir: grubun sayfası. Burada yalnızca okunur.
    inlines = (RotaInline,)
    actions = ("saglayiciya_ekle", "tavsiyeyi_operatorden_al")
    readonly_fields = ("grup_fiyatlari", "satis_durumu")

    def get_fieldsets(self, request, obj=None):
        fiyat = ["tavsiye_fiyati", "grup_fiyatlari"]
        aciklama = (
            "Bayinin ödeyeceği tutar <b>Kontör → Fiyat Grupları</b>'nda grubun sayfasından "
            "girilir; fiyatı yazılmayan grup bu paketi göremez. "
            "<b>Tavsiye Satış</b> bayinin müşteriye söyleyeceği fiyattır; bayi ekranında "
            "büyük rakam odur, aradaki fark bayinin kazancı olarak göz düğmesinin arkasında durur."
        )
        # Varsayılan grup yoksa grupsuz bayi paketin kendi fiyatını öder; o
        # zaman alan gerekir. Varsayılan grup varken hiçbir bayiye uymaz, gizlenir.
        if FiyatGrubu.varsayilani() is None:
            fiyat.append("satis_fiyati")
        ust = ("satis_durumu",) if obj is not None else ()
        return (
            (None, {"fields": ust + ("kategori", "kod", "ad", "aciklama", "sira", "aktif")}),
            ("İçerik", {"fields": (("dakika", "internet_mb", "sms", "gun"),)}),
            ("Fiyat", {"fields": fiyat, "description": aciklama}),
        )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("kategori")
            .prefetch_related("rotalar__saglayici", "grup_fiyatlari")
        )

    def changelist_view(self, request, extra_context=None):
        belirtec = _GRUPLAR.set(list(FiyatGrubu.objects.all()))
        try:
            return super().changelist_view(request, extra_context)
        finally:
            _GRUPLAR.reset(belirtec)

    def _ilk_rota(self, obj):
        rotalar = [r for r in obj.rotalar.all() if r.aktif and r.saglayici.aktif]
        return rotalar[0] if rotalar else None

    @display(description="İçerik")
    def icerik_gosterimi(self, obj):
        return obj.icerik or "—"

    @display(description="Alış")
    def alis_gosterimi(self, obj):
        rota = self._ilk_rota(obj)
        if rota is None or rota.alis_fiyati is None:
            return format_html('<span style="color:#D42046">girilmedi</span>')
        return format_html(
            '{}<br><span style="color:#6F7B8F;font-size:.7rem">{}</span>', rota.alis_fiyati, rota.saglayici
        )

    @display(description="Bayiye satış · kâr")
    def grup_fiyatlari(self, obj):
        """Her grubun ödeyeceği ve bizim kârımız; hesap `grup_fiyati`ndan, bayi ekranıyla aynı."""
        if obj is None or obj.pk is None:
            return "—"
        gruplar = _gruplar()
        if not gruplar:
            fiyat = obj.satis_fiyati
            return fiyat if fiyat else format_html('<span style="color:#D42046">fiyat yok — satılmaz</span>')
        alis = obj.ilk_alis()
        ozel = {f.grup_id: f.fiyat for f in obj.grup_fiyatlari.all()}
        satirlar = []
        for grup in gruplar:
            fiyat = ozel.get(grup.pk)
            if fiyat is None:
                satirlar.append((grup.ad, "—", "", "#94A3B8", ""))
                continue
            kar = fiyat - alis if alis is not None else None
            renk = "#0F8A4D" if kar is None or kar > 0 else "#D42046"
            kar_metni = f"{'+' if kar > 0 else ''}{kar}" if kar is not None else ""
            satirlar.append((grup.ad, fiyat, kar_metni, renk, ""))
        return format_html_join(
            format_html("<br>"),
            '<span style="white-space:nowrap">{}: <b>{}</b> <span style="color:{}">{}</span>'
            '<span style="color:#6F7B8F;font-size:.7rem">{}</span></span>',
            ((ad, fiyat, renk, kar, not_) for ad, fiyat, kar, renk, not_ in satirlar),
        )

    @display(description="Bayiye görünüyor mu?")
    def satis_durumu(self, obj):
        """Paketin bayi ekranına çıkmasının şartlarını tek tek sayar.

        "Bayi kontörü göremiyor" şikâyetinde sebep çoğu zaman bağlı sağlayıcı
        olmamasıydı; liste sütununda yazıyordu ama paket sayfasında yoktu.
        """
        if obj is None or obj.pk is None:
            return "—"
        eksikler = []
        if not obj.aktif:
            eksikler.append("Paket pasif.")
        if not obj.kategori.aktif:
            eksikler.append(f"“{obj.kategori}” kategorisi pasif.")
        rotalar = list(obj.rotalar.all())
        if not rotalar:
            eksikler.append(
                "Hiçbir sağlayıcıya bağlı değil — yüklemeyi yapacak kimse yok. Aşağıdaki "
                "Sağlayıcı sırası tablosuna “Başka bir Sağlayıcı ekle” ile sağlayıcıyı ekleyin."
            )
        elif not any(r.aktif and r.saglayici.aktif for r in rotalar):
            eksikler.append("Bağlı sağlayıcıların hepsi kapalı (satırda ya da Sağlayıcılar ekranında).")
        gruplar = _gruplar()
        fiyatli = {f.grup_id for f in obj.grup_fiyatlari.all()}
        if gruplar and not fiyatli:
            eksikler.append("Hiçbir fiyat grubunda Bayi Satış Tutarı yazılı değil.")
        if not gruplar and not obj.satis_fiyati:
            eksikler.append("Fiyatı yok.")
        if not eksikler:
            satilan = [g.ad for g in gruplar if g.pk in fiyatli] if gruplar else []
            return format_html(
                '<b style="color:#0F8A4D">Evet</b>{}',
                f" — {', '.join(satilan)} grubundaki bayiler görür." if satilan else "",
            )
        return format_html(
            '<b style="color:#D42046">Hayır</b><ul style="margin:.25rem 0 0 1rem;list-style:disc">{}</ul>',
            format_html_join("", "<li>{}</li>", ((e,) for e in eksikler)),
        )

    @display(description="Sağlayıcı sırası")
    def rota_gosterimi(self, obj):
        rotalar = list(obj.rotalar.all())
        if not rotalar:
            return format_html('<b style="color:#D42046">yok — satılmaz</b>')
        return format_html_join(
            " → ",
            '<span style="{}">{}</span>',
            (
                ("" if r.aktif and r.saglayici.aktif else "color:#94A3B8;text-decoration:line-through", r.saglayici.ad)
                for r in rotalar
            ),
        )

    def _ara_form(self, request, queryset, form, baslik, aciklama, eylem):
        return render(
            request,
            "admin/kontor/toplu_form.html",
            {
                **self.admin_site.each_context(request),
                "title": baslik,
                "aciklama": aciklama,
                "form": form,
                "secilenler": queryset,
                "eylem": eylem,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Seçili paketleri bir sağlayıcının sırasına ekle")
    def saglayiciya_ekle(self, request, queryset):
        """Eski sistemdeki "API'ye bütün kontörleri ekle"nin karşılığı.

        Rota zaten varsa sırası ve kodları güncellenir, yenisi açılmaz.
        Kod boş kalır — paketin kendi kodu gider; farklıysa satırda düzeltilir.
        Alış **Sağlayıcı Alışları** ekranından toplu girilir.
        """
        form = SaglayiciyaEkleFormu(request.POST if "uygula" in request.POST else None)
        if "uygula" in request.POST and form.is_valid():
            veri = form.cleaned_data
            eklenen = guncellenen = 0
            for paket in queryset:
                _, yeni = Rota.objects.update_or_create(
                    paket=paket,
                    saglayici=veri["saglayici"],
                    defaults={
                        "sira": veri["sira"],
                        "uzak_operator": veri["uzak_operator"].strip(),
                        "uzak_tip": veri["uzak_tip"].strip(),
                    },
                )
                eklenen += yeni
                guncellenen += not yeni
            self.message_user(
                request,
                f"{veri['saglayici']}: {eklenen} pakete eklendi, {guncellenen} paketin sırası güncellendi. "
                "Alışları Sağlayıcı Alışları ekranından girin.",
                messages.SUCCESS,
            )
            return None
        return self._ara_form(
            request,
            queryset,
            form,
            "Sağlayıcı sırasına ekle",
            "Seçili paketler bu sağlayıcıya da gidebilir hâle gelir. Sıra küçükse önce o denenir.",
            "saglayiciya_ekle",
        )

    @admin.action(description="Tavsiye fiyatını operatörün fiyatından al")
    def tavsiyeyi_operatorden_al(self, request, queryset):
        """Numara sorgusunda görülen operatör fiyatını tavsiye olarak yazar."""
        guncellenen, atlanan = tavsiyeyi_operatorden_al(queryset)
        mesaj = f"{guncellenen} paketin tavsiye fiyatı operatörün fiyatından yazıldı."
        if atlanan:
            mesaj += (
                f" {atlanan} paket operatör sorgusunda hiç görülmedi; onların tavsiyesini "
                "elle girin."
            )
        self.message_user(request, mesaj, messages.SUCCESS if not atlanan else messages.WARNING)


# -- İşlem ----------------------------------------------------------------


class DenemeInline(TabularInline):
    model = Deneme
    extra = 0
    can_delete = False
    fields = (
        "olusturma_tarihi", "saglayici", "ref", "uzak_ref", "uzak_kod", "durum", "elle",
        "alis", "gonderim_cevabi", "sonuc_cevabi",
    )
    readonly_fields = fields
    verbose_name_plural = "Gönderimler — her satır sağlayıcıya giden tek bir istektir"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Islem)
class IslemAdmin(ModelAdmin):
    list_display = (
        "olusturma_tarihi",
        "referans",
        "bayi_gosterimi",
        "hedef",
        "paket_gosterimi",
        "tutar_gosterimi",
        "alis_tutari",
        "kar_gosterimi",
        "durum_rozeti",
        "saglayici",
        "kanal",
        "karar_dugmesi",
    )
    list_filter = (
        "durum",
        "kanal",
        "saglayici",
        "kategori",
        ("olusturma_tarihi", GunAraligiFiltresi),
    )
    list_filter_submit = True
    search_fields = (
        "hedef",
        "siparis__referans_no",
        "bayi_ref",
        "denemeler__ref",
        "denemeler__uzak_ref",
        "bayi__username",
        "bayi__first_name",
        "bayi__last_name",
        "bayi__bayi_profili__unvan",
    )
    date_hierarchy = "olusturma_tarihi"
    list_per_page = 50
    inlines = (DenemeInline,)
    readonly_fields = (
        "siparis", "bayi", "kategori", "paket", "paket_adi", "hedef", "kanal", "bayi_ref", "durum",
        "sonuc_mesaji", "saglayici", "alis_tutari", "sonuc_tarihi", "olusturma_tarihi",
    )
    fieldsets = (
        (
            "İşlem",
            {
                "fields": (
                    ("bayi", "kanal"), ("kategori", "paket"), "paket_adi", "hedef", "bayi_ref",
                    "siparis", "olusturma_tarihi",
                ),
            },
        ),
        (
            "Sonuç",
            {
                "fields": ("durum", "saglayici", "alis_tutari", "sonuc_mesaji", "sonuc_tarihi"),
                "description": (
                    "Durum elle değiştirilmez: para ve sağlayıcı ona bağlı. Karar vermek için "
                    "listedeki ya da sayfanın üstündeki <b>Karar</b> düğmesini kullanın."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("siparis", "bayi", "bayi__bayi_profili", "kategori", "saglayici")
            .distinct()
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description="Referans", ordering="siparis__referans_no")
    def referans(self, obj):
        return obj.siparis.referans_no

    @display(description="Bayi", ordering="bayi__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.bayi)

    @display(description="Paket")
    def paket_gosterimi(self, obj):
        return format_html(
            '{}<br><span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            obj.paket_adi,
            obj.kategori.ad if obj.kategori else "",
        )

    @display(description="Tutar", ordering="siparis__tutar")
    def tutar_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.siparis.tutar)

    @display(description="Kâr")
    def kar_gosterimi(self, obj):
        kar = obj.kar
        if kar is None:
            return ""
        return format_html('<span style="color:{}">{}</span>', "#0F8A4D" if kar >= 0 else "#D42046", kar)

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        return _rozet(obj.get_durum_display(), DURUM_RENKLERI.get(obj.durum, "#6F7B8F"))

    @display(description="")
    def karar_dugmesi(self, obj):
        """Açık işlemde karar ekranına gider; askıdaki kırmızı yazılır."""
        if obj.durum == IslemDurumu.IPTAL:
            return ""
        renk = "#D42046" if obj.durum == IslemDurumu.ASKIDA else "#0D1320"
        return _baglanti_dugmesi(reverse("admin:kontor_islem_karar", args=[obj.pk]), "Karar", renk)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/karar/",
                self.admin_site.admin_view(_atomik_degil(self.karar)),
                name="kontor_islem_karar",
            ),
            *super().get_urls(),
        ]

    def karar(self, request, object_id):
        """Yöneticinin askıdaki (ya da süren) işlem için vereceği karar.

        Her düğme POST'tur ve ne yapacağını üstünde yazar. **Sıradakine
        gönder** tek bilinçli yeniden gönderim yoludur ve iki kez yükleme
        riski taşır: ekran önce "Sonucu sorgula"yı önerir.
        """
        islem = self.get_object(request, object_id)
        if islem is None:
            raise Http404("İşlem bulunamadı.")
        geri = reverse("admin:kontor_islem_karar", args=[islem.pk])

        if request.method == "POST":
            karar = request.POST.get("karar")
            try:
                if karar == "sorgula":
                    sonuc = sonucu_sorgula(islem)
                    metin = {
                        "basarili": ("Sağlayıcı “yüklendi” dedi; işlem kapandı.", messages.SUCCESS),
                        "islemde": ("Sağlayıcı “işlemde” dedi; sonuç kendiliğinden takip ediliyor.", messages.INFO),
                        "iptal": (
                            "Sağlayıcı “iptal/yüklenmedi” dedi. İşlem sürüyorduysa sıradakine gönderildi; "
                            "askıdaysa kararı siz verin (sıradakine gönder ya da iade et).",
                            messages.WARNING,
                        ),
                    }[sonuc]
                    self.message_user(request, *metin)
                elif karar == "yuklendi":
                    alis = _tutar(request.POST.get("alis"))
                    yuklendi_say(
                        islem, alis=alis, mesaj=request.POST.get("mesaj", ""), olusturan=request.user
                    )
                    self.message_user(request, "İşlem yüklendi olarak kapatıldı.", messages.SUCCESS)
                elif karar == "iptal":
                    iptal_et(islem, mesaj=request.POST.get("mesaj", "").strip(), olusturan=request.user)
                    self.message_user(
                        request, f"İşlem iptal edildi; {islem.siparis.tutar} ₺ bayiye iade edildi.", messages.WARNING
                    )
                elif karar == "gonder":
                    saglayici = Saglayici.objects.filter(pk=request.POST.get("saglayici")).first()
                    if saglayici is None:
                        raise KararVerilemez("Sağlayıcı seçilmedi.")
                    deneme = elle_gonder(islem, saglayici, olusturan=request.user)
                    self.message_user(
                        request,
                        f"{saglayici}: {deneme.get_durum_display()}. {deneme.gonderim_cevabi[:200]}",
                        messages.INFO,
                    )
                else:
                    raise KararVerilemez("Bilinmeyen karar.")
            except (KararVerilemez, IslemMesgul) as hata:
                self.message_user(request, str(hata), messages.ERROR)
            return HttpResponseRedirect(geri)

        islem.refresh_from_db()
        denemeler = list(islem.denemeler.select_related("saglayici"))
        denenen = {d.saglayici_id for d in denemeler}
        rotalar = (
            list(Rota.objects.filter(paket_id=islem.paket_id).select_related("saglayici"))
            if islem.paket_id
            else []
        )
        saglayicilar = [
            {"saglayici": r.saglayici, "denendi": r.saglayici_id in denenen, "rota": r}
            for r in rotalar
            if r.saglayici.aktif
        ]
        return render(
            request,
            "admin/kontor/islem_karar.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Kontör işlemi · {islem.siparis.referans_no}",
                "opts": self.model._meta,
                "islem": islem,
                "denemeler": denemeler,
                "saglayicilar": saglayicilar,
                "belirsiz_var": any(d.durum in ("belirsiz", "gonderiliyor", "islemde") for d in denemeler),
                "durum_rengi": DURUM_RENKLERI.get(islem.durum, "#6F7B8F"),
            },
        )


def _tutar(metin):
    metin = (metin or "").strip().replace(",", ".")
    if not metin:
        return None
    try:
        return Decimal(metin).quantize(Decimal("0.01"))
    except Exception:
        return None


# -- Bayi API'si ----------------------------------------------------------


@admin.register(ApiErisimi)
class ApiErisimiAdmin(ModelAdmin):
    list_display = ("bayi_gosterimi", "bayi_kodu", "aktif", "anahtar_durumu", "son_kullanim", "sifre_dugmesi")
    list_filter = ("aktif",)
    search_fields = ("bayi_kodu", "kullanici__username", "kullanici__first_name", "kullanici__last_name")
    fields = ("kullanici", "bayi_kodu", "aktif", "son_kullanim")
    readonly_fields = ("son_kullanim",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        return _kullanici_kutusunu_sadelestir(super().formfield_for_foreignkey(db_field, request, **kwargs))

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("kullanici", "kullanici__bayi_profili")

    @display(description="Bayi", ordering="kullanici__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.kullanici)

    @display(description="Şifre")
    def anahtar_durumu(self, obj):
        if obj.anahtar_ozeti:
            return format_html('<span style="color:#0F8A4D">var</span>')
        return format_html('<b style="color:#D42046">üretilmedi</b>')

    @display(description="")
    def sifre_dugmesi(self, obj):
        return _baglanti_dugmesi(reverse("admin:kontor_apierisimi_sifre", args=[obj.pk]), "Yeni şifre")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/sifre/",
                self.admin_site.admin_view(self.sifre),
                name="kontor_apierisimi_sifre",
            ),
            *super().get_urls(),
        ]

    def sifre(self, request, object_id):
        """Yeni API şifresi üretir ve bir kez gösterir. GET onay, POST üretim.

        Eski şifre anında geçersiz olur; bayinin programı yeni şifre
        yazılana kadar reddedilir.
        """
        erisim = self.get_object(request, object_id)
        if erisim is None:
            raise Http404("Erişim bulunamadı.")
        baglam = {
            **self.admin_site.each_context(request),
            "title": "Bayi API şifresi",
            "opts": self.model._meta,
            "erisim": erisim,
            "adres": request.build_absolute_uri("/").rstrip("/"),
        }
        if request.method == "POST":
            baglam["sifre"] = erisim.yeni_anahtar()
        return render(request, "admin/kontor/api_sifre.html", baglam)
