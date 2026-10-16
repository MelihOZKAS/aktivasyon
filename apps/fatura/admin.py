from decimal import InvalidOperation

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from unfold.widgets import UnfoldAdminPasswordWidget, UnfoldAdminTextInputWidget

from apps.bayi.etiket import kullanici_etiketi_html
from apps.fatura import fiyat as fatura_fiyat
from apps.fatura.models import (
    FaturaFiyatGrubu,
    GonderimDurumu,
    GrupFiyati,
    Kategori,
    Kurum,
    Odeme,
    OdemeDurumu,
    Robot,
    RobotHesabi,
    Sorgu,
    SorguDurumu,
)
from apps.fatura.services import (
    OTOMATIK_GONDERIM_SURESI,
    FaturaHatasi,
    KararVerilemez,
    fiyat_grubu,
    gonderim_engeli,
    iptal_et,
    kurumlari_eslestir,
    odemeyi_gonder,
    odendi_isaretle,
    sonucu_sorgula,
    yonetim_bekleyenler,
)
from apps.filtreler import GunAraligiFiltresi

GRI = "#6F7B8F"
DUGME_STILI = (
    "display:inline-block;padding:.3rem .7rem;border-radius:.4rem;background:{};"
    "color:#fff;font-size:.75rem;font-weight:600;white-space:nowrap"
)


def _rozet(metin, renk):
    return format_html(
        '<span style="background:{};color:#fff;padding:.15rem .6rem;border-radius:999px;'
        'font-size:.75rem;font-weight:600;white-space:nowrap">{}</span>',
        renk,
        metin,
    )


def _dugme(adres, metin, renk="#0D1320"):
    return format_html('<a href="{}" style="{}">{}</a>', adres, format_html(DUGME_STILI, renk), metin)


def _soluk(metin):
    return format_html('<span style="color:{}">{}</span>', GRI, metin)


def _atomik_degil(gorunum):
    """Sağlayıcıyla konuşan yönetim ekranı istek transaction'ının dışında.

    `ATOMIC_REQUESTS` açık; gönderim kaydı ağa çıkmadan commit edilmezse
    süreç düştüğünde kaybolur ve fatura ikinci kez ödenirdi (kontördeki gibi).
    """

    def sarmalayici(*args, **kwargs):
        return gorunum(*args, **kwargs)

    return transaction.non_atomic_requests(sarmalayici)


# -- Katalog -------------------------------------------------------------


@admin.register(Kategori)
class KategoriAdmin(ModelAdmin):
    list_display = ("ad", "kurum_sayisi", "ikon", "sira", "aktif")
    list_editable = ("ikon", "sira", "aktif")
    search_fields = ("ad",)
    fields = ("ad", "slug", "ikon", "sira", "aktif")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_kurum=Count("kurumlar"))

    @display(description="Kurum", ordering="_kurum")
    def kurum_sayisi(self, obj):
        adres = reverse("admin:fatura_kurum_changelist") + f"?kategori__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', adres, obj._kurum)


