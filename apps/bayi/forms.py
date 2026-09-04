"""Kamuya açık formlar."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.bayi.models import BayiBasvurusu, BayiBasvuruDurumu
from apps.bayi.telefon import gecerli_mi, normalize

# Bekleyen bir başvuru varken ikincisi açılmaz; aynı kişi iki kez doldurunca
# operasyon iki kayıt görüyordu.
ACIK_DURUMLAR = (BayiBasvuruDurumu.YENI, BayiBasvuruDurumu.GORUSULDU)


class BayiBasvuruFormu(forms.ModelForm):
    """Bayi olmak isteyenler için kısa başvuru formu.

    Başvuran parolasını burada seçer; hesabı yönetim açtığında aynı parolayla
    girer. Parola yalnızca özet olarak saklanır (`parola_ozeti`), düz metin
    hiçbir yere yazılmaz — bildirime de girmez.
    """

    parola = forms.CharField(
        label="Parola",
        widget=forms.PasswordInput(
            attrs={"class": "girdi", "autocomplete": "new-password"}
        ),
        help_text="Hesabınız açıldığında bu parolayla gireceksiniz.",
    )
    parola_tekrar = forms.CharField(
        label="Parola (tekrar)",
        widget=forms.PasswordInput(
            attrs={"class": "girdi", "autocomplete": "new-password"}
        ),
    )

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
        # Numara aynı zamanda kullanıcı adı olacak: boşluk, ülke kodu ve
        # baştaki sıfır atılıp tek biçime indirilir.
        numara = normalize(self.cleaned_data["irtibat"])
        if not gecerli_mi(numara):
            raise forms.ValidationError(
                "Telefon numarasını 5 ile başlayacak şekilde, 10 hane girin."
            )

        # Numara aynı zamanda kullanıcı adı olacak. Çakışmayı burada söylemek,
        # kullanılamayacak bir parola seçtirip sonra telefonla açıklamaktan iyi.
        if User.objects.filter(username=numara).exists():
            raise forms.ValidationError(
                "Bu numarayla açılmış bir hesap var. Giriş yapın ya da bizi arayın."
            )
        if BayiBasvurusu.objects.filter(
            irtibat=numara, durum__in=ACIK_DURUMLAR
        ).exists():
            raise forms.ValidationError(
                "Bu numarayla bekleyen bir başvurunuz var. Temsilcimiz sizi arayacak."
            )
        return numara

    def clean(self):
        veriler = super().clean()
        parola = veriler.get("parola")
        tekrar = veriler.get("parola_tekrar")

        if parola and tekrar and parola != tekrar:
            self.add_error("parola_tekrar", "Parolalar aynı değil.")

        if parola:
            try:
                validate_password(parola)
            except ValidationError as hata:
                self.add_error("parola", hata)
        return veriler

    def save(self, commit=True):
        basvuru = super().save(commit=False)
        # Düz metin parola kaydedilmez; buradan sonra yalnızca özeti taşınır.
        basvuru.parola_ozeti = make_password(self.cleaned_data["parola"])
        if commit:
            basvuru.save()
        return basvuru

    @property
    def bot_doldurdu(self):
        return bool(self.cleaned_data.get("website"))


class GirisFormu(AuthenticationForm):
    """Giriş formu: telefonla girenler numarayı nasıl yazarsa yazsın kabul eder.

    Bayinin kullanıcı adı telefon numarası. Tezgâh başında telefonunu
    "0532 123 45 67" diye yazması çok olası; kullanıcı adı `5321234567`
    olduğu için giriş reddedilirdi. Numara burada da tek biçime indirilir.
    Harf içeren kullanıcı adlarına dokunulmaz.
    """

    def clean_username(self):
        return normalize(self.cleaned_data["username"])
