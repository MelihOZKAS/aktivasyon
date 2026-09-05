from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.shortcuts import render
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from apps.finans.admin import TarifeParaKuraliInline
from apps.finans.models import KuralYonu
from apps.katalog.models import (
    BasvuruKategorisi,
    Kampanya,
    KategoriAlani,
    Operator,
    Tarife,
)
from apps.katalog.varsayilan_alanlar import varsayilan_alanlari_ac

SIFIR = Decimal("0.00")


class KategoriAlaniInline(TabularInline):
    model = KategoriAlani
    extra = 0
    fields = ("sira", "etiket", "kod", "tip", "cekirdek_alan", "grup", "zorunlu", "max_uzunluk", "aktif")
    ordering = ("sira",)
    show_change_link = True


class TarifeInline(TabularInline):
    """Bu kategoride geçerli tarifeler.

    Tarifenin kategorisi çoğullaştığı için satır içi tablo doğrudan Tarife
    üzerinde kurulamıyor; bağlantı tablosu üzerinden kuruluyor. Buradan var
    olan bir tarife kategoriye eklenir ya da çıkarılır; tarifenin kendi
    ayrıntıları (fiyat, açıklama, görsel) Tarifeler ekranından girilir.
    """

    model = Tarife.kategoriler.through
    verbose_name = "Bu kategoride geçerli tarife"
    verbose_name_plural = "Bu kategoride geçerli tarifeler"
    extra = 0
    autocomplete_fields = ("tarife",)


class KampanyaInline(TabularInline):
    model = Kampanya
    extra = 0
    fields = ("ad", "baslangic_tarihi", "bitis_tarihi", "sira", "aktif")
    show_change_link = True


@admin.register(Operator)
class OperatorAdmin(ModelAdmin):
    list_display = ("ad", "renk_rozeti", "sira", "aktif")
    list_editable = ("sira", "aktif")
    search_fields = ("ad",)
    list_filter = ("aktif",)
    prepopulated_fields = {"slug": ("ad",)}

    @admin.display(description="Renk")
    def renk_rozeti(self, obj):
        return format_html(
            '<span style="display:inline-block;width:1.5rem;height:1.5rem;'
            'border-radius:.375rem;background:{};border:1px solid rgba(0,0,0,.1)"></span>',
            obj.renk,
        )


@admin.register(BasvuruKategorisi)
class BasvuruKategorisiAdmin(ModelAdmin):
    list_display = ("ad", "musteri_tipi", "alan_sayisi", "tarife_sayisi", "sira", "aktif")
    list_editable = ("sira", "aktif")
    list_filter = ("aktif", "musteri_tipi")
    search_fields = ("ad", "aciklama")
    prepopulated_fields = {"slug": ("ad",)}
    filter_horizontal = ("operatorler",)
    inlines = [KategoriAlaniInline, TarifeInline]
    fieldsets = (
        ("Tanım", {"fields": ("ad", "slug", "aciklama", "ikon")}),
        (
            "Kapsam",
            {
                "fields": (
                    "operatorler", "musteri_tipi", "tarife_zorunlu",
                    "sim_karsiligi_gerekir",
                ),
            },
        ),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )

    def save_related(self, request, form, formsets, change):
        """Yeni kategori formuyla birlikte açılır.

        Kategori panelden açıldığında hiç alanı olmuyordu: bayi boş bir form
        görüyor, yönetici on beş satırı elle giriyordu. Varsayılanlar açık
        gelir, gerekmeyeni yönetici aşağıdaki tablodan kapatır.

        `save_model` değil `save_related`: satır içi tablo o sırada
        kaydedilmiş oluyor, yöneticinin kendi eklediği alanla aynı koddan
        ikinci bir kayıt açılmıyor.
        """
        super().save_related(request, form, formsets, change)

        if change:
            return

        acilan = varsayilan_alanlari_ac(form.instance)
        if acilan:
            self.message_user(
                request,
                f"{acilan} form alanı hazır geldi. Bu kategoride sorulmayacak "
                "alanların “Aktif” kutusunu kapatın.",
                messages.INFO,
            )

    @admin.display(description="Form Alanı")
    def alan_sayisi(self, obj):
        return obj.alanlar.count()

    @admin.display(description="Tarife")
    def tarife_sayisi(self, obj):
        return obj.tarifeler.count()


