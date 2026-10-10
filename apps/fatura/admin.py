from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin
from unfold.decorators import display

from apps.bayi.etiket import kullanici_etiketi_html
from apps.fatura.models import GrupFiyati, Kategori, Kurum, Odeme, OdemeDurumu, Robot, Sorgu, SorguDurumu
from apps.fatura.services import KararVerilemez, iptal_et, odendi_isaretle
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


def _ondalik(metin):
    """Kutudan gelen "5,50" / "1.250,00" / "5.50" → Decimal; boşsa None, bozuksa hata."""
    metin = (metin or "").strip().replace(" ", "")
    if not metin:
        return None
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    deger = Decimal(metin)  # bozuksa InvalidOperation
    if deger < 0:
        raise InvalidOperation
    return deger.quantize(Decimal("0.01"))


def _soluk(metin):
    return format_html('<span style="color:{}">{}</span>', GRI, metin)


# -- Katalog -------------------------------------------------------------


@admin.register(Kategori)
class KategoriAdmin(ModelAdmin):
    list_display = ("ad", "kurum_sayisi", "sira", "aktif")
    list_editable = ("sira", "aktif")
    search_fields = ("ad",)
    fields = ("ad", "slug", "sira", "aktif")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_kurum=Count("kurumlar"))

    @display(description="Kurum", ordering="_kurum")
    def kurum_sayisi(self, obj):
        adres = reverse("admin:fatura_kurum_changelist") + f"?kategori__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', adres, obj._kurum)


