"""Mağaza yönetimi: ürün kataloğu ve siparişler."""

from django.contrib import admin, messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin
from unfold.decorators import display

from apps.bayi.etiket import kullanici_etiketi_html
from apps.esim.saglayicilar import SaglayiciHatasi
from apps.esim.services import esim_siparisi_iptal_et
from apps.finans.services import (
    SiparisVerilemez,
    siparis_durumunu_uygula,
)
from apps.magaza.models import Siparis, SiparisDurumu, Urun


@admin.register(Urun)
class UrunAdmin(ModelAdmin):
    list_display = ("gorsel_onizleme", "ad", "fiyat_gosterimi", "sira", "aktif")
    list_display_links = ("ad",)
    list_editable = ("sira", "aktif")
    list_filter = ("aktif",)
    search_fields = ("ad", "aciklama")
    fieldsets = (
        (
            "Ürün",
            {
                "fields": ("ad", "fiyat", "aciklama", "gorsel"),
                "description": (
                    "Bayi bu ürünü mağazada görür ve <b>bakiyesiyle</b> alır. "
                    "Fiyat tektir, bayi grubuna göre değişmez.<br><br>"
                    "<b>Stok tutulmaz.</b> Ürünler elden teslim ediliyor; kaç "
                    "adet kaldığını sistem bilmiyor. Satılmasını istemediğiniz "
                    "ürünün “Aktif” kutusunu kapatın — mağazada hiç görünmez, "
                    "verilmiş siparişler yerinde kalır."
                ),
            },
        ),
        ("Görünüm", {"fields": ("sira", "aktif")}),
    )

    @display(description="")
    def gorsel_onizleme(self, obj):
        if not obj.gorsel:
            return format_html('<span style="color:#94A3B8">görselsiz</span>')
        return format_html(
            '<img src="{}" style="width:44px;height:44px;object-fit:cover;'
            'border-radius:.375rem;border:1px solid #E3E8F0">',
            obj.gorsel.url,
        )

    @display(description="Fiyat", ordering="fiyat")
    def fiyat_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.fiyat)