@admin.register(Tarife)
class TarifeAdmin(ModelAdmin):
    list_display = (
        "ad", "kategori_listesi", "operator", "gorsel_var_mi", "kampanya_sayisi", "aktif"
    )
    list_filter = ("aktif", "kategoriler", "operator", "musteri_tipi")
    search_fields = ("ad", "kategoriler__ad", "operator__ad")
    autocomplete_fields = ("kategoriler", "operator")
    inlines = [TarifeParaKuraliInline, KampanyaInline]
    readonly_fields = ("gorsel_onizleme", "para_ozeti")
    fieldsets = (
        (
            "Tarife",
            {
                "fields": ("kategoriler", "operator", "ad", "musteri_tipi"),
                "description": (
                    "Aynı tarife birden çok kategoride geçerli olabilir. Operatör "
                    "aynı paketi hem numara taşımada hem yeni hatta veriyorsa "
                    "hepsini işaretleyin; tarifeyi ikinci kez açmanız gerekmez."
                ),
            },
        ),
        (
            "Para",
            {
                "fields": ("para_ozeti",),
                "description": (
                    "Bayiye vereceğiniz hakediş ile operatörden/tedarikçiden alacağınız "
                    "tutar sayfanın altındaki <b>Bu tarifenin parası</b> tablosuna girilir. "
                    "Aradaki fark kârınızdır."
                ),
            },
        ),
        (
            "Bayiye gösterilecek içerik",
            {
                "fields": ("kisa_aciklama", "aciklama", "gorsel", "gorsel_onizleme"),
                "description": (
                    "<b>Kısa açıklama</b> bayi bu tarifeyi başvuruda seçtiği anda "
                    "karşısına açılır; atlanmaması gereken bir uyarı için. "
                    "Açıklama ve görsel ise bayi panelindeki <b>Tarifeler</b> "
                    "sayfasında, tarife başlığının altında görünür."
                ),
            },
        ),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("operator")
            .prefetch_related("kategoriler")
        )

    @admin.display(description="Kategoriler")
    def kategori_listesi(self, obj):
        return obj.kategori_adlari

    @admin.display(description="Bu tarifede hesap")
    def para_ozeti(self, obj):
        """Alış, bayi fiyatı ve kâr tek tabloda.

        Yönetici üç kaydı ayrı ayrı açıp kafasında toplamasın. Alış iki
        kaynaktan olabilir (operatör ya da tedarikçi), bayi fiyatı gruba göre
        değişebilir; tablo ikisinin her bileşimi için kârı yazar.
        Kâr = alışım + bayiden tahsilat − bayiye ödenen. Kampanyaya özel
        kurallar sayılmaz; onlar kampanyanın kendi hesabı.
        """
        if obj is None or obj.pk is None:
            return "Tarife kaydedildikten sonra aşağıdaki tabloya girilir."

        kurallar = list(
            obj.ucret_kurallari.filter(aktif=True, kampanya__isnull=True)
            .select_related("bayi_grubu", "tedarikci__bayi_profili")
        )
        if not kurallar:
            return format_html(
                '<span style="color:#6F7B8F">Henüz fiyat girilmedi. Aşağıdaki '
                "<b>Bu tarifenin parası</b> tablosuna alış fiyatınızı ve bayiye "
                "ödeyeceğiniz tutarı girin.</span>"
            )

        alislar = []
        bayi_fiyatlari = {}
        for kural in kurallar:
            if kural.yon == KuralYonu.ANA_HAKEDIS:
                if kural.tedarikci_id:
                    profil = getattr(kural.tedarikci, "bayi_profili", None)
                    kaynak = (
                        profil.unvan
                        if profil and profil.unvan
                        else kural.tedarikci.get_username()
                    )
                else:
                    kaynak = obj.operator.ad if obj.operator_id else "Operatör"
                alislar.append((kaynak, kural.tutar))
            else:
                grup = kural.bayi_grubu.ad if kural.bayi_grubu_id else "Tüm bayiler"
                bayi_fiyatlari.setdefault(grup, {})[kural.yon] = kural.tutar

        # Yarım girilmiş tabloda da kâr sütunu anlamlı kalsın.
        if not alislar:
            alislar = [("girilmedi", SIFIR)]
        if not bayi_fiyatlari:
            bayi_fiyatlari = {"Tüm bayiler": {}}

        satirlar = []
        for kaynak, alis in sorted(alislar):
            for grup, tutarlar in sorted(bayi_fiyatlari.items()):
                odenen = tutarlar.get(KuralYonu.HAKEDIS, SIFIR)
                tahsil = tutarlar.get(KuralYonu.TAHSILAT, SIFIR)
                kar = alis + tahsil - odenen
                satirlar.append((
                    kaynak, alis, grup, odenen, tahsil,
                    "#0F8A4D" if kar >= SIFIR else "#D42046", kar,
                ))

        hucre = 'padding:.3rem .9rem .3rem 0'
        return format_html(
            '<table style="border-collapse:collapse;font-size:.85rem">'
            '<tr style="text-align:left;color:#6F7B8F">'
            '<th style="{0}">Kimden alıyorum</th><th style="{0}">Alışım</th>'
            '<th style="{0}">Bayi grubu</th><th style="{0}">Bayiye</th>'
            '<th style="{0}">Bayiden</th><th style="padding:.3rem 0">Kâr</th>'
            "</tr>{1}</table>",
            hucre,
            format_html_join(
                "",
                '<tr><td style="{0}">{1}</td><td style="{0}">{2} ₺</td>'
                '<td style="{0}">{3}</td><td style="{0}">{4} ₺</td>'
                '<td style="{0}">{5} ₺</td>'
                '<td style="padding:.3rem 0"><b style="color:{6}">{7} ₺</b></td></tr>',
                ((hucre, *satir) for satir in satirlar),
            ),
        )

    @display(description="Görsel", boolean=True)
    def gorsel_var_mi(self, obj):
        return bool(obj.gorsel)

    @admin.display(description="Önizleme")
    def gorsel_onizleme(self, obj):
        if not obj.gorsel:
            return "Henüz görsel yüklenmedi."
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            '<img src="{}" style="max-width:22rem;border-radius:.5rem;'
            'border:1px solid rgba(0,0,0,.1)"></a>',
            obj.gorsel.url,
            obj.gorsel.url,
        )

    @admin.display(description="Kampanya")
    def kampanya_sayisi(self, obj):
        return obj.kampanyalar.count()