@admin.register(Kurum)
class KurumAdmin(ModelAdmin):
    """Fatura kurumu — kontördeki paket ekranının aynısı.

    Bayinin ödeyeceği **fiyat grubunun sayfasından** girilir (Fatura → Fiyat
    Grupları → grup); burada yalnızca okunur, aynı rakam
    iki yerden girilmesin. "Müşteriye" kontördeki tavsiye satış gibi listede
    satırdan düzenlenir ve gruba göre değişmez.
    """

    list_display = (
        "ad", "kod", "uzak_id", "kategori", "sorgulu", "kural", "tavsiye", "grup_fiyatlari_gosterimi", "sira", "aktif",
    )
    list_editable = ("uzak_id", "kategori", "sorgulu", "tavsiye", "sira", "aktif")
    list_filter = ("aktif", "sorgulu", "kategori", ("uzak_id", admin.EmptyFieldListFilter))
    search_fields = ("ad", "kod", "uzak_id")
    list_per_page = 50
    # Listenin üstünde "Sağlayıcıdan eşleştir": kurum numaralarını API'nin listesinden doldurur.
    change_list_template = "admin/fatura/kurum/change_list.html"

    def get_fieldsets(self, request, obj=None):
        fiyat = ["tavsiye", "grup_fiyatlari_gosterimi", "alis_fiyati"]
        aciklama = (
            "Bayinin ödeyeceği <b>Fatura → Fiyat Grupları</b>'nda grubun sayfasından girilir "
            "(kontördeki fiyat listesinin aynı düzeni); rakamı yazılmayan grup bu kurumu "
            "göremez. Sorgulu kurumda o rakam fatura başına hizmet bedelidir (bayi fatura tutarı "
            "+ bunu öder), sorgusuz kalemde net bayi fiyatı. <b>Müşteriye</b> gruba göre değişmez. "
            "Alışımız yalnızca sorgusuz kalemin kâr hesabı içindir."
        )
        # Varsayılan grup yoksa grupsuz bayi kurumun kendi rakamını öder;
        # o zaman alan gerekir. Varsayılan grup varken hiçbir bayiye uymaz, gizlenir.
        if fiyat_grubu(None) is None:
            fiyat += ["hizmet_bedeli", "bayi_fiyati"]
        return (
            (None, {"fields": ("ad", "kod", "uzak_id", "kategori", "operator", "sira", "aktif", "sorgulu")}),
            (
                "Numara kuralı",
                {
                    "fields": ("alan_etiketi", ("min_hane", "max_hane"), "sadece_rakam", "aciklama"),
                    "description": (
                        "Robot sağlayıcının alan tanımını kataloğla yollar ve bu kuralı günceller. "
                        "Kurala uymayan numara bayi formundan geçmez, robota hiç gitmez."
                    ),
                },
            ),
            ("Fiyat", {"fields": fiyat, "description": aciklama}),
        )

    def get_readonly_fields(self, request, obj=None):
        # Kod robotun kimliğidir: değişirse robot bu kurumu bulamaz.
        return ("kod", "grup_fiyatlari_gosterimi") if obj is not None else ("grup_fiyatlari_gosterimi",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("kategori")
            .prefetch_related(Prefetch("grup_fiyatlari", queryset=GrupFiyati.objects.select_related("grup")))
        )

    def get_urls(self):
        return [
            path(
                "eslestir/",
                self.admin_site.admin_view(_atomik_degil(self.eslestir)),
                name="fatura_kurum_eslestir",
            ),
            *super().get_urls(),
        ]

    def eslestir(self, request):
        """Sağlayıcının kurum listesinden kurum numaralarını doldurur. Yalnızca POST."""
        if request.method != "POST":
            return redirect("admin:fatura_kurum_changelist")
        if not self.has_change_permission(request):
            raise PermissionDenied
        try:
            adet, guncellenen, eslesmeyen = kurumlari_eslestir()
        except FaturaHatasi as hata:
            self.message_user(request, str(hata), messages.ERROR)
            return redirect("admin:fatura_kurum_changelist")
        self.message_user(
            request,
            f"Sağlayıcının listesinde {adet} kurum; {guncellenen} kurumun numarası yazıldı.",
            messages.SUCCESS,
        )
        if eslesmeyen:
            self.message_user(
                request,
                f"Adıyla eşleşmeyen {len(eslesmeyen)} kurum (numarayı listeden elle yaz): {', '.join(eslesmeyen[:20])}"
                + (" …" if len(eslesmeyen) > 20 else ""),
                messages.WARNING,
            )
        return redirect("admin:fatura_kurum_changelist")

    @display(description="Numara")
    def kural(self, obj):
        hane = f"{obj.max_hane} hane" if obj.min_hane == obj.max_hane else f"{obj.min_hane}–{obj.max_hane} hane"
        return f"{obj.alan_etiketi} · {hane}" + (" · rakam" if obj.sadece_rakam else "")

    @display(description="Bayiye (grup)")
    def grup_fiyatlari_gosterimi(self, obj):
        """Her grubun rakamı, yalnızca okunur. Rakamı olmayan grup bu kurumu göremez."""
        if obj is None or obj.pk is None:
            return "—"
        from apps.kontor.models import FiyatGrubu

        gruplar = list(FiyatGrubu.objects.order_by("-varsayilan", "ad"))
        if not gruplar:
            deger = obj.hizmet_bedeli if obj.sorgulu else obj.bayi_fiyati
            return deger if deger is not None else format_html('<span style="color:#D42046">fiyat yok</span>')
        yazili = {g.grup_id: g.tutar for g in obj.grup_fiyatlari.all()}
        on_ek = "+" if obj.sorgulu else ""
        return format_html_join(
            format_html("<br>"),
            '<span style="white-space:nowrap">{}: {}</span>',
            (
                (g.ad, f"{on_ek}{yazili[g.pk]}" if g.pk in yazili else format_html('<span style="color:#94A3B8">satılmaz</span>'))
                for g in gruplar
            ),
        )


