import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as TemelGrupAdmin
from django.contrib.auth.admin import UserAdmin as TemelKullaniciAdmin
from django.contrib.auth.models import Group, User
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, StackedInline
from unfold.decorators import action as unfold_islem
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from django.contrib.auth import update_session_auth_hash
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

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
from apps.katalog.models import Operator

logger = logging.getLogger(__name__)


class BayiProfiliInline(StackedInline):
    model = BayiProfili
    can_delete = False
    extra = 0
    fields = (
        ("bayi_mi", "tedarikci_mi"),
        ("unvan", "yetkili_adi"),
        ("telefon", "sehir"),
        "adres",
        ("vergi_dairesi", "vergi_no"),
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
    list_display = (
        "username",
        "unvan_gosterimi",
        "bakiye_gosterimi",
        "email",
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


@admin.register(Group)
class GrupAdmin(TemelGrupAdmin, ModelAdmin):
    pass


@admin.register(BayiProfili)
class BayiProfiliAdmin(ModelAdmin):
    list_display = ("kullanici", "unvan", "rol_rozeti", "telefon", "sehir")
    search_fields = ("kullanici__username", "unvan", "yetkili_adi", "telefon", "vergi_no")
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


@admin.register(SimKart)
class SimKartAdmin(ModelAdmin):
    list_display = (
        "imei", "zimmetli_bayi", "operator", "durum_rozeti", "basvuru", "olusturma_tarihi",
    )
    list_filter = ("durum", "operator", "bayi")
    search_fields = ("imei", "bayi__username", "basvuru__referans_no")
    autocomplete_fields = ("bayi", "operator", "basvuru")
    date_hierarchy = "olusturma_tarihi"
    actions = ("bayiye_ata", "bayiden_geri_al", "arizali_isaretle")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "bayi", "bayi__bayi_profili", "operator", "basvuru"
        )

    @admin.display(description="Zimmetli Bayi", ordering="bayi__username")
    def zimmetli_bayi(self, obj):
        """Kartın kimde olduğu tek bakışta okunmalı.

        Kullanıcı adı telefon numarasıdır; numara tek başına hangi firma
        olduğunu anlatmıyor. Ünvan varsa o yazılır, numara altında durur.
        """
        if not obj.bayi_id:
            return format_html('<span style="color:#6F7B8F">stokta · zimmetsiz</span>')

        numara = obj.bayi.get_username()
        profil = getattr(obj.bayi, "bayi_profili", None)
        unvan = profil.unvan if profil and profil.unvan else ""
        if not unvan:
            return numara
        return format_html(
            '<span style="font-weight:600">{}</span><br>'
            '<span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            unvan,
            numara,
        )

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
                # Kullanılmış kartlar başka bayiye devredilmez.
                atanabilir = secilenler.exclude(durum=SimKartDurumu.KULLANILDI)
                adet = atanabilir.update(bayi=bayi, durum=SimKartDurumu.ATANDI)
                atlanan = secilenler.count() - adet
                self.message_user(
                    request,
                    f"{adet} SIM kart {bayi.get_username()} bayisine zimmetlendi"
                    + (f", {atlanan} tanesi kullanılmış olduğu için atlandı." if atlanan else "."),
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

        Kullanılmış kartlara dokunulmaz: onlar bir başvuruya bağlı.
        """
        geri_alinabilir = secilenler.exclude(durum=SimKartDurumu.KULLANILDI)
        adet = geri_alinabilir.update(bayi=None, durum=SimKartDurumu.BEKLEMEDE)
        atlanan = secilenler.count() - adet
        self.message_user(
            request,
            f"{adet} SIM kart geri alındı"
            + (f", {atlanan} tanesi kullanılmış olduğu için atlandı." if atlanan else "."),
            messages.SUCCESS if adet else messages.WARNING,
        )

    @admin.action(description="Seçili SIM kartları arızalı işaretle")
    def arizali_isaretle(self, request, secilenler):
        adet = secilenler.update(durum=SimKartDurumu.ARIZALI)
        self.message_user(request, f"{adet} SIM kart arızalı işaretlendi.", messages.SUCCESS)


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