@admin.register(Kampanya)
class KampanyaAdmin(ModelAdmin):
    list_display = ("ad", "tarife", "baslangic_tarihi", "bitis_tarihi", "gecerli_mi", "aktif")
    list_filter = ("aktif", "tarife__kategoriler", "tarife__operator")
    search_fields = ("ad", "tarife__ad")
    autocomplete_fields = ("tarife",)
    fieldsets = (
        (
            "Kampanya",
            {
                "fields": ("tarife", "ad"),
                "description": (
                    "Kampanya bayiye başvuru formunda <b>adıyla</b> listelenir; "
                    "görseli ve açıklaması yoktur. Anlatılacak bir şey varsa "
                    "tarifenin açıklamasına yazın."
                ),
            },
        ),
        ("Geçerlilik", {"fields": ("baslangic_tarihi", "bitis_tarihi", "sira", "aktif")}),
    )

    @admin.display(description="Şu An Geçerli", boolean=True)
    def gecerli_mi(self, obj):
        return obj.su_an_gecerli


class AlanKopyalaFormu(forms.Form):
    """Bir kategorinin alanlarını başka kategoriye taşımak için."""

    hedef = forms.ModelChoiceField(
        label="Hangi kategoriye kopyalansın?",
        queryset=BasvuruKategorisi.objects.filter(aktif=True),
    )


