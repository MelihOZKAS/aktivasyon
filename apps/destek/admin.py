"""Destek taleplerinin yönetim ekranı.

Yanıt yazmak satır içi mesaj kutusundan geçer; kaydedilince
`mesaj_ekle` çağrılır. Mesajı doğrudan formsete bırakmak talebin özet
alanlarını (son mesaj, sıra kimde) güncellemezdi ve talep listede yanlış
tarafta görünürdü — karar hangi yoldan verilirse verilsin tek servisten
geçer kuralının aynısı.
"""

from django import forms
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from apps.destek.models import DestekMesaji, DestekTalebi, TalepDurumu


class DestekMesajiInline(TabularInline):
    """Yazışma geçmişi + yeni yanıt kutusu.

    Var olan mesajlar salt okunur: yazışma düzeltilmez, üstüne yazılır.
    """

    model = DestekMesaji
    extra = 1
    fields = ("tarih", "kim", "icerik")
    readonly_fields = ("tarih", "kim")
    can_delete = False
    verbose_name_plural = "Yazışma"

    @display(description="Gönderen")
    def kim(self, obj):
        if obj.pk is None:
            return "—"
        return "Yönetim" if obj.personelden else obj.talep.bayi.get_username()

    def get_readonly_fields(self, request, obj=None):
        # Yeni satırda mesaj yazılabilsin, eskiler dokunulmaz kalsın.
        return self.readonly_fields

    def has_change_permission(self, request, obj=None):
        return True


@admin.register(DestekTalebi)
class DestekTalebiAdmin(ModelAdmin):
    list_display = (
        "referans_no",
        "konu",
        "acan",
        "durum_rozeti",
        "sira_kimde",
        "son_mesaj_tarihi",
    )
    list_filter = ("durum", "yanit_bekliyor", "olusturma_tarihi")
    search_fields = (
        "referans_no", "konu", "bayi__username", "mesajlar__icerik",
    )
    autocomplete_fields = ("bayi", "basvuru")
    readonly_fields = ("referans_no", "olusturma_tarihi", "son_mesaj_tarihi")
    inlines = [DestekMesajiInline]
    actions = ("kapat", "yeniden_ac")
    fieldsets = (
        (
            "Talep",
            {
                "fields": ("referans_no", "bayi", "konu", "basvuru", "durum",
                           "olusturma_tarihi", "son_mesaj_tarihi"),
                "description": (
                    "Yanıt yazmak için aşağıdaki <b>Yazışma</b> tablosunun boş "
                    "satırına mesajınızı yazıp kaydedin. Yazışma silinmez, "
                    "düzenlenmez."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request).select_related("bayi__bayi_profili", "basvuru")
        )

    def has_add_permission(self, request):
        """Talebi bayi açar; yönetim yanıtlar."""
        return False

    @display(description="Açan", ordering="bayi__username")
    def acan(self, obj):
        profil = getattr(obj.bayi, "bayi_profili", None)
        unvan = profil.unvan if profil and profil.unvan else ""
        numara = obj.bayi.get_username()
        if not unvan:
            return numara
        return format_html(
            '<span style="font-weight:600">{}</span><br>'
            '<span style="color:#6F7B8F;font-size:.75rem">{}</span>',
            unvan,
            numara,
        )

    @display(description="Durum", ordering="durum")
    def durum_rozeti(self, obj):
        renk = "#0F8A4D" if obj.acik_mi else "#6F7B8F"
        return format_html(
            '<span style="background:{};color:#fff;padding:.15rem .6rem;'
            'border-radius:999px;font-size:.75rem;font-weight:600">{}</span>',
            renk,
            obj.get_durum_display(),
        )

    @display(description="Sıra")
    def sira_kimde(self, obj):
        if not obj.acik_mi:
            return "—"
        if obj.yanit_bekliyor:
            return format_html(
                '<b style="color:#B45309">Yönetimde</b>'
            )
        return format_html('<span style="color:#6F7B8F">Bayide</span>')

    def save_formset(self, request, form, formset, change):
        """Yeni mesajlar servisten geçer; eskiler dokunulmaz.

        Formset doğrudan kaydedilseydi talebin "son mesaj" ve "sıra kimde"
        alanları güncellenmez, talep yanıtlandığı hâlde rozette beklemeye
        devam ederdi.
        """
        from apps.destek.services import mesaj_ekle

        if formset.model is not DestekMesaji:
            return super().save_formset(request, form, formset, change)

        for nesne in formset.save(commit=False):
            if nesne.pk:
                continue
            mesaj_ekle(form.instance, request.user, nesne.icerik, personelden=True)
        formset.save_m2m()

    @admin.action(description="Seçili talepleri kapat")
    def kapat(self, request, secilenler):
        adet = secilenler.update(durum=TalepDurumu.KAPALI)
        self.message_user(request, f"{adet} talep kapatıldı.")

    @admin.action(description="Seçili talepleri yeniden aç")
    def yeniden_ac(self, request, secilenler):
        adet = secilenler.update(durum=TalepDurumu.ACIK)
        self.message_user(request, f"{adet} talep yeniden açıldı.")
