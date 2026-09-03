"""Kamuya açık formlar."""

import re

from django import forms

from apps.bayi.models import BayiBasvurusu

TELEFON_DESENI = re.compile(r"^0?5\d{9}$")


class BayiBasvuruFormu(forms.ModelForm):
    """Bayi olmak isteyenler için kısa iletişim formu."""

    # Botlar doldurur, insanlar görmez. Doluysa kayıt sessizce atlanır.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    class Meta:
        model = BayiBasvurusu
        fields = ("isim", "soyisim", "irtibat")
        widgets = {
            "isim": forms.TextInput(
                attrs={"class": "girdi", "autocomplete": "given-name"}
            ),
            "soyisim": forms.TextInput(
                attrs={"class": "girdi", "autocomplete": "family-name"}
            ),
            "irtibat": forms.TextInput(
                attrs={
                    "class": "girdi",
                    "type": "tel",
                    "inputmode": "numeric",
                    "autocomplete": "tel",
                    "placeholder": "5XX XXX XX XX",
                }
            ),
        }

    def clean_irtibat(self):
        numara = re.sub(r"\D", "", self.cleaned_data["irtibat"])
        if not TELEFON_DESENI.match(numara):
            raise forms.ValidationError(
                "Telefon numarasını 5 ile başlayacak şekilde, 10 hane girin."
            )
        return numara.lstrip("0")

    @property
    def bot_doldurdu(self):
        return bool(self.cleaned_data.get("website"))
