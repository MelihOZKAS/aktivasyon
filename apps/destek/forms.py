"""Destek formları."""

from django import forms

from apps.destek.models import DestekTalebi


class TalepFormu(forms.ModelForm):
    """Yeni talep: konu + ilk mesaj.

    İlgili başvuru kutusuna yalnızca **bu bayinin kendi** başvuruları
    girer; başkasının referansı elle gönderilse de kaydedilmez.
    """

    icerik = forms.CharField(
        label="Mesajın",
        widget=forms.Textarea(attrs={"rows": 5, "class": "girdi"}),
        max_length=4000,
    )

    class Meta:
        model = DestekTalebi
        fields = ("konu", "basvuru")

    def __init__(self, *args, bayi=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.basvurular.models import Basvuru

        self.fields["konu"].widget.attrs.update(
            {"class": "girdi", "placeholder": "Kısaca konu"}
        )
        self.fields["basvuru"].queryset = (
            Basvuru.objects.filter(bayi=bayi)
            .select_related("kategori")
            .order_by("-olusturma_tarihi")[:50]
            if bayi
            else Basvuru.objects.none()
        )
        self.fields["basvuru"].required = False
        self.fields["basvuru"].empty_label = "Bir başvuruyla ilgili değil"
        self.fields["basvuru"].widget.attrs.update({"class": "girdi"})


class YanitFormu(forms.Form):
    """Açık talebe yazılan yanıt."""

    icerik = forms.CharField(
        label="Yanıtın",
        widget=forms.Textarea(attrs={"rows": 3, "class": "girdi"}),
        max_length=4000,
    )