@admin.register(KategoriAlani)
class KategoriAlaniAdmin(ModelAdmin):
    list_display = (
        "etiket", "kategori", "tip_gosterimi", "kod", "grup", "zorunlu", "sira", "aktif"
    )
    list_editable = ("sira", "aktif")
    list_filter = ("aktif", "kategori", "tip", "zorunlu", "cekirdek_alan")
    search_fields = ("etiket", "kod", "kategori__ad")
    autocomplete_fields = ("kategori", "kosul_alani")
    actions = ("alanlari_kopyala",)
    fieldsets = (
        (
            "Tanım",
            {
                "fields": ("kategori", "etiket", "kod", "tip", "cekirdek_alan", "grup"),
                "description": (
                    "Bayinin formda göreceği bir soru tanımlıyorsunuz. "
                    "<b>Etiket</b> ekranda görünen başlık, <b>Alan Kodu</b> "
                    "verinin saklandığı anahtar, <b>Alan Tipi</b> ise çıkacak "
                    "kutunun türü.<br><br>"
                    "<b>Çekirdek Alan çoğu zaman boş kalır.</b> Yalnızca "
                    "başvurunun kendi kolonu olan bilgilerde (isim, TC no, "
                    "telefon) doldurulur; o zaman değer aranabilir olur. Bir "
                    "kategoride aynı çekirdek alan iki kez kullanılamaz ve "
                    "görsel/dosya alanları çekirdek alan olamaz. "
                    "<b>İkinci bir kimlik görseli</b> ekliyorsanız (çocuk, "
                    "ebeveyn…) Çekirdek Alan’ı boş bırakın, Alan Tipi’ni "
                    "<i>Resim</i>, Bölüm Başlığı’nı <i>Belgeler</i> yapın."
                ),
            },
        ),
        ("Davranış", {"fields": ("zorunlu", "yardim_metni", "placeholder", "secenekler")}),
        (
            "Doğrulama",
            {
                "classes": ("collapse",),
                "fields": ("dogrulama_deseni", "min_uzunluk", "max_uzunluk"),
            },
        ),
        (
            "Koşullu Gösterim",
            {"classes": ("collapse",), "fields": ("kosul_alani", "kosul_degeri")},
        ),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("kategori")

    @display(description="Tip")
    def tip_gosterimi(self, obj):
        if obj.cekirdek_alan:
            return format_html(
                '{} <span style="color:#0F8A4D;font-size:.72rem">· aranabilir</span>',
                obj.get_tip_display(),
            )
        return obj.get_tip_display()

    @admin.action(description="Seçili alanları başka kategoriye kopyala")
    def alanlari_kopyala(self, request, secilenler):
        """Aynı form yapısını yeniden kurmak yerine kopyalayıp düzenlemek için."""
        if "uygula" in request.POST:
            form = AlanKopyalaFormu(request.POST)
            if form.is_valid():
                hedef = form.cleaned_data["hedef"]
                eklenen = atlanan = 0
                for alan in secilenler:
                    if alan.kategori_id == hedef.pk:
                        atlanan += 1
                        continue
                    _, olusturuldu = KategoriAlani.objects.get_or_create(
                        kategori=hedef,
                        kod=alan.kod,
                        defaults={
                            "etiket": alan.etiket,
                            "tip": alan.tip,
                            # Çekirdek alan bir kategoride tek kez bulunabilir.
                            "cekirdek_alan": alan.cekirdek_alan
                            if not KategoriAlani.objects.filter(
                                kategori=hedef, cekirdek_alan=alan.cekirdek_alan
                            ).exclude(cekirdek_alan="").exists()
                            else "",
                            "grup": alan.grup,
                            "zorunlu": alan.zorunlu,
                            "yardim_metni": alan.yardim_metni,
                            "placeholder": alan.placeholder,
                            "secenekler": alan.secenekler,
                            "dogrulama_deseni": alan.dogrulama_deseni,
                            "min_uzunluk": alan.min_uzunluk,
                            "max_uzunluk": alan.max_uzunluk,
                            "sira": alan.sira,
                        },
                    )
                    eklenen += olusturuldu
                    atlanan += not olusturuldu

                self.message_user(
                    request,
                    f"{hedef.ad}: {eklenen} alan eklendi"
                    + (f", {atlanan} alan zaten vardı." if atlanan else "."),
                    messages.SUCCESS,
                )
                return None
        else:
            form = AlanKopyalaFormu()

        return render(
            request,
            "admin/katalog/alan_kopyala.html",
            {
                **self.admin_site.each_context(request),
                "title": "Alanları kopyala",
                "form": form,
                "alanlar": secilenler,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )
