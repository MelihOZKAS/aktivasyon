import logging
import re

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as TemelGrupAdmin
from django.contrib.auth.admin import UserAdmin as TemelKullaniciAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Q
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, StackedInline
from unfold.decorators import action as unfold_islem
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import (
    UnfoldAdminCheckboxSelectMultipleWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextareaWidget,
    UnfoldAdminTextInputWidget,
)

from django.contrib.auth import update_session_auth_hash
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse

from apps.bayi.etiket import kullanici_etiketi, kullanici_etiketi_html
from apps.bayi.models import (
    BayiBasvuruDurumu,
    BayiBasvurusu,
    BayiProfili,
    Duyuru,
    GenelAyarlar,
    SimKart,
    SimKartDurumu,
)
from apps.bayi.parola import uret as parola_uret
from apps.bayi.services import HesapAcilamadi, bayi_hesabi_ac
from apps.bayi.telefon import normalize
from apps.finans.models import Cuzdan
from apps.katalog.models import BasvuruKategorisi, Operator

logger = logging.getLogger(__name__)


class KapaliKategoriKutusu:
    """“Kapalı başvuru tipleri” kutusunu onay kutusu listesi olarak çizer.

    Varsayılan çoklu seçim kutusunda kapatmak için Ctrl'e basılı tutmak
    gerekiyor; yönetici tek tıkla açtığını kapatıyordu. Liste kategori
    sırasını izler, pasif tipler de görünür — kapatılmış bir tip sonradan
    açılırsa işaret yerinde dursun.
    """

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "kapali_kategoriler":
            kwargs["widget"] = UnfoldAdminCheckboxSelectMultipleWidget()
            kwargs["queryset"] = BasvuruKategorisi.objects.order_by("sira", "ad")
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class BayiProfiliInline(KapaliKategoriKutusu, StackedInline):
    model = BayiProfili
    can_delete = False
    extra = 0
    fields = (
        ("bayi_mi", "tedarikci_mi"),
        ("unvan", "yetkili_adi"),
        ("telefon", "sehir"),
        "adres",
        ("vergi_dairesi", "vergi_no"),
        "kapali_kategoriler",
        "notlar",
    )


class CuzdanInline(StackedInline):
    model = Cuzdan
    can_delete = False
    extra = 0
    fields = (("grup", "islem_yapabilir"), ("bakiye", "borc"))
    readonly_fields = ("bakiye", "borc")