@admin.register(FaturaFiyatGrubu)
class FaturaFiyatGrubuAdmin(ModelAdmin):
    """Perakende, Toptan… — kontördeki grup ekranının faturadaki eşi, aynı düzen.

    Gruplar kontörle ortaktır (vekil model): bayi ikisinde de cüzdanındaki
    grubu öder. Grubun sayfası **tek sayfadır**: üstte ayarlar, altta fatura
    kurumları; satırda tek rakam, boş = bu gruba satılmaz, hesap aracı üstte
    (kontörün aracı, ortak `admin/parca_grup_fiyat_betik.html`). Kontörün
    grup sayfası yalnızca paketleri gösterir — bir süre fatura tablosu da
    oradaydı, yönetici "Fatura'ya bastım kontör fiyatları geliyor" dedi.
    """

    list_display = ("ad", "fiyatli_sayisi", "varsayilan", "bayi_sayisi", "aciklama")
    search_fields = ("ad",)
    fields = ("ad", "varsayilan", "aciklama")

    def has_delete_permission(self, request, obj=None):
        # Grup kontörle ortak: buradan silinseydi kontör paket fiyatları da giderdi.
        return False

    def has_add_permission(self, request):
        # Yeni grup (hele "varsayılan" işaretliyse) kontör fiyatlarını da etkiler:
        # fatura izni yetmez, kontör grubu ekleme izni de gerekir.
        return super().has_add_permission(request) and request.user.has_perm("kontor.add_fiyatgrubu")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Grubun sayfası fatura fiyatlarıdır; ayarlar da o sayfanın üstünde durur."""
        return redirect("admin:fatura_faturafiyatgrubu_fiyatlar", object_id)

    def response_add(self, request, obj, post_url_continue=None):
        return redirect("admin:fatura_faturafiyatgrubu_fiyatlar", obj.pk)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_bayi=Count("cuzdanlar", distinct=True), _fiyatli=Count("fatura_fiyatlari", distinct=True))
        )

    @display(description="Fiyatı yazılı kurum", ordering="_fiyatli")
    def fiyatli_sayisi(self, obj):
        return obj._fiyatli or "—"

    @display(description="Bayi", ordering="_bayi")
    def bayi_sayisi(self, obj):
        adres = reverse("admin:finans_cuzdan_changelist") + f"?kontor_grubu__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', adres, obj._bayi)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/fiyatlar/",
                self.admin_site.admin_view(self.fiyatlar),
                name="fatura_faturafiyatgrubu_fiyatlar",
            ),
            *super().get_urls(),
        ]

    def fiyatlar(self, request, object_id):
        grup = self.get_object(request, object_id)
        if grup is None:
            raise Http404("Fiyat grubu bulunamadı.")
        if not self.has_change_permission(request, grup):
            raise PermissionDenied

        pasif = request.GET.get("pasif") == "1"
        liste = fatura_fiyat.kurumlar(pasif)
        # Grubun adı ve "varsayılan" işareti kontörle ortaktır: varsayılanı
        # değiştirmek grubu seçilmemiş bayilerin kontör fiyatını da değiştirir.
        # Fatura izni yalnızca fatura rakamlarını yazdırır; grup ayarı kontör
        # grubu izni ister (form çizilmez, elle gönderilen istek reddedilir).
        grup_duzenlenir = request.user.has_perm("kontor.change_fiyatgrubu")
        if "_grup" in request.POST and not grup_duzenlenir:
            raise PermissionDenied

        GrupFormu = forms.modelform_factory(
            FaturaFiyatGrubu,
            fields=("ad", "varsayilan", "aciklama"),
            widgets={"ad": UnfoldAdminTextInputWidget, "aciklama": UnfoldAdminTextInputWidget},
        )
        grup_formu = GrupFormu(request.POST if "_grup" in request.POST else None, instance=grup)
        if "_grup" in request.POST:
            if grup_formu.is_valid():
                grup_formu.save()
                self.message_user(request, f"{grup}: grup ayarları kaydedildi.", messages.SUCCESS)
                return redirect(request.get_full_path())
            self.message_user(request, "Grup ayarları kaydedilmedi; hatayı düzeltin.", messages.ERROR)

        if "_hepsine" in request.POST:
            try:
                tutar = fatura_fiyat._ondalik(request.POST.get("hepsine_tutar"))
            except (InvalidOperation, ValueError):
                tutar = None
            if tutar is None:
                self.message_user(request, "Hepsine yazılacak bedel anlaşılamadı; örn. 10 ya da 7,5.", messages.ERROR)
            else:
                with transaction.atomic():
                    adet, degisen = fatura_fiyat.hepsine_yaz(grup, liste, tutar)
                self.message_user(
                    request,
                    f"{grup}: {adet} sorgulu kurumun fatura başı bedeli {tutar} ₺ ({degisen} değişti). "
                    "Sorgusuz kalemlere dokunulmadı.",
                    messages.SUCCESS,
                )
            return redirect(request.get_full_path())

        fiyat_postu = request.method == "POST" and "_grup" not in request.POST
        hatalar = {}
        if fiyat_postu:
            yazilacak, hatalar = fatura_fiyat.ayikla(liste, request.POST)
            if not hatalar:
                with transaction.atomic():
                    degisen = fatura_fiyat.kaydet(grup, yazilacak)
                self.message_user(request, f"{grup}: {degisen} kurumun fiyatı kaydedildi.", messages.SUCCESS)
                return redirect(request.get_full_path())
            self.message_user(request, "Bazı satırlar kaydedilmedi; kırmızı yazan satırları düzeltin.", messages.ERROR)

        return render(
            request,
            "admin/fatura/grup_fiyatlari.html",
            {
                **self.admin_site.each_context(request),
                "title": f"{grup} · fatura fiyatları",
                "opts": self.model._meta,
                "grup": grup,
                "grup_formu": grup_formu,
                "grup_duzenlenir": grup_duzenlenir,
                "satirlar": fatura_fiyat.satirlar(grup, liste, request.POST if fiyat_postu else None, hatalar),
                "sorgulu_sayisi": sum(1 for k in liste if k.sorgulu),
                "pasif": pasif,
            },
        )


# -- Robot ---------------------------------------------------------------


def _hesap_hak(obj, tur):
    """Bir hesabın o türdeki bugünkü kullanımı, renkli: 3/10, limit doldu, sınırsız."""
    if obj.pk is None:
        return "—"
    if obj.saglayici_doldu_mu(tur):
        return format_html('<b style="color:#D42046">limit doldu</b>')
    sayi, limit = obj.bugunku_sayi(tur), obj.limiti(tur)
    if not limit:
        return format_html("<b>{}</b>", sayi)   # sınırsız
    renk = "#D42046" if sayi >= limit else ("#B45309" if sayi >= limit * 0.8 else "#0F8A4D")
    return format_html('<b style="color:{}">{}/{}</b>', renk, sayi, limit)


class RobotHesabiFormu(forms.ModelForm):
    class Meta:
        model = RobotHesabi
        fields = "__all__"
        widgets = {
            # Şifre ekranda maskeli durur ama kayıtlı değer korunur (robot
            # /hesaplar/ ile çeker). Staff-only admin; yine de açıkta yazmayalım.
            "sifre": UnfoldAdminPasswordWidget(render_value=True),
        }


class RobotHesabiInline(TabularInline):
    model = RobotHesabi
    form = RobotHesabiFormu
    extra = 0
    fields = (
        "kullanici_adi", "sifre", "guvenlik_resmi",
        "fatura_limiti", "kontor_limiti", "fatura_kullanim", "kontor_kullanim",
        "sira", "aktif",
    )
    readonly_fields = ("fatura_kullanim", "kontor_kullanim")

    @display(description="Fatura (bugün)")
    def fatura_kullanim(self, obj):
        return _hesap_hak(obj, "fatura")

    @display(description="Kontör (bugün)")
    def kontor_kullanim(self, obj):
        return _hesap_hak(obj, "paket")


@admin.register(Robot)
class RobotAdmin(ModelAdmin):
    list_display = (
        "ad", "durum_gosterimi", "oturum_gosterimi", "isler_gosterimi", "hesap_ozeti",
        "mesai_gosterimi", "son_nabiz", "aktif", "anahtar_durumu", "anahtar_dugmesi",
    )
    list_editable = ("aktif",)
    fields = ("ad", "aktif", ("fatura_limiti", "kontor_limiti"), "son_nabiz")
    readonly_fields = ("son_nabiz",)
    inlines = (RobotHesabiInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("hesaplar")

    def save_formset(self, request, form, formset, change):
        # Yeni hesap limitsiz girildiyse robotun varsayılan hakkını al.
        nesneler = formset.save(commit=False)
        robot = form.instance
        for nesne in nesneler:
            if isinstance(nesne, RobotHesabi):
                if not nesne.fatura_limiti and robot.fatura_limiti:
                    nesne.fatura_limiti = robot.fatura_limiti
                if not nesne.kontor_limiti and robot.kontor_limiti:
                    nesne.kontor_limiti = robot.kontor_limiti
            nesne.save()
        for nesne in formset.deleted_objects:
            nesne.delete()
        formset.save_m2m()

    @display(description="Durum")
    def durum_gosterimi(self, obj):
        if not obj.cevrimici:
            return _rozet("Çevrimdışı", GRI)
        return _rozet("Meşgul", "#B45309") if obj.mesgul else _rozet("Açık", "#0F8A4D")

    @display(description="Hesaplar · bugün (fatura/kontör)")
    def hesap_ozeti(self, obj):
        # Robotun toplam hesabı ve bugünkü kullanımı; hakkı kalan hesap sayısı.
        hesaplar = [h for h in obj.hesaplar.all() if h.aktif]
        if not hesaplar:
            return format_html('<b style="color:#D42046">hesap yok</b>')
        f_top = sum(h.bugunku_fatura for h in hesaplar)
        k_top = sum(h.bugunku_kontor for h in hesaplar)
        f_kalan = sum(1 for h in hesaplar if not h.limit_doldu("fatura"))
        k_kalan = sum(1 for h in hesaplar if not h.limit_doldu("paket"))
        return format_html(
            "{} hesap · fatura {} ({} açık) · kontör {} ({} açık)",
            len(hesaplar), f_top, f_kalan, k_top, k_kalan,
        )

    @display(description="Oturum")
    def oturum_gosterimi(self, obj):
        if obj.oturum_canli:
            return _soluk("canlı")
        return format_html('<b style="color:#D42046">düştü — robotun makinesinde giris.bat</b>')

    @display(description="İşler")
    def isler_gosterimi(self, obj):
        # Robot iş isterken söyler; eski sürüm yalnızca fatura yapar.
        if obj.paket_sorgusu:
            return "Fatura · Paket"
        return format_html('Fatura <span style="color:{}">· paket için robotu güncelle</span>', GRI)

    @display(description="Çalışma saatleri")
    def mesai_gosterimi(self, obj):
        return obj.mesai_metni or _soluk("bildirilmedi")

    @display(description="Anahtar")
    def anahtar_durumu(self, obj):
        if obj.anahtar_ozeti:
            return format_html('<span style="color:#0F8A4D">var</span>')
        return format_html('<b style="color:#D42046">üretilmedi</b>')

    @display(description="")
    def anahtar_dugmesi(self, obj):
        return _dugme(reverse("admin:fatura_robot_anahtar", args=[obj.pk]), "Yeni anahtar")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/anahtar/",
                self.admin_site.admin_view(self.anahtar),
                name="fatura_robot_anahtar",
            ),
            *super().get_urls(),
        ]

    def anahtar(self, request, object_id):
        """Robotun anahtarını üretir ve bir kez gösterir. GET onay, POST üretim.

        Eski anahtar anında geçersiz olur; robot ayar.json güncellenene kadar
        iş alamaz. Düz bağlantı olsaydı açılan herhangi bir sayfa robotu
        sessizce kilitleyebilirdi.
        """
        robot = self.get_object(request, object_id)
        if robot is None:
            raise Http404("Robot bulunamadı.")
        # admin_view yalnızca "personel mi" diye bakar; anahtar robotun
        # kimliğidir, yalnızca robotu değiştirme izni olan üretebilir.
        if not self.has_change_permission(request, robot):
            raise PermissionDenied
        baglam = {
            **self.admin_site.each_context(request),
            "title": "Robot anahtarı",
            "opts": self.model._meta,
            "robot": robot,
            # Panel hangi alan adından açılmış olursa olsun robot tek adrese gider.
            "adres": (settings.FATURA_ROBOT_ADRESI or request.build_absolute_uri("/")).rstrip("/"),
        }
        if request.method == "POST":
            baglam["anahtar"] = robot.yeni_anahtar()
        return render(request, "admin/fatura/robot_anahtar.html", baglam)


# -- Sorgu kaydı ---------------------------------------------------------

SORGU_RENKLERI = {
    SorguDurumu.BEKLIYOR: GRI,
    SorguDurumu.SORGULANIYOR: "#B45309",
    SorguDurumu.TAMAM: "#0F8A4D",
    SorguDurumu.HATA: "#D42046",
}


@admin.register(Sorgu)
class SorguAdmin(ModelAdmin):
    """Robotun yaptığı sorguların kaydı; yalnızca okunur."""

    list_display = ("olusturma_tarihi", "referans_no", "bayi_gosterimi", "kurum", "numara", "durum_gosterimi", "sonuc_ozeti", "robot")
    list_filter = ("durum", "kurum", "robot", ("olusturma_tarihi", GunAraligiFiltresi))
    search_fields = ("referans_no", "numara", "bayi__username", "bayi__first_name", "bayi__last_name")
    list_per_page = 50
    readonly_fields = [f.name for f in Sorgu._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi", "bayi__bayi_profili", "kurum", "robot")

    @display(description="Bayi", ordering="bayi__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.bayi)

    @display(description="Durum", ordering="durum")
    def durum_gosterimi(self, obj):
        return _rozet(obj.get_durum_display(), SORGU_RENKLERI.get(obj.durum, GRI))

    @display(description="Sonuç")
    def sonuc_ozeti(self, obj):
        if obj.faturalar:
            return f"{len(obj.faturalar)} fatura · {obj.abone_adi}"
        robot_hatasi = (obj.sonuc or {}).get("robot_hatasi")
        if robot_hatasi:
            return format_html('{}<br><span style="color:{};font-size:.7rem">robot: {}</span>', obj.mesaj, GRI, robot_hatasi)
        return obj.mesaj or "—"


# -- Ödemeler ------------------------------------------------------------

ODEME_RENKLERI = {
    OdemeDurumu.BEKLIYOR: "#B45309",
    OdemeDurumu.ODENDI: "#0F8A4D",
    OdemeDurumu.IPTAL: "#D42046",
}


GONDERIM_RENKLERI = {
    GonderimDurumu.GONDERILIYOR: GRI,
    GonderimDurumu.ISLEMDE: "#B45309",
    GonderimDurumu.ODENDI: "#0F8A4D",
    GonderimDurumu.REDDEDILDI: "#D42046",
    GonderimDurumu.IPTAL: "#D42046",
    GonderimDurumu.BELIRSIZ: "#D42046",
}


class KararFiltresi(admin.SimpleListFilter):
    """Yönetimin elindeki ödemeler (`services.yonetim_bekleyenler`), rozetin saydığı."""

    title = "Karar"
    parameter_name = "karar"

    def lookups(self, request, model_admin):
        return (("bekliyor", "Yönetimin elinde"), ("saglayicida", "Sağlayıcıda sürüyor"))

    def queryset(self, request, queryset):
        if self.value() == "bekliyor":
            return yonetim_bekleyenler(queryset)
        if self.value() == "saglayicida":
            return queryset.filter(durum=OdemeDurumu.BEKLIYOR).exclude(pk__in=yonetim_bekleyenler().values("pk"))
        return queryset


@admin.register(Odeme)
class OdemeAdmin(ModelAdmin):
    """Bayinin ödediği faturalar. Faturaları sağlayıcı öder; yönetim istisnaya bakar.

    Fatura sağlayıcısı ve kurumun sağlayıcıdaki numarası varsa ödeme
    kendiliğinden gönderilir, sonucu sorulur, "Ödendi" ya da "İptal + iade"
    kendiliğinden olur. Gönderilemeyen, cevabı belirsiz olan ve sağlayıcıya
    hiç gitmeyen (elle ödenecek) ödemeler yönetimin elindedir: süzgeç ve
    rozet onları sayar, düğme kırmızıdır.

    Durum alanı formda salt okunurdur; karar yalnızca satırdaki düğmeden
    (onay ekranı, POST) verilir ve `services` üzerinden geçer. İptal para
    oynattığı için doğrudan çalışmaz, ne olacağını yazan ekranı açar.
    """

    list_display = (
        "olusturma_tarihi", "referans", "bayi_gosterimi", "kurum_adi", "numara",
        "fatura_ozeti", "tutar_gosterimi", "durum_gosterimi", "saglayici_gosterimi", "karar_dugmesi",
    )
    list_filter = (KararFiltresi, "durum", "kurum", ("olusturma_tarihi", GunAraligiFiltresi))
    search_fields = (
        "siparis__referans_no", "numara", "abone_adi",
        "bayi__username", "bayi__first_name", "bayi__last_name", "bayi__bayi_profili__unvan",
    )
    list_per_page = 50
    readonly_fields = [f.name for f in Odeme._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("siparis", "bayi", "bayi__bayi_profili")
            .prefetch_related("gonderimler")
        )

    @display(description="Referans", ordering="siparis__referans_no")
    def referans(self, obj):
        return obj.siparis.referans_no

    @display(description="Bayi", ordering="bayi__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.bayi)

    @display(description="Fatura")
    def fatura_ozeti(self, obj):
        if not obj.faturalar:
            return _soluk("sabit tutar")
        return format_html_join(
            format_html("<br>"),
            '<span style="white-space:nowrap">{} <span style="color:{}">· {}</span></span>',
            ((f.get("fatura_no"), GRI, f.get("son_odeme_tarihi")) for f in obj.faturalar),
        )

    @display(description="Tutar")
    def tutar_gosterimi(self, obj):
        if obj.saglayici_tutari is None:
            return obj.siparis.tutar
        return format_html(
            '<b>{}</b><br><span style="color:{};font-size:.7rem">{} {}</span>',
            obj.siparis.tutar, GRI, "fatura" if obj.faturalar else "alış", obj.saglayici_tutari,
        )

    @display(description="Durum", ordering="durum")
    def durum_gosterimi(self, obj):
        rozet = _rozet(obj.get_durum_display(), ODEME_RENKLERI.get(obj.durum, GRI))
        if obj.sonuc_notu:
            return format_html('{}<br><span style="color:{};font-size:.7rem">{}</span>', rozet, GRI, obj.sonuc_notu)
        return rozet

    @display(description="Sağlayıcı")
    def saglayici_gosterimi(self, obj):
        """Faturaların sağlayıcıdaki son durumu; hiç gitmediyse elle ödenecektir."""
        son = obj.son_gonderimler()
        if not son:
            if not obj.bekliyor:
                return "—"
            yeni = timezone.now() - obj.olusturma_tarihi < OTOMATIK_GONDERIM_SURESI
            return _soluk("gönderiliyor" if obj.otomatik and yeni else "elle ödenecek")
        return format_html_join(
            format_html("<br>"),
            "{}",
            ((_rozet(g.get_durum_display(), GONDERIM_RENKLERI.get(g.durum, GRI)),) for g in son.values()),
        )

    @display(description="")
    def karar_dugmesi(self, obj):
        if not obj.bekliyor:
            return ""
        # Sağlayıcıda süren ödeme kendiliğinden kapanır; yönetimin elindeki kırmızı.
        renk = "#0D1320" if obj.saglayicida else "#D42046"
        return _dugme(reverse("admin:fatura_odeme_karar", args=[obj.pk]), "Karar", renk)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/karar/",
                self.admin_site.admin_view(_atomik_degil(self.karar)),
                name="fatura_odeme_karar",
            ),
            *super().get_urls(),
        ]

    def karar(self, request, object_id):
        odeme = self.get_object(request, object_id)
        if odeme is None:
            raise Http404("Ödeme bulunamadı.")
        # Karar para oynatır (iade); yalnızca ödemeyi değiştirme izni olan
        # personel görür ve verir. admin_view tek başına bunu denetlemez.
        if not self.has_change_permission(request, odeme):
            raise PermissionDenied
        if request.method == "POST":
            karar = request.POST.get("karar")
            try:
                if karar == "sorgula":
                    adet = sonucu_sorgula(odeme)
                    odeme.refresh_from_db()
                    durum = {
                        OdemeDurumu.ODENDI: ("Sağlayıcı ödendi dedi; ödeme kapandı.", messages.SUCCESS),
                        OdemeDurumu.IPTAL: ("Sağlayıcı iptal etti; tutar bayiye iade edildi.", messages.WARNING),
                    }.get(odeme.durum, (f"{adet} gönderim soruldu; cevaplar aşağıda.", messages.INFO))
                    messages.add_message(request, durum[1], durum[0])
                    return redirect("admin:fatura_odeme_karar", odeme.pk)
                if karar == "gonder":
                    yeni = odemeyi_gonder(odeme.pk, elle=True)
                    messages.info(
                        request,
                        " · ".join(f"{g.fatura_no}: {g.get_durum_display()}" for g in yeni)
                        or "Gönderilecek fatura yok.",
                    )
                    return redirect("admin:fatura_odeme_karar", odeme.pk)
                if karar == "odendi":
                    odendi_isaretle(odeme, olusturan=request.user, not_=request.POST.get("not", ""))
                    messages.success(request, f"{odeme.referans_no} ödendi olarak kapandı.")
                elif karar == "iptal":
                    sebep = (request.POST.get("sebep") or "").strip()
                    if not sebep:
                        messages.error(request, "İptal sebebini yaz: bayi görecek.")
                        return redirect("admin:fatura_odeme_karar", odeme.pk)
                    iptal_et(odeme, olusturan=request.user, sebep=sebep)
                    messages.success(request, f"{odeme.referans_no} iptal edildi, {odeme.siparis.tutar} ₺ bayiye iade edildi.")
                else:
                    messages.error(request, "Bilinmeyen karar.")
                    return redirect("admin:fatura_odeme_karar", odeme.pk)
            except KararVerilemez as hata:
                messages.error(request, str(hata))
                return redirect("admin:fatura_odeme_karar", odeme.pk)
            return redirect("admin:fatura_odeme_changelist")
        gonderimler = list(odeme.gonderimler.select_related("saglayici"))
        son = odeme.son_gonderimler()
        return render(
            request,
            "admin/fatura/odeme_karar.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Fatura ödemesi · {odeme.referans_no}",
                "opts": self.model._meta,
                "odeme": odeme,
                "gonderimler": gonderimler,
                "engel": gonderim_engeli(odeme) if odeme.bekliyor else "",
                "suren": any(g.suruyor for g in son.values()),
                "odenen": any(g.durum == GonderimDurumu.ODENDI for g in son.values()),
                "belirsiz": any(g.durum == GonderimDurumu.BELIRSIZ for g in son.values()),
                # Sağlayıcı açıklamayla iptal etti: kendiliğinden iade edilmez
                # (`services._sonuclandir`), metin iade sebebine hazır yazılır.
                "iptal_aciklamasi": " · ".join(dict.fromkeys(
                    g.mesaj for g in son.values() if g.durum == GonderimDurumu.IPTAL and g.mesaj
                )) if son and all(g.durum == GonderimDurumu.IPTAL for g in son.values()) else "",
                "sorulabilir": any(
                    g.durum in (GonderimDurumu.ISLEMDE, GonderimDurumu.BELIRSIZ) for g in son.values()
                ),
                "gonderilebilir": [
                    f["fatura_no"] for f in odeme.faturalar
                    if f["fatura_no"] not in son
                    or not (son[f["fatura_no"]].suruyor or son[f["fatura_no"]].durum == GonderimDurumu.ODENDI)
                ],
            },
        )
