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
from django.db import models, transaction
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
    BayiRotasi,
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
)
from apps.kontor.saglayicilar import SaglayiciHatasi
from apps.kontor.services import (
    IslemMesgul,
    KararVerilemez,
    elle_gonder,
    fiyat_listesini_cek,
    grup_fiyati,
    gorulen_paketi_kataloga_ekle,
    ISLEM_AYNEN,
    ISLEM_TUTAR,
    ISLEM_YUZDE,
    TABAN_ALIS,
    TABAN_OPERATOR,
    operator_fiyatlari,
    tavsiyeyi_hesapla,
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
    # Formun altında, formun dışında: paketlerin karşı sitedeki kodu ve alışı.
    change_form_outer_after_template = "admin/kontor/saglayici_paketleri.html"
    list_display = ("ad", "tur_gosterimi", "aktif", "adres", "rota_sayisi", "son_24_saat", "islem_dugmeleri")
    list_filter = ("aktif", "tur")
    readonly_fields = ("son_liste_cekme",)
    fieldsets = (
        (
            "Sağlayıcı",
            {
                "fields": ("ad", "tur", "aktif"),
                "description": (
                    "İşlemleri ilettiğimiz bayi sistemi. Paketlerin bu sitedeki kodu ve alışı "
                    "sayfanın altındaki <b>Paketler</b> tablosundan girilir; sıra paketin kendi "
                    "sayfasındadır. Kapatılan sağlayıcıya hiçbir işlem gitmez, sıradaki denenir."
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
        """Sağlayıcının paketleri: kodları ve alışları sağlayıcının sayfasında girilir."""
        adres = reverse("admin:kontor_saglayici_change", args=[obj.pk]) + "#paketler"
        return format_html('<a href="{}">{} paket · kodlar ve alışlar</a>', adres, obj._rota)

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

    # -- Paketler tablosu --------------------------------------------------
    #
    # Karşı sitenin paket kodu ve alışı eskiden paketin sayfasındaki sağlayıcı
    # tablosunda ve ayrı bir "Sağlayıcı Alışları" listesinde giriliyordu.
    # Yönetici bir sağlayıcının kodlarını onun listesine bakarak giriyor:
    # yeri sağlayıcının sayfasıdır. Bizim kod salt okunur (paketin kimliği,
    # bayi programları onunla ister). Liste operatör seçilmeden gelmez ve
    # sayfa başı 50'dir — bir operatörde bin paket olabilir.

    def _paket_tablosu(self, request, saglayici):
        operator_id = request.GET.get("operator", "")
        kategori_id = request.GET.get("kategori", "")
        ara = request.GET.get("q", "").strip()[:60]
        operatorler = list(
            Operator.objects.filter(kontor_kategorileri__isnull=False).distinct().order_by("sira", "ad")
        )
        tablo = {
            "operatorler": operatorler,
            "kategoriler": list(
                Kategori.objects.filter(operator_id=operator_id).order_by("sira", "ad") if operator_id.isdigit() else []
            ),
            "secili_operator": operator_id,
            "secili_kategori": kategori_id,
            "ara": ara,
            "satirlar": None,
        }
        if not operator_id.isdigit():
            return tablo
        paketler = (
            Paket.objects.filter(kategori__operator_id=operator_id)
            .select_related("kategori")
            .order_by("kategori__sira", "kategori__ad", "sira", "ad")
        )
        if kategori_id.isdigit():
            paketler = paketler.filter(kategori_id=kategori_id)
        for kelime in ara.split():
            paketler = paketler.filter(Q(ad__icontains=kelime) | Q(kod__icontains=kelime))
        sayfa = Paginator(paketler, PAKET_FIYAT_SAYFASI).get_page(request.GET.get("sayfa"))
        rotalar = {
            r.paket_id: r for r in Rota.objects.filter(saglayici=saglayici, paket__in=list(sayfa.object_list))
        }
        sorgu = request.GET.copy()
        sorgu.pop("sayfa", None)
        tablo.update(
            satirlar=[{"paket": p, "rota": rotalar.get(p.pk)} for p in sayfa.object_list],
            sayfa=sayfa,
            sorgu=sorgu.urlencode(),
            kaydet_url=reverse("admin:kontor_saglayici_paketler", args=[saglayici.pk]) + "?" + request.GET.urlencode(),
        )
        return tablo

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        saglayici = self.get_object(request, object_id)
        if saglayici is not None:
            extra_context["paket_tablosu"] = self._paket_tablosu(request, saglayici)
        return super().change_view(request, object_id, form_url, extra_context)

    def paketleri_kaydet(self, request, object_id):
        """Tablonun POST'u: karşı site kodu, alış ve "bu sağlayıcıya gönder".

        Rotası olmayan pakete kod ya da alış yazılırsa rota açılır (sıranın
        sonuna); "Gönder" işaretliyse paket bu sağlayıcıya da gider — ekran
        kod yazılınca kutuyu kendiliğinden işaretler, yönetici kaldırabilir. Karşı kod bizimkiyle aynı
        ya da boşsa saklanmaz — boş kod paketin kendi kodunun gideceği demek.
        Yalnızca bu sayfadaki paketler yazılır.
        """
        saglayici = self.get_object(request, object_id)
        if saglayici is None:
            raise Http404("Sağlayıcı bulunamadı.")
        if not self.has_change_permission(request, saglayici):
            raise PermissionDenied
        geri = reverse("admin:kontor_saglayici_change", args=[saglayici.pk]) + "?" + request.GET.urlencode() + "#paketler"
        if request.method != "POST":
            return HttpResponseRedirect(geri)
        pkler = [int(p) for p in request.POST.getlist("paket") if p.isdigit()]
        paketler = {p.pk: p for p in Paket.objects.filter(pk__in=pkler)}
        rotalar = {r.paket_id: r for r in Rota.objects.filter(saglayici=saglayici, paket_id__in=paketler)}
        yazilacak, hatalar = [], []
        for pk, paket in paketler.items():
            uzak = request.POST.get(f"kod_{pk}", "").strip()[:60]
            if uzak == paket.kod:
                uzak = ""
            try:
                alis = _ondalik(request.POST.get(f"alis_{pk}", ""))
            except (InvalidOperation, ValueError):
                hatalar.append(paket.ad)
                continue
            gonder = request.POST.get(f"gonder_{pk}") == "1"
            yazilacak.append((paket, uzak, alis, gonder))
        if hatalar:
            self.message_user(
                request, f"Alışı anlaşılamayan satırlar kaydedilmedi: {', '.join(hatalar)}", messages.ERROR
            )
            return HttpResponseRedirect(geri)
        acilan = degisen = 0
        with transaction.atomic():
            for paket, uzak, alis, gonder in yazilacak:
                rota = rotalar.get(paket.pk)
                if rota is None:
                    if not (gonder or uzak or alis is not None):
                        continue
                    son = Rota.objects.filter(paket=paket).order_by("-sira").values_list("sira", flat=True).first()
                    Rota.objects.create(
                        paket=paket, saglayici=saglayici, sira=(son or 0) + 1,
                        uzak_kod=uzak, alis_fiyati=alis, aktif=gonder,
                    )
                    acilan += 1
                    continue
                if (rota.uzak_kod, rota.alis_fiyati, rota.aktif) != (uzak, alis, gonder):
                    rota.uzak_kod, rota.alis_fiyati, rota.aktif = uzak, alis, gonder
                    rota.save(update_fields=["uzak_kod", "alis_fiyati", "aktif"])
                    degisen += 1
        mesaj = f"{saglayici}: {degisen} paket güncellendi"
        if acilan:
            mesaj += f", {acilan} paket bu sağlayıcıya bağlandı"
        self.message_user(request, mesaj + ".", messages.SUCCESS)
        return HttpResponseRedirect(geri)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/paketler/",
                self.admin_site.admin_view(self.paketleri_kaydet),
                name="kontor_saglayici_paketler",
            ),
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


@admin.register(BayiRotasi)
class BayiRotasiAdmin(ModelAdmin):
    """Bütün bayilerin özel sağlayıcı sıraları tek listede.

    Günlük giriş bayinin kullanıcı sayfasındaki tablodandır; burası "hangi
    bayinin Turkcell'i nereye gidiyor" sorusuna tek ekrandan bakmak için.
    """

    list_display = ("bayi_gosterimi", "kategori", "saglayici", "sira", "aktif")
    list_editable = ("sira", "aktif")
    list_filter = ("kategori", "saglayici", "aktif")
    search_fields = ("bayi__username", "bayi__first_name", "bayi__last_name", "bayi__bayi_profili__unvan")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi", "bayi__bayi_profili", "kategori", "saglayici")

    @display(description="Bayi", ordering="bayi__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.bayi)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        alan = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "bayi":
            # Seçimin yanındaki sil düğmesi kullanıcının kendisini siler (CLAUDE.md).
            for ad in ("can_add_related", "can_change_related", "can_delete_related", "can_view_related"):
                setattr(alan.widget, ad, False)
        return alan


# Sağlayıcının çekilen fiyat listesi (`SaglayiciPaketi`) yönetimde listelenmez:
# hiçbir yere bağlı değildi, rota alışları çekim sırasında doğrudan güncellenir.
# Yönetici "bunu göstermeye gerek yok" dedi.


# -- Görülen paketler -------------------------------------------------------


class KatalogFiltresi(admin.SimpleListFilter):
    title = "Katalogda"
    parameter_name = "katalog"

    def lookups(self, request, model_admin):
        return (("yeni", "Yeni (eklenmedi)"), ("var", "Eklendi"), ("yok_say", "Yok sayılan"))

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
    ekle** (fiyatsız ve sağlayıcısız açılır; fiyatı grubun sayfasında
    yazılana kadar bayiye görünmez), satılmayacaksa **Yok say**.

    Menü **bütün** görülen paketleri açar, durum sütunu "Eklendi / Yeni /
    Yok sayıldı" der: bir süre yalnızca yeniler süzülüyordu, yönetici hangi
    paketi eklediğini göremiyordu. Liste kaynak + kod başına tekildir; aynı
    paket her sorguda yeniden yazılmaz, yalnızca güncellenir.
    """

    list_display = (
        "ad_gosterimi", "kod", "kategori", "fiyat_gosterimi", "ilk_gorulme", "son_gorulme",
        "katalog_durumu",
    )
    list_filter = (KatalogFiltresi, "kaynak", "kategori__operator", "kategori")
    search_fields = ("kod", "ad", "aciklama")
    readonly_fields = (
        "kaynak", "kod", "kategori", "ad", "aciklama", "fiyat", "onceki_fiyat", "fiyat_degisme",
        "ilk_gorulme", "son_gorulme",
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

    @display(description="Durum")
    def katalog_durumu(self, obj):
        if obj._katalog_pk:
            return format_html(
                '<a href="{}" style="color:#0F8A4D;font-weight:600">✓ Eklendi</a>',
                reverse("admin:kontor_paket_change", args=[obj._katalog_pk]),
            )
        if obj.yok_say:
            return format_html('<span style="color:#94A3B8">Yok sayıldı</span>')
        if obj.kategori_id is None:
            return format_html('<b style="color:#D42046">Yeni</b>')
        return format_html_join(
            " ",
            "{}",
            (
                (format_html('<b style="color:#D42046">Yeni</b>'),),
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
            f"“{paket.ad}” {'kataloğa eklendi' if yeni else 'zaten katalogdaydı'}. Fiyat grubunun "
            "sayfasında Bayi Satış Tutarını yazın, fiyatı olmadan bayiye görünmez. Sağlayıcıya "
            "bağlamazsanız alındığında işlem askıya düşer.",
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
    list_display = (
        "ad", "oyun", "operator", "hedef", "api_kodu", "paket_sayisi", "gonderim_oncesi_sorgu", "sira", "aktif",
    )
    # Göndermeden önce sorgu satırdan açılıp kapanır; her kategoride formu açmak gerekmesin.
    list_editable = ("gonderim_oncesi_sorgu", "sira", "aktif")
    list_filter = ("oyun", "aktif", "gonderim_oncesi_sorgu", "operator", "hedef")
    search_fields = ("ad", "api_operator", "api_tip")
    fieldsets = (
        (None, {"fields": ("ad", "slug", "oyun", "operator", "gorsel", "aciklama", "sira", "aktif")}),
        (
            "Yükleme",
            {
                "fields": ("hedef", "hedef_etiketi", "sorgu_kaynagi", "gonderim_oncesi_sorgu", "sorgu_sahibi_goster"),
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
        operator_fiyati = operator_fiyatlari(sayfadakiler)

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
                    "operator_fiyati": operator_fiyati.get(paket.pk),
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
    fields = ("sira", "saglayici", "uzak_kod", "alis_fiyati", "uzak_operator", "uzak_tip", "aktif")
    # Karşı site kodu ve alış sağlayıcının sayfasından girilir; burada görünür.
    readonly_fields = ("uzak_kod", "alis_fiyati")
    verbose_name = "Sağlayıcı"
    verbose_name_plural = (
        "Sağlayıcı sırası — küçük sıra önce denenir. Karşı site kodu ve alış "
        "sağlayıcının sayfasındaki Paketler tablosundan girilir."
    )


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


class TavsiyeHesapFormu(forms.Form):
    """Fiyat grubu sayfasındaki hesap aracının tavsiye satış için olanı."""

    taban = forms.ChoiceField(
        label="Neyin üstüne",
        choices=((TABAN_OPERATOR, "Operatör fiyatı (numara sorgusunda görülen)"), (TABAN_ALIS, "Alış (sıradaki ilk sağlayıcı)")),
        widget=UnfoldAdminSelectWidget,
    )
    islem = forms.ChoiceField(
        label="Hesap",
        choices=((ISLEM_AYNEN, "Aynen"), (ISLEM_YUZDE, "+ %"), (ISLEM_TUTAR, "+ ₺")),
        widget=UnfoldAdminSelectWidget,
    )
    deger = forms.DecimalField(
        label="Yüzde ya da tutar (eksi yazılırsa altına iner; “Aynen”de boş kalır)",
        required=False,
        max_digits=10,
        decimal_places=2,
        localize=True,
        widget=UnfoldAdminTextInputWidget(attrs={"inputmode": "decimal", "placeholder": "örn. 5"}),
    )

    def clean(self):
        veri = super().clean()
        if veri.get("islem") in (ISLEM_YUZDE, ISLEM_TUTAR) and veri.get("deger") is None:
            self.add_error("deger", "Yüzdeyi ya da tutarı yazın.")
        return veri


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
        "operator_fiyati_gosterimi",
        "tavsiye_fiyati",
        "rota_gosterimi",
        "aktif",
        "bayiye_gorunur",
    )
    list_editable = ("tavsiye_fiyati", "aktif", "bayiye_gorunur")
    list_filter = (
        "aktif", "bayiye_gorunur", "sorguda_hep_goster", "kategori__operator", "kategori", "rotalar__saglayici",
    )
    search_fields = ("ad", "kod", "kategori__ad")
    list_per_page = 50
    # Grup fiyatı burada satır içi tablo olarak da duruyordu; aynı rakam
    # grubun sayfasında da girildiği için yönetici "bu ne işe yarıyor?" dedi.
    # Bayinin fiyatı tek yerden girilir: grubun sayfası. Burada yalnızca okunur.
    inlines = (RotaInline,)
    actions = ("saglayiciya_ekle", "tavsiyeyi_hesapla")
    readonly_fields = ("grup_fiyatlari", "satis_durumu", "alternatif_listesi")

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
            (
                None,
                {
                    "fields": ust
                    + ("kategori", "kod", "ad", "aciklama", "sira", "aktif", "bayiye_gorunur", "sorguda_hep_goster")
                },
            ),
            ("İçerik", {"fields": (("dakika", "internet_mb", "sms", "gun"),)}),
            ("Fiyat", {"fields": fiyat, "description": aciklama}),
            (
                "Alternatif",
                {
                    "fields": ("alternatif_yapilmasin",) + (("alternatif_listesi",) if obj is not None else ()),
                    "description": (
                        "Bayi bu paketi aldığında, numara aynı içeriği ya da fazlasını daha ucuza "
                        "veren bir paketi alabiliyorsa o gönderilir; bayi yine bu paketin fiyatını "
                        "öder ve yalnızca bu paketi görür. Reddedilirse sıradaki, en son bu paket "
                        "denenir. Numara ne bunu ne alternatifi alabiliyorsa sağlayıcıya gidilmez, "
                        "tutar iade edilir. Yalnızca numara sorgusu olan kategorilerde çalışır."
                    ),
                },
            ),
        )

    def get_queryset(self, request):
        # Operatör fiyatı: `services.operator_fiyatlari` ile aynı eşleşme
        # (kategori + kod, en son görülen), listede satır başına sorgu atmasın.
        operator_fiyati = (
            GorulenPaket.objects.filter(kategori_id=OuterRef("kategori_id"), kod=OuterRef("kod"), fiyat__isnull=False)
            .order_by("-son_gorulme")
            .values("fiyat")[:1]
        )
        return (
            super()
            .get_queryset(request)
            .select_related("kategori")
            .prefetch_related("rotalar__saglayici", "grup_fiyatlari")
            .annotate(
                _operator_fiyati=Subquery(
                    operator_fiyati, output_field=models.DecimalField(max_digits=12, decimal_places=2)
                )
            )
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
            return format_html('<span style="color:#6F7B8F">—</span>')
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
            return fiyat if fiyat else format_html('<span style="color:#6F7B8F">fiyat yok</span>')
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

    @display(description="Alternatifleri")
    def alternatif_listesi(self, obj):
        """Şu anki alış fiyatlarıyla hesaplanan liste; saklanmaz."""
        if obj is None or obj.pk is None:
            return "—"
        if obj.alternatif_yapilmasin:
            return "Kapalı."
        if not obj.kategori.sorgu_kaynagi:
            return "Kategoride numara sorgusu yok; alternatif denenmez."
        alis = obj.ilk_alis()
        if alis is None:
            return "Bu paketin alışı yok; ucuzu hesaplanamaz."
        alternatifler = obj.alternatifleri()
        if not alternatifler:
            return "Aynı içeriği ya da fazlasını daha ucuza veren paket yok."
        return format_html(
            '<ol style="margin:0 0 0 1rem;list-style:decimal">{}</ol>',
            format_html_join(
                "",
                '<li>{} <span style="color:#6F7B8F">({} · alış {} ₺, {} ₺ ucuz)</span></li>',
                ((p.ad, p.icerik or p.kod, p.ilk_alis(), alis - p.ilk_alis()) for p in alternatifler),
            ),
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
        if not obj.bayiye_gorunur:
            eksikler.append(
                "“Bayiye görünür” kapalı. Aktif olduğu sürece başka paketin alternatifi olarak gönderilebilir."
            )
        # Sağlayıcı eksikliği bayiden saklamaz: işlem açılır, askıya düşer.
        notlar = []
        rotalar = list(obj.rotalar.all())
        if not any(r.aktif and r.saglayici.aktif for r in rotalar):
            notlar.append(
                "Açık bir sağlayıcıya bağlı değil: bayi alırsa işlem askıya düşer, "
                "yönetimden elle gönderilir ya da “Yüklendi say” denir."
            )
        gruplar = _gruplar()
        fiyatli = {f.grup_id for f in obj.grup_fiyatlari.all()}
        if gruplar and not fiyatli:
            eksikler.append("Hiçbir fiyat grubunda Bayi Satış Tutarı yazılı değil.")
        if not gruplar and not obj.satis_fiyati:
            eksikler.append("Fiyatı yok.")
        if not eksikler:
            satilan = [g.ad for g in gruplar if g.pk in fiyatli] if gruplar else []
            return format_html(
                '<b style="color:#0F8A4D">Evet</b>{}{}',
                f" — {', '.join(satilan)} grubundaki bayiler görür." if satilan else "",
                format_html('<br><span style="color:#6F7B8F">{}</span>', notlar[0]) if notlar else "",
            )
        return format_html(
            '<b style="color:#D42046">Hayır</b><ul style="margin:.25rem 0 0 1rem;list-style:disc">{}</ul>',
            format_html_join("", "<li>{}</li>", ((e,) for e in eksikler)),
        )

    @display(description="Sağlayıcı sırası")
    def rota_gosterimi(self, obj):
        rotalar = list(obj.rotalar.all())
        if not rotalar:
            return format_html('<span style="color:#6F7B8F">— (askıya düşer)</span>')
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
        Karşı site kodu ve alış sağlayıcının sayfasındaki Paketler tablosundan girilir.
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
                "Karşı site kodlarını ve alışları sağlayıcının sayfasından girin.",
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

    @display(description="Operatör fiyatı", ordering="_operator_fiyati")
    def operator_fiyati_gosterimi(self, obj):
        """Numara sorgusunda görülen fiyat; tavsiye çoğu zaman bunun üstüne kurulur."""
        if obj._operator_fiyati is None:
            return format_html('<span style="color:#6F7B8F">—</span>')
        return f"{obj._operator_fiyati:.2f}"

    @admin.action(description="Tavsiye satışı hesapla (operatör fiyatı / alış + %% / ₺)")
    def tavsiyeyi_hesapla(self, request, queryset):
        """Tavsiye satışı operatör fiyatından ya da alıştan hesaplayıp yazar.

        Fiyat grubu sayfasındaki hesap aracının aynısı; burada sonuç ara
        formdan sonra doğrudan kaydedilir. Tabanı olmayan pakete dokunulmaz.
        """
        form = TavsiyeHesapFormu(request.POST if "uygula" in request.POST else None)
        if "uygula" in request.POST and form.is_valid():
            veri = form.cleaned_data
            guncellenen, atlanan = tavsiyeyi_hesapla(
                queryset.prefetch_related("rotalar__saglayici"),
                taban=veri["taban"],
                islem=veri["islem"],
                deger=veri["deger"] or 0,
            )
            mesaj = f"{guncellenen} paketin tavsiye satışı hesaplanıp yazıldı."
            if atlanan:
                eksik = "operatör sorgusunda hiç görülmedi" if veri["taban"] == TABAN_OPERATOR else "alışı yok"
                mesaj += f" {atlanan} paket atlandı ({eksik}); onların tavsiyesi olduğu gibi kaldı."
            self.message_user(request, mesaj, messages.SUCCESS if not atlanan else messages.WARNING)
            return None
        return self._ara_form(
            request,
            queryset,
            form,
            "Tavsiye satışı hesapla",
            "Seçili paketlerin Tavsiye Satış'ı operatörün fiyatından ya da alıştan hesaplanıp kaydedilir. "
            "Operatör fiyatı numara sorgusunda görülen fiyattır; hiç görülmemiş paket atlanır.",
            "tavsiyeyi_hesapla",
        )


# -- İşlem ----------------------------------------------------------------


class DenemeInline(TabularInline):
    model = Deneme
    extra = 0
    can_delete = False
    fields = (
        "olusturma_tarihi", "saglayici", "paket", "ref", "uzak_ref", "uzak_kod", "durum", "elle",
        "alis", "gonderim_istegi", "gonderim_cevabi", "sonuc_istegi", "sonuc_cevabi",
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
        "gonderilen_gosterimi",
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
                "fields": (
                    "durum", "gonderilen_gosterimi", "saglayici", "alis_tutari", "sonuc_mesaji", "sonuc_tarihi",
                ),
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
            .select_related("siparis", "bayi", "bayi__bayi_profili", "kategori", "saglayici", "paket")
            .prefetch_related("denemeler__paket")
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
        alt = ""
        if obj.alternatif_gonderildi:
            alt = format_html(
                '<br><span style="color:#0F8A4D;font-size:.75rem">→ {} (alternatif)</span>',
                obj.gonderilen_paket.ad,
            )
        # Paket kodu yanında: sağlayıcı "kodu bulamadım" dediğinde hangi
        # paketin eşleşmesine bakılacağı listeden okunsun. Karşı siteye
        # başka kod gittiyse o da yazar.
        kod = obj.paket.kod if obj.paket else ""
        denemeler = list(obj.denemeler.all())
        giden = denemeler[-1].uzak_kod if denemeler else ""
        kod_metni = f"Kod {kod}" if kod else ""
        if giden and giden != kod:
            kod_metni = f"{kod_metni} → giden {giden}".strip()
        return format_html(
            '{}{}<br><span style="color:#6F7B8F;font-size:.75rem">{}{}{}</span>',
            obj.paket_adi,
            alt,
            obj.kategori.ad if obj.kategori else "",
            " · " if kod_metni else "",
            kod_metni,
        )

    @display(description="Gönderilen paket")
    def gonderilen_gosterimi(self, obj):
        """Bayi istediğini görür; burada yüklenen (ucuz alternatif olabilir) yazar."""
        paket = obj.gonderilen_paket
        if paket is None:
            return "—"
        if paket.pk == obj.paket_id:
            return format_html("{} <span style=\"color:#6F7B8F\">(istenen paket)</span>", paket.ad)
        return format_html(
            '<b style="color:#0F8A4D">{}</b> — alternatif; bayi “{}” görür, fiyatını öder.',
            paket.ad,
            obj.paket_adi,
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
        """İptalde ve askıda sebep rozetin altında: "neden?" için satırı açmak gerekmesin."""
        rozet = _rozet(obj.get_durum_display(), DURUM_RENKLERI.get(obj.durum, "#6F7B8F"))
        if obj.durum not in (IslemDurumu.IPTAL, IslemDurumu.ASKIDA) or not obj.sonuc_mesaji:
            return rozet
        return format_html(
            '{}<div style="margin-top:.25rem;max-width:22rem;font-size:.75rem;'
            'white-space:pre-wrap;overflow-wrap:anywhere;opacity:.75">{}</div>',
            rozet,
            obj.sonuc_mesaji,
        )

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
        denemeler = list(islem.denemeler.select_related("saglayici", "paket"))
        # Elle gönderim son gidenin paketiyle yapılır (alternatif olabilir);
        # sağlayıcı listesi de o paketin sırasıdır.
        son_paket_id = (denemeler[-1].paket_id if denemeler else None) or islem.paket_id
        denenen = {d.saglayici_id for d in denemeler if (d.paket_id or islem.paket_id) == son_paket_id}
        rotalar = (
            list(Rota.objects.filter(paket_id=son_paket_id).select_related("saglayici"))
            if son_paket_id
            else []
        )
        saglayicilar = [
            {"saglayici": r.saglayici, "denendi": r.saglayici_id in denenen, "rota": r}
            for r in rotalar
            if r.saglayici.aktif and r.aktif
        ]
        # Bayiye özel sağlayıcılar en üstte: işlem genel sıraya değil onlara gidiyordu.
        ozel = list(
            BayiRotasi.objects.filter(
                bayi_id=islem.bayi_id, kategori_id=islem.kategori_id, aktif=True, saglayici__aktif=True
            )
            .select_related("saglayici")
            .order_by("sira", "pk")
        )
        if ozel:
            rota_bul = {r.saglayici_id: r for r in rotalar}
            ustte = [
                {
                    "saglayici": o.saglayici,
                    "denendi": o.saglayici_id in denenen,
                    "rota": rota_bul.get(o.saglayici_id),
                    "bayiye_ozel": True,
                }
                for o in ozel
            ]
            ozel_idler = {o.saglayici_id for o in ozel}
            saglayicilar = ustte + [s for s in saglayicilar if s["saglayici"].pk not in ozel_idler]
        # Paket hiçbir açık sağlayıcıya bağlı değilse işlem buraya bu yüzden
        # düştü: bütün açık sağlayıcılar seçilebilir, paketin kendi kodu gider.
        baglisiz = not saglayicilar
        if baglisiz:
            saglayicilar = [
                {"saglayici": sg, "denendi": sg.pk in denenen, "rota": None}
                for sg in Saglayici.objects.filter(aktif=True).order_by("ad")
            ]
        return render(
            request,
            "admin/kontor/islem_karar.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Kontör işlemi · {islem.siparis.referans_no}",
                "opts": self.model._meta,
                "baglisiz": baglisiz,
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