@admin.register(Siparis)
class SiparisAdmin(ModelAdmin):
    list_display = (
        "referans_no",
        "olusturma_tarihi",
        "bayi_gosterimi",
        "urun_adi",
        "adet",
        "tutar_gosterimi",
        "durum_rozeti",
        "esim_gosterimi",
        "karar_dugmeleri",
    )
    list_filter = ("durum", "urun")
    search_fields = (
        "referans_no",
        "urun_adi",
        "bayi__username",
        "bayi__first_name",
        "bayi__last_name",
        "bayi__bayi_profili__unvan",
    )
    date_hierarchy = "olusturma_tarihi"
    autocomplete_fields = ("urun",)
    readonly_fields = (
        "referans_no", "bayi", "urun_adi", "adet", "birim_fiyat", "tutar",
        "bayi_notu", "para_islendi", "olusturma_tarihi",
    )
    fieldsets = (
        (
            "Sipariş",
            {
                "fields": (
                    "referans_no", "bayi", "urun", "urun_adi",
                    ("adet", "birim_fiyat", "tutar"),
                    "bayi_notu", "olusturma_tarihi",
                ),
                "description": (
                    "Sipariş kalemleri değiştirilmez; tutar bayinin bakiyesinden "
                    "sipariş anında düşüldü."
                ),
            },
        ),
        (
            "Karar",
            {
                "fields": ("durum", "yonetim_notu", "para_islendi"),
                "description": (
                    "<b>Para, siparişin iptal edilmemiş olmasına bağlıdır.</b> "
                    "“İptal edildi” seçilip kaydedilirse tutar ters kayıtla "
                    "bayinin bakiyesine geri döner; iptalden çıkarılırsa "
                    "yeniden kesilir (bakiyesi yetmiyorsa kayıt reddedilir). "
                    "İptal sebebini <b>Yönetim Notu</b>'na yazın, bayi görür."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("bayi", "bayi__bayi_profili", "urun", "esim", "esim_yukleme")
        )

    @display(description="eSIM")
    def esim_gosterimi(self, obj):
        """eSIM siparişinin sağlayıcı tarafı ayrı ekranda; buradan oraya geçilir."""
        if obj.esim_yukleme_mi:
            return format_html(
                '<a href="{}" style="font-size:.75rem;font-weight:600;text-decoration:underline">yükleme · {}</a>',
                reverse("admin:esim_yukleme_change", args=[obj.esim_yukleme.pk]),
                obj.esim_yukleme.get_durum_display(),
            )
        if not obj.esim_mi:
            return ""
        return format_html(
            '<a href="{}" style="font-size:.75rem;font-weight:600;text-decoration:underline">{}</a>',
            reverse("admin:esim_teslimat_change", args=[obj.esim.pk]),
            obj.esim.get_durum_display(),
        )

    @display(description="Bayi", ordering="bayi__username")
    def bayi_gosterimi(self, obj):
        return kullanici_etiketi_html(obj.bayi)

    @display(description="Tutar", ordering="tutar")
    def tutar_gosterimi(self, obj):
        return format_html("<b>{} ₺</b>", obj.tutar)

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        renkler = {
            SiparisDurumu.VERILDI: "#B45309",
            SiparisDurumu.TESLIM: "#0F8A4D",
            SiparisDurumu.IPTAL: "#D42046",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renkler.get(obj.durum, "#6F7B8F"),
            obj.get_durum_display(),
        )

    # -- karar düğmeleri --------------------------------------------------
    #
    # unfold'un `actions_row`'u kullanılmıyor: `get_actions_row` kaydı
    # bilmediği için düğmeler satır başına süzülemiyor ve teslim edilmiş
    # siparişte de "Teslim edildi" duruyordu. Adresler `get_urls` ile
    # tanımlanır, düğme sütunda koşullu çizilir.

    # Düğmelerin ortak görünümü; biri form gönderir, biri sayfa açar.
    DUGME_STILI = (
        "border:1px solid #e3e8f0;border-radius:.375rem;padding:.25rem .6rem;"
        "font-size:.75rem;font-weight:600;white-space:nowrap;text-decoration:none;"
        "background:transparent;cursor:pointer;color:{}"
    )

    @display(description="")
    def karar_dugmeleri(self, obj):
        """Teslim POST'lar, iptal onay ekranı açar.

        **Teslim düğmesi bağlantı değildir.** Kaydı değiştiren bir GET,
        yöneticinin açtığı herhangi bir sayfanın (gömülü bir `<img>`in bile)
        siparişi teslim edilmiş yapmasına izin verirdi; bekleyen iş rozetten
        düşer ve kimse fark etmez. Düğme, listenin kendi formunu (`changelist-form`)
        bu adrese POST'lar — CSRF anahtarı o formdan gelir, günlük iş yine
        tek tık kalır, ikinci bir onay ekranına gerek olmaz.

        İptal para oynattığı için ayrı: bağlantı yalnızca ne olacağını yazan
        onay ekranını açar, iş orada POST ile yapılır.
        """
        parcalar = []

        # eSIM'de teslim otomatik (profil gelince), iptal ise önce sağlayıcıda
        # yapılmalı: düğme teslimat ekranının onayına gider.
        if obj.esim_mi:
            if obj.esim.iptal_edilebilir:
                parcalar.append(
                    format_html(
                        '<a href="{}" style="{}">İptal et</a>',
                        reverse("admin:esim_teslimat_iptal", args=[obj.esim.pk]),
                        format_html(self.DUGME_STILI, "#D42046"),
                    )
                )
            return format_html_join(" ", "{}", ((parca,) for parca in parcalar)) if parcalar else ""

        # Yükleme sağlayıcıda geri alınamaz; iptal yalnızca yönetimin bilinçli
        # kararı (bayiye iade bizden çıkar). Teslim düğmesi yok: yükleme anında teslim.
        if obj.bekliyor and not obj.esim_yukleme_mi:
            parcalar.append(
                format_html(
                    '<button type="submit" form="changelist-form" formmethod="post" '
                    'formaction="{}" style="{}">Teslim edildi</button>',
                    reverse("admin:magaza_siparis_teslim_edildi", args=[obj.pk]),
                    format_html(self.DUGME_STILI, "#0F8A4D"),
                )
            )

        # Ürün geri geldiyse teslim edilmiş sipariş de iptal edilebilir;
        # para o zaman bayinin bakiyesine döner.
        if obj.bekliyor or obj.durum == SiparisDurumu.TESLIM:
            parcalar.append(
                format_html(
                    '<a href="{}" style="{}">İptal et</a>',
                    reverse("admin:magaza_siparis_iptal_et", args=[obj.pk]),
                    format_html(self.DUGME_STILI, "#D42046"),
                )
            )

        if not parcalar:
            return ""
        # `"".join(...)` düz str döndürür ve dıştaki format_html onu kaçışlar.
        return format_html_join(" ", "{}", ((parca,) for parca in parcalar))

    def get_urls(self):
        return [
            path(
                "<int:object_id>/teslim-edildi/",
                self.admin_site.admin_view(self.teslim_edildi),
                name="magaza_siparis_teslim_edildi",
            ),
            path(
                "<int:object_id>/iptal-et/",
                self.admin_site.admin_view(self.iptal_et),
                name="magaza_siparis_iptal_et",
            ),
            *super().get_urls(),
        ]

    def teslim_edildi(self, request, object_id):
        """Siparişi teslim edildi işaretler. Para hareketi yoktur.

        Yalnızca POST: kaydı değiştiren bir GET adresi, yöneticinin açtığı
        başka bir sayfadan tetiklenebilirdi.
        """
        if request.method != "POST":
            return redirect("admin:magaza_siparis_changelist")

        siparis = self.get_object(request, object_id)
        if siparis is None:
            raise Http404("Sipariş bulunamadı.")

        if not siparis.bekliyor:
            self.message_user(request, "Bu sipariş zaten sonuçlanmış.", messages.INFO)
        else:
            siparis.durum = SiparisDurumu.TESLIM
            siparis.save(update_fields=["durum", "guncelleme_tarihi"])
            self.message_user(
                request,
                f"{siparis.referans_no} teslim edildi olarak işaretlendi.",
                messages.SUCCESS,
            )
        return redirect("admin:magaza_siparis_changelist")

    def iptal_et(self, request, object_id):
        """Siparişi iptal eder ve tutarı bayinin bakiyesine geri yazar.

        Düz bağlantı yalnızca ne olacağını yazan onay ekranını açar; para
        POST ile hareket eder. Yöneticinin açtığı bir sayfa ya da bir
        önizleme isteği kimsenin bakiyesini oynatmamalı.
        """
        siparis = self.get_object(request, object_id)
        if siparis is None:
            raise Http404("Sipariş bulunamadı.")

        if siparis.iptal_mi:
            self.message_user(request, "Bu sipariş zaten iptal edilmiş.", messages.INFO)
            return redirect("admin:magaza_siparis_changelist")

        if siparis.esim_mi:
            # Sağlayıcı atlanmaz: iade ancak profil sağlayıcıda iptal edilince.
            return redirect("admin:esim_teslimat_iptal", siparis.esim.pk)

        if request.method == "POST":
            siparis.durum = SiparisDurumu.IPTAL
            siparis.save(update_fields=["durum", "guncelleme_tarihi"])
            siparis_durumunu_uygula(siparis, olusturan=request.user)
            self.message_user(
                request,
                f"{siparis.referans_no} iptal edildi; {siparis.tutar} ₺ bayinin "
                "bakiyesine geri yazıldı. Sebebini “Yönetim Notu”na yazarsanız "
                "bayi de görür.",
                messages.WARNING,
            )
            return redirect("admin:magaza_siparis_changelist")

        return render(
            request,
            "admin/magaza/siparis_iptal.html",
            {
                **self.admin_site.each_context(request),
                "title": "Siparişi iptal et",
                "siparis": siparis,
                "opts": self.model._meta,
            },
        )

    def save_model(self, request, obj, form, change):
        """Durum hangi yoldan değişirse değişsin para tek servisten geçer.

        Durum alanı formda düzenlenebilir; yönetici "İptal edildi" seçip
        kaydedince sipariş iptal **görünüp** para bayide kalmasın diye
        servis burada da çağrılır. Ödeme bildirimindeki kuralın aynısı.
        """
        if change and obj.esim_mi:
            self._esim_kaydet(request, obj, form)
            return

        super().save_model(request, obj, form, change)
        try:
            siparis_durumunu_uygula(obj, olusturan=request.user)
        except SiparisVerilemez as hata:
            # İptalden çıkarılan sipariş yeniden kesiliyor; bakiye yetmezse
            # kayıt iptal olarak kalır ve yönetici sebebini görür.
            obj.durum = SiparisDurumu.IPTAL
            obj.save(update_fields=["durum", "guncelleme_tarihi"])
            self.message_user(
                request,
                f"Sipariş yeniden açılamadı: {hata} Kayıt iptal olarak kaldı.",
                messages.ERROR,
            )
        obj.refresh_from_db()

    def _esim_kaydet(self, request, obj, form):
        """eSIM siparişinde durum formdan değişmez; iptal sağlayıcıdan geçer.

        "İptal edildi" seçilirse sağlayıcıda iptal denenir: kabul ederse para
        bayiye döner, reddederse durum eski hâline alınır ve yönetici sebebini
        görür. Teslim/verildi geçişi elle yapılmaz — profil gelince kendiliğinden
        teslim olur. Diğer alanlar (yönetim notu) serbestçe kaydedilir.
        """
        if "durum" not in form.changed_data:
            super().save_model(request, obj, form, True)
            return

        eski_durum = form.initial.get("durum")
        if obj.durum == SiparisDurumu.IPTAL and obj.esim.iptal_edilebilir:
            obj.durum = eski_durum
            super().save_model(request, obj, form, True)
            try:
                esim_siparisi_iptal_et(obj, olusturan=request.user)
            except SaglayiciHatasi as hata:
                self.message_user(
                    request,
                    f"Sağlayıcı iptali kabul etmedi, sipariş açık kaldı: {hata}",
                    messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"{obj.referans_no} sağlayıcıda iptal edildi; {obj.tutar} ₺ bayiye geri yazıldı.",
                    messages.WARNING,
                )
            obj.refresh_from_db()
            return

        obj.durum = eski_durum
        super().save_model(request, obj, form, True)
        self.message_user(
            request,
            "eSIM siparişinin durumu elle değiştirilmez: teslim profil gelince kendiliğinden "
            "olur, iptal yalnızca hazır (kurulmamış) profilde ve sağlayıcı üzerinden yapılır.",
            messages.ERROR,
        )