class KullaniciAdiKarisimi:
    """Kullanıcı adı telefon numarasıysa tek biçime indirir.

    Bayi giriş ekranına numarasını yazacak. Yönetici "0532 123 45 67" diye
    açarsa bayi "5321234567" yazıp giremez. Boşluk, ülke kodu ve baştaki
    sıfır burada düşer; harf içeren gerçek kullanıcı adlarına dokunulmaz.
    """

    YARDIM = (
        "Bayi bu adla giriş yapar. Telefon numarasını yazın — boşluklar, "
        "ülke kodu ve baştaki sıfır kendiliğinden silinir "
        "(0532 123 45 67 → 5321234567)."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        alan = self.fields.get("username")
        if alan is not None:
            alan.help_text = self.YARDIM

    def clean_username(self):
        return normalize(self.cleaned_data["username"])


class BayiKullaniciEklemeFormu(KullaniciAdiKarisimi, UserCreationForm):
    pass


class BayiKullaniciDuzenlemeFormu(KullaniciAdiKarisimi, UserChangeForm):
    pass


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class KullaniciAdmin(TemelKullaniciAdmin, ModelAdmin):
    form = BayiKullaniciDuzenlemeFormu
    add_form = BayiKullaniciEklemeFormu
    change_password_form = AdminPasswordChangeForm
    inlines = [BayiProfiliInline, CuzdanInline]
    # Parola düğmesi hem listenin her satırında hem kullanıcı sayfasının
    # üstünde durur: bayi telefonla arayıp "giremiyorum" dediğinde yönetici
    # aramadan çıkmadan halletsin.
    actions_row = ["yeni_parola", "cuzdan_islemi"]
    actions_detail = ["yeni_parola", "cuzdan_islemi"]
    # E-posta yerine borç: yönetici listeye "kimde ne var" diye bakıyor,
    # e-postayı zaten kimse kullanmıyor. Borcu olmayan sıfır görür.
    list_display = (
        "username",
        "unvan_gosterimi",
        "bakiye_gosterimi",
        "borc_gosterimi",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "cuzdan__grup")
    # Bayinin numarasını kimse ezbere bilmiyor; ünvanından ve adından da
    # bulunsun. Otomatik tamamlama kutuları da bu listeden besleniyor.
    search_fields = (
        "username", "first_name", "last_name", "email",
        "bayi_profili__unvan", "bayi_profili__yetkili_adi",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("bayi_profili", "cuzdan")

    @admin.display(description="Ünvan")
    def unvan_gosterimi(self, obj):
        profil = getattr(obj, "bayi_profili", None)
        return profil.unvan if profil and profil.unvan else "—"

    @unfold_islem(
        description="Yeni parola",
        url_path="yeni-parola",
        permissions=["change"],
        icon="key",
    )
    def yeni_parola(self, request, object_id):
        """Bayiye okunabilir yeni bir parola üretir ve bir kez gösterir.

        Sistem parolayı saklamaz — yalnızca özetini tutar — bu yüzden
        "eski parolası neydi" diye bakılamaz; unutulduğunda tek yol yenisini
        vermek. Yönetici parola uydurmak zorunda kalmasın diye üretimi sistem
        yapıyor.

        Üretme işi POST ile olur: düğme bir bağlantı olsaydı, yöneticinin
        ziyaret ettiği herhangi bir sayfa gizlice bayinin parolasını
        sıfırlayabilirdi. GET onay ekranını, POST parolayı üretir.
        """
        kullanici = self.get_object(request, object_id)
        if kullanici is None:
            raise Http404("Kullanıcı bulunamadı.")

        baglam = {
            **self.admin_site.each_context(request),
            "title": "Yeni parola",
            "opts": self.model._meta,
            "kullanici": kullanici,
            "giris_adresi": request.build_absolute_uri(reverse("bayi:giris")),
            "kullanici_adresi": reverse(
                "admin:auth_user_change", args=[kullanici.pk]
            ),
        }

        if request.method != "POST":
            return render(request, "admin/bayi/yeni_parola.html", baglam)

        parola = parola_uret()
        kullanici.set_password(parola)
        kullanici.save(update_fields=["password"])

        # Yönetici kendi parolasını yenilediyse kendi oturumundan düşmesin.
        if kullanici.pk == request.user.pk:
            update_session_auth_hash(request, kullanici)

        # Parola yalnızca bu yanıtta görünür: log'a, mesaja, bildirime girmez.
        logger.info("%s için yeni parola üretildi.", kullanici.get_username())
        return render(
            request, "admin/bayi/yeni_parola.html", {**baglam, "parola": parola}
        )

    @unfold_islem(
        description="Bakiye / borç",
        url_path="cuzdan-islemi",
        permissions=["change"],
        icon="account_balance_wallet",
    )
    def cuzdan_islemi(self, request, object_id):
        """Kullanıcı listesinden doğrudan cüzdan işlemine götürür.

        Yönetici bayiyi kullanıcı adından buluyor; para işlemi için ayrıca
        Cüzdanlar ekranında aynı bayiyi ikinci kez aramasın. Ekran tek yerde
        (`CuzdanAdmin`), buradan yalnızca yönlendiriliyor.
        """
        from apps.finans.models import Cuzdan

        kullanici = self.get_object(request, object_id)
        if kullanici is None:
            raise Http404("Kullanıcı bulunamadı.")

        # Elle açılmış kullanıcının cüzdanı olmayabilir; para ekranı için
        # sıfır bakiyeli cüzdan açılır, yönetici boş ekranla karşılaşmaz.
        cuzdan, _ = Cuzdan.objects.get_or_create(bayi=kullanici)
        return redirect("admin:finans_cuzdan_bakiye_yukle", cuzdan_id=cuzdan.pk)

    @admin.display(description="Bakiye")
    def bakiye_gosterimi(self, obj):
        cuzdan = getattr(obj, "cuzdan", None)
        if not cuzdan:
            return format_html('<span style="color:#94a3b8">cüzdan yok</span>')
        renk = "#16a34a" if cuzdan.bakiye >= 0 else "#dc2626"
        return format_html('<b style="color:{}">{} ₺</b>', renk, cuzdan.bakiye)

    @admin.display(description="Borç", ordering="cuzdan__borc")
    def borc_gosterimi(self, obj):
        cuzdan = getattr(obj, "cuzdan", None)
        borc = cuzdan.borc if cuzdan else 0
        if not borc:
            return format_html('<span style="color:#94a3b8">0 ₺</span>')
        return format_html('<b style="color:#dc2626">{} ₺</b>', borc)


@admin.register(Group)
class GrupAdmin(TemelGrupAdmin, ModelAdmin):
    pass


@admin.register(BayiProfili)
class BayiProfiliAdmin(KapaliKategoriKutusu, ModelAdmin):
    list_display = ("kullanici", "unvan", "rol_rozeti", "telefon", "sehir")
    search_fields = (
        "kullanici__username", "kullanici__first_name", "kullanici__last_name",
        "unvan", "yetkili_adi", "telefon", "vergi_no",
    )
    autocomplete_fields = ("kullanici",)
    list_filter = ("bayi_mi", "tedarikci_mi", "sehir")
    fieldsets = (
        (
            "Roller",
            {
                "fields": (("bayi_mi", "tedarikci_mi"),),
                "description": (
                    "Roller birbirini dışlamaz. Bayi başvuru getirir ve hakediş alır; "
                    "tedarikçi kendisine atanan işlemin aktivasyonunu yapar, alış "
                    "bedelini alacak olarak yazar."
                ),
            },
        ),
        ("Firma", {"fields": ("kullanici", "unvan", "yetkili_adi", "telefon", "sehir", "adres")}),
        (
            "Başvuru tipleri",
            {
                "fields": ("kapali_kategoriler",),
                "description": (
                    "İşaretlenen tipler bu bayiye <b>hiç gösterilmez</b>. Boş "
                    "bırakılırsa hepsi açıktır; sonradan açılan yeni bir tip de "
                    "kendiliğinden açık gelir."
                ),
            },
        ),
        ("Kayıt", {"fields": ("vergi_dairesi", "vergi_no", "notlar")}),
    )

    @admin.display(description="Rol")
    def rol_rozeti(self, obj):
        renkler = {"Bayi": "#0E5E5B", "Tedarikçi": "#B45309", "Bayi ve Tedarikçi": "#0F8A4D"}
        ad = obj.rol_adi
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(ad, "#6F7B8F"),
            ad,
        )


class SimAtamaFormu(forms.Form):
    """SIM kartları bir bayiye zimmetlemek için."""

    bayi = forms.ModelChoiceField(
        label="Hangi bayiye zimmetlensin?",
        queryset=User.objects.filter(is_active=True).order_by("username"),
    )


class TopluSimFormu(forms.Form):
    """Listeden toplu SIM kart girişi.

    Kartlar operatörden koli koli geliyor; yüzlerce IMEI'yi tek tek "Ekle"
    ekranından girmek günlük işi kilitliyordu. Liste operatörün gönderdiği
    dosyadan kopyalanıp yapıştırılır: satır, virgül, noktalı virgül ya da
    boşluk — hepsi ayraç sayılır, çünkü kopyalanan biçim her seferinde aynı
    olmuyor.

    Operatör tekli eklemedeki gibi zorunludur: operatörsüz kart başvuru
    formundaki stok kutusunda süzülemez.
    """

    # Ayraç olarak boşluk ve noktalama kabul edilir; IMEI'nin kendi içinde
    # tire geçebildiği için tire ayraç sayılmaz.
    AYIRAC = re.compile(r"[\s,;|]+")

    operator = forms.ModelChoiceField(
        label="Operatör",
        queryset=Operator.objects.filter(aktif=True),
        widget=UnfoldAdminSelectWidget,
        help_text="Listedeki kartların hepsi bu operatöre yazılır.",
    )
    bayi = forms.ModelChoiceField(
        label="Zimmetlenecek bayi",
        queryset=User.objects.filter(is_active=True).order_by("username"),
        required=False,
        widget=UnfoldAdminSelectWidget,
        help_text=(
            "Boş bırakılırsa kartlar “Beklemede” olarak stoğa girer; "
            "sonradan listeden seçilip zimmetlenebilir."
        ),
    )
    aciklama = forms.CharField(
        label="Açıklama",
        max_length=255,
        required=False,
        widget=UnfoldAdminTextInputWidget(
            attrs={"placeholder": "Örn: 12 Eylül Turkcell kolisi"}
        ),
        help_text="Listedeki her karta aynı açıklama yazılır.",
    )
    imeiler = forms.CharField(
        label="SIM / IMEI listesi",
        widget=UnfoldAdminTextareaWidget(
            attrs={
                "rows": 12,
                "placeholder": "8990011122233344455\n8990011122233344456\n8990011122233344457",
            }
        ),
    )

    def clean_imeiler(self):
        """Listeyi ayrıştırır; kendi içindeki tekrarları eler.

        Aynı numaranın listede iki kez geçmesi kopyala-yapıştırın olağan
        sonucu; hata verip bütün listeyi geri çevirmek yerine tekrarı bir
        kez alıp kaç tanesinin elendiğini söylüyoruz.
        """
        numaralar = []
        self.tekrar_edenler = []
        for parca in self.AYIRAC.split(self.cleaned_data["imeiler"]):
            parca = parca.strip()
            if not parca:
                continue
            if len(parca) > 40:
                raise forms.ValidationError(
                    f"“{parca[:40]}…” 40 karakterden uzun; bu bir IMEI değil. "
                    "Listede sütun başlığı ya da yapıştırma artığı olabilir."
                )
            if parca in numaralar:
                self.tekrar_edenler.append(parca)
                continue
            numaralar.append(parca)

        if not numaralar:
            raise forms.ValidationError("Listede hiç numara yok.")
        return numaralar


class ArizaFiltresi(admin.SimpleListFilter):
    """Arızalı kartın hangi adımı açık?

    Bozuk kart üç adımda kapanır (bayiden alındı, yerine kart verildi,
    operatörden değişimi geldi); yönetici "elimde kaç bozuk kart var, kaçını
    bayiden almadım" sorusunu listeyi tarayarak değil süzerek cevaplasın.
    Özet sayfasındaki sayılar da bu süzgece bağlanır.
    """

    title = "arıza takibi"
    parameter_name = "ariza"

    def lookups(self, request, model_admin):
        return (
            ("bayide", "Bayiden alınmadı"),
            ("yerine", "Yerine kart verilmedi"),
            ("operator", "Operatörden değişimi bekleniyor"),
            ("acik", "Açık işi olan"),
            ("kapandi", "Kapandı"),
        )

    def queryset(self, request, sorgu):
        if self.value() is None:
            return sorgu
        arizali = sorgu.filter(durum=SimKartDurumu.ARIZALI)
        bayide = Q(bayi__isnull=False, iade_alinma_tarihi__isnull=True)
        yerine = Q(bayi__isnull=False, yerine_verilen__isnull=True)
        operator = Q(degisim_tarihi__isnull=True)
        if self.value() == "bayide":
            return arizali.filter(bayide)
        if self.value() == "yerine":
            return arizali.filter(yerine)
        if self.value() == "operator":
            return arizali.filter(operator)
        if self.value() == "acik":
            return arizali.filter(bayide | yerine | operator)
        if self.value() == "kapandi":
            return arizali.exclude(bayide | yerine | operator)
        return sorgu


@admin.register(SimKart)
class SimKartAdmin(ModelAdmin):
    list_display = (
        "imei", "zimmetli_bayi", "operator", "durum_rozeti", "ariza_takibi",
        "basvuru", "olusturma_tarihi",
    )
    list_filter = ("durum", ArizaFiltresi, "operator", "bayi")
    search_fields = (
        "imei", "bayi__username", "bayi__first_name", "bayi__last_name",
        "bayi__bayi_profili__unvan", "basvuru__referans_no",
    )
    autocomplete_fields = ("bayi", "operator", "basvuru", "yerine_verilen")
    readonly_fields = ("ariza_tarihi", "ariza_bildiren")
    date_hierarchy = "olusturma_tarihi"
    actions = (
        "bayiye_ata",
        "bayiden_geri_al",
        "arizali_isaretle",
        "bayiden_alindi_isaretle",
        "degisim_geldi_isaretle",
    )
    fieldsets = (
        (None, {"fields": ("imei", "operator", "bayi", "durum", "basvuru", "aciklama")}),
        (
            "Arıza takibi",
            {
                "fields": (
                    "ariza_tarihi",
                    "ariza_bildiren",
                    "iade_alinma_tarihi",
                    "yerine_verilen",
                    "degisim_tarihi",
                ),
                "description": (
                    "Yalnızca arızalı kartta anlamlıdır. Günlük iş listedeki "
                    "“Takip” düğmesinden yürür; buradaki alanlar düzeltme içindir. "
                    "Para hareketi yoktur: bayiye para değil kart verilir."
                ),
                "classes": ("collapse",),
            },
        ),
    )
    # Listenin üstünde "Ekle"nin yanında "Toplu ekle" düğmesi çizilsin.
    change_list_template = "admin/bayi/simkart/change_list.html"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "bayi", "bayi__bayi_profili", "operator", "basvuru", "yerine_verilen"
        )

    # -- adresler ---------------------------------------------------------

    def get_urls(self):
        return [
            path(
                "toplu-ekle/",
                self.admin_site.admin_view(self.toplu_ekle),
                name="bayi_simkart_toplu_ekle",
            ),
            path(
                "<int:object_id>/ariza/",
                self.admin_site.admin_view(self.ariza_sayfasi),
                name="bayi_simkart_ariza",
            ),
            *super().get_urls(),
        ]

    # -- arıza takibi -----------------------------------------------------
    #
    # Bozuk kart için para hareketi yok, kart takası var: bayi kartın
    # parasını zaten ödedi, ona kart borçluyuz. Üç adım tek sayfada durur —
    # kartın "dosyası" — ve her adım POST ile işler; listedeki düğme yalnızca
    # sayfayı açar. Satır işlemleri satır başına süzülemediği için düğme
    # `ariza_takibi` sütununda koşullu çizilir.

    def ariza_sayfasi(self, request, object_id):
        from apps.bayi.services import (
            ArizaHatasi,
            sim_bayiden_alindi,
            sim_degisimi_alindi,
            sim_yerine_ver,
        )

        kart = self.get_object(request, object_id)
        if kart is None:
            raise Http404("SIM kart bulunamadı.")
        if not self.has_change_permission(request, kart):
            raise Http404("Bu ekrana erişim yetkiniz yok.")
        if not kart.arizali:
            self.message_user(request, f"{kart.imei} arızalı değil.", messages.INFO)
            return redirect("admin:bayi_simkart_changelist")

        buraya = reverse("admin:bayi_simkart_ariza", args=[kart.pk])

        if request.method == "POST":
            adim = request.POST.get("adim")
            try:
                if adim == "bayiden_alindi":
                    sim_bayiden_alindi(kart)
                    self.message_user(request, f"{kart.imei} bayiden alındı.", messages.SUCCESS)
                elif adim == "yerine_ver":
                    yeni = SimKart.objects.filter(pk=request.POST.get("yeni_kart") or 0).first()
                    if yeni is None:
                        raise ArizaHatasi("Stoktan bir kart seçin.")
                    sim_yerine_ver(kart, yeni)
                    self.message_user(
                        request,
                        f"{yeni.imei} {kullanici_etiketi(kart.bayi)} bayisine zimmetlendi "
                        f"({kart.imei} yerine).",
                        messages.SUCCESS,
                    )
                elif adim == "degisim_geldi":
                    sim_degisimi_alindi(kart)
                    self.message_user(
                        request,
                        f"{kart.imei} için operatörden değişim alındı. Yeni kartı "
                        "“Toplu ekle” ile stoğa girin.",
                        messages.SUCCESS,
                    )
                else:
                    raise ArizaHatasi("Bilinmeyen adım.")
            except ArizaHatasi as hata:
                self.message_user(request, str(hata), messages.ERROR)
            return redirect(buraya)

        # Yerine verilecek kart: stokta ve aynı operatörün kartı olmalı.
        stok = SimKart.objects.filter(durum=SimKartDurumu.BEKLEMEDE, bayi__isnull=True)
        if kart.operator_id:
            stok = stok.filter(Q(operator=kart.operator) | Q(operator__isnull=True))
        return render(
            request,
            "admin/bayi/sim_ariza.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Arıza takibi · {kart.imei}",
                "opts": self.model._meta,
                "kart": kart,
                "bayi_etiketi": kullanici_etiketi(kart.bayi) if kart.bayi_id else "",
                "stok": list(stok.select_related("operator").order_by("imei")[:300]),
                "acik_isler": kart.acik_ariza_isleri,
            },
        )

    @admin.display(description="Arıza takibi")
    def ariza_takibi(self, obj):
        """Arızalı satırda açık adımlar ve dosyayı açan düğme."""
        if not obj.arizali:
            return ""
        isler = obj.acik_ariza_isleri
        ozet = (
            format_html_join(
                "", '<span style="display:block;color:#B45309;font-size:.75rem">{}</span>',
                ((i,) for i in isler),
            )
            if isler
            else format_html('<span style="color:#0F8A4D;font-size:.75rem">Kapandı</span>')
        )
        return format_html(
            '{}<a href="{}" style="display:inline-block;margin-top:.2rem;border:1px solid #e3e8f0;'
            'border-radius:.375rem;padding:.2rem .55rem;font-size:.75rem;font-weight:600;'
            'white-space:nowrap;text-decoration:none;color:#0E5E5B">Takip</a>',
            ozet,
            reverse("admin:bayi_simkart_ariza", args=[obj.pk]),
        )

    def toplu_ekle(self, request):
        """Yapıştırılan listeden tek seferde çok sayıda SIM kart açar.

        Kartlar operatörden koli koli geliyor; her IMEI için ayrı ekleme
        ekranı açmak günlük işi kilitliyordu.

        Zaten kayıtlı numaralar **hata değil, atlanan satırdır**: yönetici
        çoğu zaman bir kolinin devamını yapıştırıyor ve araya önceden
        girilmiş birkaç kart karışıyor. Bütün listeyi geri çevirmek, hangi
        satırın tekrar olduğunu elle aramak demekti — kaç tanesinin neden
        atlandığı yazılır, kalanı girilir.
        """
        if not self.has_add_permission(request):
            raise Http404("Bu ekrana erişim yetkiniz yok.")

        if request.method == "POST":
            form = TopluSimFormu(request.POST)
            if form.is_valid():
                return self._toplu_kaydet(request, form)
        else:
            form = TopluSimFormu()

        return render(
            request,
            "admin/bayi/toplu_sim.html",
            {
                **self.admin_site.each_context(request),
                "title": "Toplu SIM kart ekle",
                "form": form,
                "opts": self.model._meta,
            },
        )

    def _toplu_kaydet(self, request, form):
        numaralar = form.cleaned_data["imeiler"]
        bayi = form.cleaned_data["bayi"]

        # Veritabanında olanlar atlanır; `imei` tekil olduğu için bunları
        # yazmaya çalışmak bütün işlemi düşürürdü.
        kayitli = set(
            SimKart.objects.filter(imei__in=numaralar).values_list("imei", flat=True)
        )
        yeniler = [n for n in numaralar if n not in kayitli]

        # Durum `save()` ile aynı kurala uyar: bayisi olan kart "Bayiye
        # Atandı", olmayan "Beklemede". `bulk_create` model `save()`'ini
        # çağırmadığı için burada elle yazılıyor.
        durum = SimKartDurumu.ATANDI if bayi else SimKartDurumu.BEKLEMEDE
        SimKart.objects.bulk_create(
            [
                SimKart(
                    imei=imei,
                    operator=form.cleaned_data["operator"],
                    bayi=bayi,
                    durum=durum,
                    aciklama=form.cleaned_data["aciklama"],
                )
                for imei in yeniler
            ]
        )

        if yeniler:
            nereye = (
                f"{bayi.get_username()} bayisine zimmetli"
                if bayi
                else "stoğa (Beklemede)"
            )
            self.message_user(
                request,
                f"{len(yeniler)} SIM kart {nereye} eklendi.",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request, "Hiç yeni kart eklenmedi.", messages.WARNING
            )

        # Atlananlar adıyla söylenir: yönetici hangi satırın neden girmediğini
        # listeyi tarayarak aramasın.
        if kayitli:
            self.message_user(
                request,
                f"{len(kayitli)} numara zaten kayıtlı olduğu için atlandı: "
                + self._numara_ozeti(sorted(kayitli)),
                messages.WARNING,
            )
        tekrar = getattr(form, "tekrar_edenler", [])
        if tekrar:
            self.message_user(
                request,
                f"{len(tekrar)} numara listede birden çok kez yazılmıştı, "
                "bir kez alındı: " + self._numara_ozeti(tekrar),
                messages.INFO,
            )

        return redirect("admin:bayi_simkart_changelist")

    @staticmethod
    def _numara_ozeti(numaralar, sinir=15):
        """Uyarı mesajı ekranı kaplamasın: ilk birkaçını yazıp kalanını sayar."""
        gosterilen = ", ".join(numaralar[:sinir])
        kalan = len(numaralar) - sinir
        return f"{gosterilen} (+{kalan} tane daha)" if kalan > 0 else gosterilen

    @admin.display(description="Zimmetli Bayi", ordering="bayi__username")
    def zimmetli_bayi(self, obj):
        """Kartın kimde olduğu tek bakışta okunmalı.

        Kullanıcı adı telefon numarasıdır; numara tek başına hangi firma
        olduğunu anlatmıyor. Ünvan varsa o yazılır, numara altında durur.
        """
        if not obj.bayi_id:
            return format_html('<span style="color:#6F7B8F">stokta · zimmetsiz</span>')
        return kullanici_etiketi_html(obj.bayi)

    @admin.display(description="Durum")
    def durum_rozeti(self, obj):
        renkler = {
            "beklemede": "#6F7B8F",
            "atandi": "#0E5E5B",
            "kullanildi": "#0F8A4D",
            "arizali": "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#64748b"),
            obj.get_durum_display(),
        )

    # -- toplu işlemler ---------------------------------------------------

    @admin.action(description="Seçili SIM kartları bir bayiye zimmetle")
    def bayiye_ata(self, request, secilenler):
        if "uygula" in request.POST:
            form = SimAtamaFormu(request.POST)
            if form.is_valid():
                bayi = form.cleaned_data["bayi"]
                # Kullanılmış kart başka bayiye devredilmez; arızalı kart
                # zimmetlenirse "sağlam" görünüp başvuruya girerdi.
                atanabilir = secilenler.exclude(
                    durum__in=[SimKartDurumu.KULLANILDI, SimKartDurumu.ARIZALI]
                )
                adet = atanabilir.update(bayi=bayi, durum=SimKartDurumu.ATANDI)
                atlanan = secilenler.count() - adet
                self.message_user(
                    request,
                    f"{adet} SIM kart {kullanici_etiketi(bayi)} bayisine zimmetlendi"
                    + (
                        f", {atlanan} tanesi kullanılmış ya da arızalı olduğu için atlandı."
                        if atlanan
                        else "."
                    ),
                    messages.SUCCESS,
                )
                return None
        else:
            form = SimAtamaFormu()

        return render(
            request,
            "admin/bayi/sim_ata.html",
            {
                **self.admin_site.each_context(request),
                "title": "SIM kart zimmetle",
                "form": form,
                "kartlar": secilenler,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Seçili SIM kartları bayiden geri al (Beklemede'ye döner)")
    def bayiden_geri_al(self, request, secilenler):
        """Kartın bayiyle bağını koparır ve Beklemede'ye döndürür.

        Kullanılmış kartlara dokunulmaz: onlar bir başvuruya bağlı. Arızalı
        kart da stoğa dönmez — bozuk kartın bayiden alınması arıza takibinde
        ayrı bir adımdır, kartı sağlam stoğa karıştırmaz.
        """
        geri_alinabilir = secilenler.exclude(
            durum__in=[SimKartDurumu.KULLANILDI, SimKartDurumu.ARIZALI]
        )
        adet = geri_alinabilir.update(bayi=None, durum=SimKartDurumu.BEKLEMEDE)
        atlanan = secilenler.count() - adet
        self.message_user(
            request,
            f"{adet} SIM kart geri alındı"
            + (
                f", {atlanan} tanesi kullanılmış ya da arızalı olduğu için atlandı."
                if atlanan
                else "."
            ),
            messages.SUCCESS if adet else messages.WARNING,
        )

    @admin.action(description="Seçili SIM kartları arızalı işaretle")
    def arizali_isaretle(self, request, secilenler):
        from apps.bayi.services import sim_arizali_isaretle

        adet = 0
        for kart in secilenler.exclude(durum=SimKartDurumu.ARIZALI):
            sim_arizali_isaretle(kart, bildiren=request.user)
            adet += 1
        self.message_user(
            request,
            f"{adet} SIM kart arızalı işaretlendi. Takibi listedeki “Takip” düğmesinden.",
            messages.SUCCESS,
        )

    @admin.action(description="Seçili arızalı kartlar bayiden alındı")
    def bayiden_alindi_isaretle(self, request, secilenler):
        """Bayi ziyaretinde beş bozuk kart birden teslim alınır; tek tek sayfa açılmasın."""
        from apps.bayi.services import sim_bayiden_alindi

        adet = sum(
            1 for kart in secilenler.filter(durum=SimKartDurumu.ARIZALI) if sim_bayiden_alindi(kart)
        )
        self.message_user(request, f"{adet} arızalı kart bayiden alındı işaretlendi.", messages.SUCCESS)

    @admin.action(description="Seçili arızalı kartların operatörden değişimi geldi")
    def degisim_geldi_isaretle(self, request, secilenler):
        from apps.bayi.services import sim_degisimi_alindi

        adet = sum(
            1 for kart in secilenler.filter(durum=SimKartDurumu.ARIZALI) if sim_degisimi_alindi(kart)
        )
        self.message_user(
            request,
            f"{adet} arızalı kartın değişimi alındı işaretlendi. Yeni kartları “Toplu ekle” ile stoğa girin.",
            messages.SUCCESS,
        )


@admin.register(Duyuru)
class DuyuruAdmin(ModelAdmin):
    list_display = ("baslik", "onemli", "yayin_tarihi", "aktif", "olusturma_tarihi")
    list_editable = ("onemli", "aktif")
    list_filter = ("aktif", "onemli")
    search_fields = ("baslik", "icerik")
    date_hierarchy = "olusturma_tarihi"


@admin.register(GenelAyarlar)
class GenelAyarlarAdmin(ModelAdmin):
    """Tek kayıtlı ayar ekranı.

    Liste görünümü anlamsız: tek satır var. Menüden tıklayan yönetici
    doğrudan düzenleme sayfasına düşer; ekleme ve silme kapalıdır, yoksa
    "hangi ayar geçerli" sorusu doğar.
    """

    fieldsets = (
        (
            "İletişim",
            {
                "fields": ("telefon", "eposta"),
                "description": (
                    "Kamuya açık sayfaların altında görünür: giriş ekranı, "
                    "tanıtım sayfası ve bayi başvuru formu. Boş bıraktığınız "
                    "alan hiç gösterilmez."
                ),
            },
        ),
        (
            "Döviz kuru",
            {
                "fields": ("usd_kuru", "usd_kuru_tarihi"),
                "description": (
                    "eSIM paketleri sağlayıcıdan dolarla alınır, bayiye lirayla "
                    "satılır. Kur eskirse fiyat maliyetin altına düşebilir; "
                    "eSIM Paketleri ekranındaki <b>Kuru güncelle</b> düğmesi "
                    "TCMB satış kurunu çeker. Elle de yazılabilir."
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect

        ayar = GenelAyarlar.getir()
        return redirect("admin:bayi_genelayarlar_change", ayar.pk)


class BayiBasvurusuAdminFormu(forms.ModelForm):
    """Fiyat kademesi seçilmeden onay kaydedilemez.

    Servis de kapıyı tutuyor (`bayi_hesabi_ac`) ama orada durdurmak kaydı
    "Onaylandı" bırakıp hesabı açmamak demek: yönetici onayladığını sanır,
    bayi giriş ekranında öğrenir. Formda durdurunca kayıt o duruma hiç
    geçmez ve hata alanın yanında çıkar.

    Hesabı zaten açılmış eski kayıtlar serbesttir: kademe artık cüzdanda
    yaşıyor, başvurudaki alan geçmiş bilgisidir.
    """

    class Meta:
        model = BayiBasvurusu
        fields = "__all__"

    def clean(self):
        temiz = super().clean()
        onay = temiz.get("durum") == BayiBasvuruDurumu.ONAYLANDI
        if onay and not temiz.get("bayi_grubu") and not self.instance.olusturulan_kullanici_id:
            self.add_error(
                "bayi_grubu",
                "Onaylamadan önce fiyat kademesini seçin. Kademesiz cüzdanda "
                "bayi grubuna bağlı hakediş kuralları işlemez; bayi başvuru "
                "girer, karşılığında hiçbir şey almaz.",
            )
        return temiz


@admin.register(BayiBasvurusu)
class BayiBasvurusuAdmin(ModelAdmin):
    """Bayi olmak isteyenlerin bıraktığı talepler."""

    form = BayiBasvurusuAdminFormu

    list_display = (
        "ad_soyad", "irtibat_baglantisi", "durum_rozeti", "parola_secildi",
        "bayi_grubu", "olusturulan_kullanici", "olusturma_tarihi",
    )
    list_filter = ("durum", "bayi_grubu", "olusturma_tarihi")
    search_fields = ("isim", "soyisim", "irtibat")
    date_hierarchy = "olusturma_tarihi"
    readonly_fields = ("isim", "soyisim", "irtibat", "olusturma_tarihi")
    autocomplete_fields = ("olusturulan_kullanici",)
    actions = ("hesap_ac", "gorusuldu_isaretle", "reddet")
    fieldsets = (
        (
            "Başvuran",
            {
                "fields": ("isim", "soyisim", "irtibat", "olusturma_tarihi"),
                "description": "Bu bilgiler başvuran tarafından girildi, değiştirilemez.",
            },
        ),
        (
            "Değerlendirme",
            {
                "fields": ("durum", "bayi_grubu", "notlar", "olusturulan_kullanici"),
                "description": (
                    "Durumu “Onaylandı” yapıp kaydetmek hesabı da açar; "
                    "listeden “Seçili başvurular için bayi hesabı aç” işlemi "
                    "de aynı işi yapar. Kullanıcı adı telefon numarası olur, "
                    "parola başvuranın kendi seçtiğidir. Fiyat kademesi "
                    "onay için zorunludur: cüzdana onayla birlikte yazılır, "
                    "ayrıca cüzdan ekranına gitmek gerekmez."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("olusturulan_kullanici", "bayi_grubu")
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """“Açılan Hesap” kutusunun yanındaki ekle/düzenle/sil düğmelerini kaldırır.

        O kırmızı çöp kutusu seçimi değil, seçili kullanıcının **kendisini**
        siliyor. Yanlış hesap seçilince ilk refleks ona basmak oluyor ve
        yönetici hesabı bile silinebiliyor — bir kez silindi. Buradan yapılacak
        iş var olan bir hesabı başvuruya bağlamak; kullanıcı açmak, düzenlemek
        ve silmek Kullanıcılar ekranının işi.
        """
        alan = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if not hasattr(alan, "widget"):
            return alan

        if db_field.name == "olusturulan_kullanici":
            alan.widget.can_add_related = False
            alan.widget.can_change_related = False
            alan.widget.can_delete_related = False
        elif db_field.name == "bayi_grubu":
            # Yeni bir kademe açmak buradan makul; var olanı düzenlemek ya da
            # silmek değil. Grup silinince o gruptaki bütün cüzdanların fiyat
            # kademesi sessizce boşalır — tek bir başvuru ekranından
            # verilebilecek bir karar değil.
            alan.widget.can_change_related = False
            alan.widget.can_delete_related = False
        return alan

    @admin.display(description="Ad Soyad", ordering="isim")
    def ad_soyad(self, obj):
        return obj.ad_soyad

    @admin.display(description="Telefon")
    def irtibat_baglantisi(self, obj):
        return format_html(
            '<a href="tel:{}" style="font-weight:600">{}</a>', obj.irtibat, obj.irtibat
        )

    @admin.display(description="Durum")
    def durum_rozeti(self, obj):
        renkler = {
            "yeni": "#0E5E5B",
            "gorusuldu": "#B45309",
            "onaylandi": "#0F8A4D",
            "reddedildi": "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    @admin.display(description="Parola", boolean=True)
    def parola_secildi(self, obj):
        """Başvuran parolasını seçmiş mi? Seçmediyse hesap girişe kapalı açılır."""
        return obj.parolasini_secti

    def save_model(self, request, obj, form, change):
        """Durum “Onaylandı” seçilince hesap da açılır.

        Sistemde günlük işte tek elle yapılan şey durumu değiştirmektir;
        hesabın ayrıca listeden bir işlemle açılmasını beklemek sessiz bir
        tuzaktı. Yönetici onayladığını sanıyor, bayi giriş ekranında
        “kullanıcı adı veya parola hatalı” görüyordu. Mantık yine tek yerde:
        `bayi_hesabi_ac`.
        """
        super().save_model(request, obj, form, change)

        if obj.durum != BayiBasvuruDurumu.ONAYLANDI or obj.olusturulan_kullanici_id:
            return

        try:
            kullanici, _ = bayi_hesabi_ac(obj)
        except HesapAcilamadi as hata:
            self.message_user(request, str(hata), messages.ERROR)
            return

        self._acilanlari_bildir(request, [kullanici])

    def _acilanlari_bildir(self, request, kullanicilar):
        """Açılan hesapları bildirir; eksik kalanları ayrıca uyarır."""
        self.message_user(
            request,
            format_html(
                "{} hesap açıldı: {}. Kullanıcı adı telefon numarasıdır; "
                "parolayı başvuran kendisi seçti.",
                len(kullanicilar),
                format_html_join(
                    ", ", "{} ({})",
                    (
                        (k.get_username(), self._kademe_adi(k))
                        for k in kullanicilar
                    ),
                ),
            ),
            messages.SUCCESS,
        )

        # Kademesiz hesap artık hiç açılmıyor (`bayi_hesabi_ac` kapıda
        # durduruyor); burada ayrıca uyarılacak bir şey kalmadı.

        # Parolasız açılan hesap girişe kapalıdır. Bunu yöneticiye burada
        # söylemezsek kimse fark etmez; bayi giriş ekranında öğrenir.
        parolasiz = [
            k.get_username() for k in kullanicilar if not k.has_usable_password()
        ]
        if parolasiz:
            self.message_user(
                request,
                format_html(
                    "{} hesabının parolası yok — başvuruda parola seçilmemiş. "
                    "Bu hesap girişe kapalı; kullanıcı sayfasından parola "
                    "belirleyin.",
                    ", ".join(parolasiz),
                ),
                messages.WARNING,
            )

    @staticmethod
    def _kademe_adi(kullanici):
        cuzdan = getattr(kullanici, "cuzdan", None)
        grup = getattr(cuzdan, "grup", None)
        return grup.ad if grup else "kademesiz"

    @admin.action(description="Seçili başvurular için bayi hesabı aç")
    def hesap_ac(self, request, secilenler):
        """Kullanıcı adı telefon, parola başvuranın seçtiği parola."""
        acilan, atlanan, hatalar = [], 0, []

        for basvuru in secilenler:
            try:
                kullanici, yeni = bayi_hesabi_ac(basvuru)
            except HesapAcilamadi as hata:
                hatalar.append(f"{basvuru.ad_soyad}: {hata}")
                continue
            if yeni:
                acilan.append(kullanici)
            else:
                atlanan += 1

        if acilan:
            self._acilanlari_bildir(request, acilan)
        if atlanan:
            self.message_user(
                request, f"{atlanan} başvurunun hesabı zaten açılmıştı.", messages.INFO
            )
        for satir in hatalar:
            self.message_user(request, satir, messages.ERROR)

    @admin.action(description="Görüşüldü olarak işaretle")
    def gorusuldu_isaretle(self, request, secilenler):
        adet = secilenler.update(durum=BayiBasvuruDurumu.GORUSULDU)
        self.message_user(request, f"{adet} başvuru görüşüldü işaretlendi.", messages.SUCCESS)

    @admin.action(description="Reddet")
    def reddet(self, request, secilenler):
        adet = secilenler.update(durum=BayiBasvuruDurumu.REDDEDILDI)
        self.message_user(request, f"{adet} başvuru reddedildi.", messages.SUCCESS)