@admin.register(Kurum)
class KurumAdmin(ModelAdmin):
    list_display = ("ad", "kod", "kategori", "sorgulu", "kural", "fiyat_ozeti", "sira", "aktif")
    list_editable = ("kategori", "sorgulu", "sira", "aktif")
    list_filter = ("aktif", "sorgulu", "kategori")
    search_fields = ("ad", "kod")
    list_per_page = 50
    fieldsets = (
        (None, {"fields": ("ad", "kod", "kategori", "operator", "sira", "aktif", "sorgulu")}),
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
        (
            "Fiyat",
            {
                "fields": ("fiyat_baglantisi", "alis_fiyati"),
                "description": (
                    "Bayi ve müşteri fiyatları <b>Fatura → Fiyatlar</b> sayfasından girilir; "
                    "kontör fiyat gruplarına göre (Perakende, Toptan…) tek sayfada. "
                    "Burada yalnızca sorgusuz kalemin alışımız durur (kâr hesabı için)."
                ),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        # Kod robotun kimliğidir: değişirse robot bu kurumu bulamaz.
        return ("kod", "fiyat_baglantisi") if obj is not None else ("fiyat_baglantisi",)

    @display(description="Numara")
    def kural(self, obj):
        hane = f"{obj.max_hane} hane" if obj.min_hane == obj.max_hane else f"{obj.min_hane}–{obj.max_hane} hane"
        return f"{obj.alan_etiketi} · {hane}" + (" · rakam" if obj.sadece_rakam else "")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("kategori").annotate(_grup=Count("grup_fiyatlari"))

    @display(description="Fiyat")
    def fiyat_ozeti(self, obj):
        grup = f" · {obj._grup} grupta ayrı" if obj._grup else ""
        if obj.sorgulu:
            if not obj.hizmet_bedeli and not obj.tavsiye_ek and not obj._grup:
                return _soluk("fatura tutarı aynen")
            return f"genel +{obj.hizmet_bedeli} hizmet · müşteriden +{obj.tavsiye_ek}{grup}"
        if not obj.bayi_fiyati and not obj._grup:
            return format_html('<b style="color:#D42046">fiyat yok — görünmez</b>')
        tavsiye = f" · müşteri {obj.tavsiye_fiyati}" if obj.tavsiye_fiyati else ""
        return f"genel {obj.bayi_fiyati or '—'}{tavsiye}{grup}"

    @display(description="Fiyatlar")
    def fiyat_baglantisi(self, obj):
        return _dugme(reverse("admin:fatura_kurum_fiyatlar"), "Fiyatlar sayfası")

    def get_urls(self):
        return [
            path("fiyatlar/", self.admin_site.admin_view(self.fiyatlar), name="fatura_kurum_fiyatlar"),
            *super().get_urls(),
        ]

    def fiyatlar(self, request):
        """Bütün fatura fiyatları tek sayfada: satırda kurum, sütunda grup.

        Kontördeki grup fiyatının aynısı: bayi kontörde hangi gruptaysa
        (`Cuzdan.kontor_grubu`, boşsa varsayılan) o sütunun rakamını öder.
        Tek rakam, anlamı kurumun türüne göre: sorgulu kurumda fatura başına
        hizmet bedeli, sorgusuz kalemde net bayi fiyatı. Grup kutusu boşsa
        "Genel" sütunu geçerli. Müşteri fiyatı gruba göre değişmez.
        Aynı rakam başka yerden girilmez (kurum formunda fiyat yok).
        """
        if not self.has_change_permission(request):
            raise PermissionDenied
        from apps.kontor.models import FiyatGrubu

        gruplar = list(FiyatGrubu.objects.order_by("-varsayilan", "ad"))
        pasif = request.GET.get("pasif") == "1"
        kurumlar = Kurum.objects.select_related("kategori").order_by("kategori__sira", "kategori__ad", "sira", "ad")
        if not pasif:
            kurumlar = kurumlar.filter(aktif=True)
        kurumlar = list(kurumlar)
        mevcut = {(g.kurum_id, g.grup_id): g for g in GrupFiyati.objects.filter(kurum__in=kurumlar)}

        hatalar = {}
        if request.method == "POST":
            yazilacak = []
            for k in kurumlar:
                try:
                    musteri = _ondalik(request.POST.get(f"m_{k.pk}"))
                    genel = _ondalik(request.POST.get(f"g_{k.pk}_genel"))
                    grupta = {g.pk: _ondalik(request.POST.get(f"g_{k.pk}_{g.pk}")) for g in gruplar}
                except (InvalidOperation, ValueError):
                    hatalar[k.pk] = "Rakam anlaşılamadı."
                    continue
                if not k.sorgulu and any(v == 0 for v in (genel, *grupta.values())):
                    hatalar[k.pk] = "Sorgusuz kalemde fiyat 0 olamaz; satılmayacaksa kutuyu boş bırak."
                    continue
                yazilacak.append((k, musteri, genel, grupta))
            if not hatalar:
                degisen = 0
                with transaction.atomic():
                    for k, musteri, genel, grupta in yazilacak:
                        if k.sorgulu:
                            yeni = {"tavsiye_ek": musteri or Decimal("0"), "hizmet_bedeli": genel or Decimal("0")}
                        else:
                            yeni = {"tavsiye_fiyati": musteri, "bayi_fiyati": genel}
                        alanlar = [a for a, v in yeni.items() if getattr(k, a) != v]
                        if alanlar:
                            for a in alanlar:
                                setattr(k, a, yeni[a])
                            k.save(update_fields=[*alanlar, "guncelleme_tarihi"])
                            degisen += 1
                        for grup_id, tutar in grupta.items():
                            kayit = mevcut.get((k.pk, grup_id))
                            if tutar is None:
                                if kayit:
                                    kayit.delete()
                                    degisen += 1
                            elif kayit is None:
                                GrupFiyati.objects.create(kurum=k, grup_id=grup_id, tutar=tutar)
                                degisen += 1
                            elif kayit.tutar != tutar:
                                kayit.tutar = tutar
                                kayit.save(update_fields=["tutar"])
                                degisen += 1
                self.message_user(request, f"{degisen} fiyat kaydedildi.", messages.SUCCESS)
                return redirect(request.get_full_path())
            self.message_user(request, "Bazı satırlar kaydedilmedi; kırmızı yazan satırları düzeltin.", messages.ERROR)

        def yaz(deger):
            return "" if deger is None else str(deger).replace(".", ",")

        satirlar = []
        for k in kurumlar:
            musteri = k.tavsiye_ek if k.sorgulu else k.tavsiye_fiyati
            genel = k.hizmet_bedeli if k.sorgulu else k.bayi_fiyati
            hucreler = []
            for g in gruplar:
                kayit = mevcut.get((k.pk, g.pk))
                gecerli = kayit.tutar if kayit else genel
                # Bayi müşteriye söylenen rakamın üstünde ödüyorsa zarar eder
                # (sorgulu: hizmet > müşteriden ek; sorgusuz: fiyat > müşteri fiyatı).
                zarar = bool(musteri) and gecerli is not None and gecerli > musteri
                deger = request.POST.get(f"g_{k.pk}_{g.pk}", "") if request.method == "POST" else yaz(kayit.tutar if kayit else None)
                hucreler.append({"ad": f"g_{k.pk}_{g.pk}", "deger": deger, "zarar": zarar})
            satirlar.append({
                "kurum": k,
                "musteri_ad": f"m_{k.pk}",
                "musteri": request.POST.get(f"m_{k.pk}", "") if request.method == "POST" else yaz(musteri if (musteri or not k.sorgulu) else None),
                "genel_ad": f"g_{k.pk}_genel",
                "genel": request.POST.get(f"g_{k.pk}_genel", "") if request.method == "POST" else yaz(genel if (genel or not k.sorgulu) else None),
                "genel_yer": "0" if k.sorgulu else "satılmaz",
                "hucreler": hucreler,
                "hata": hatalar.get(k.pk, ""),
            })
        return render(
            request,
            "admin/fatura/fiyatlar.html",
            {
                **self.admin_site.each_context(request),
                "title": "Fatura fiyatları",
                "opts": self.model._meta,
                "gruplar": gruplar,
                "satirlar": satirlar,
                "pasif": pasif,
            },
        )


# -- Robot ---------------------------------------------------------------


@admin.register(Robot)
class RobotAdmin(ModelAdmin):
    list_display = (
        "ad", "durum_gosterimi", "oturum_gosterimi", "mesai_gosterimi", "son_nabiz", "aktif",
        "anahtar_durumu", "anahtar_dugmesi",
    )
    list_editable = ("aktif",)
    fields = ("ad", "aktif", "son_nabiz")
    readonly_fields = ("son_nabiz",)

    @display(description="Durum")
    def durum_gosterimi(self, obj):
        if not obj.cevrimici:
            return _rozet("Çevrimdışı", GRI)
        return _rozet("Meşgul", "#B45309") if obj.mesgul else _rozet("Açık", "#0F8A4D")

    @display(description="Oturum")
    def oturum_gosterimi(self, obj):
        if obj.oturum_canli:
            return _soluk("canlı")
        return format_html('<b style="color:#D42046">düştü — laptopta giris.bat</b>')

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


@admin.register(Odeme)
class OdemeAdmin(ModelAdmin):
    """Bayinin ödediği faturalar. Günlük iş: sağlayıcıda öde → "Ödendi".

    Durum alanı formda salt okunurdur; karar yalnızca satırdaki düğmeden
    (onay ekranı, POST) verilir ve `services` üzerinden geçer. İptal para
    oynattığı için doğrudan çalışmaz, ne olacağını yazan ekranı açar.
    """

    list_display = (
        "olusturma_tarihi", "referans", "bayi_gosterimi", "kurum_adi", "numara",
        "fatura_ozeti", "tutar_gosterimi", "durum_gosterimi", "karar_dugmesi",
    )
    list_filter = ("durum", "kurum", ("olusturma_tarihi", GunAraligiFiltresi))
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
        return super().get_queryset(request).select_related("siparis", "bayi", "bayi__bayi_profili")

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
            '<b>{}</b><br><span style="color:{};font-size:.7rem">sağlayıcıya {}</span>',
            obj.siparis.tutar, GRI, obj.saglayici_tutari,
        )

    @display(description="Durum", ordering="durum")
    def durum_gosterimi(self, obj):
        rozet = _rozet(obj.get_durum_display(), ODEME_RENKLERI.get(obj.durum, GRI))
        if obj.sonuc_notu:
            return format_html('{}<br><span style="color:{};font-size:.7rem">{}</span>', rozet, GRI, obj.sonuc_notu)
        return rozet

    @display(description="")
    def karar_dugmesi(self, obj):
        if not obj.bekliyor:
            return ""
        return _dugme(reverse("admin:fatura_odeme_karar", args=[obj.pk]), "Karar")

    def get_urls(self):
        return [
            path(
                "<int:object_id>/karar/",
                self.admin_site.admin_view(self.karar),
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
            return redirect("admin:fatura_odeme_changelist")
        return render(
            request,
            "admin/fatura/odeme_karar.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Fatura ödemesi · {odeme.referans_no}",
                "opts": self.model._meta,
                "odeme": odeme,
            },
        )
