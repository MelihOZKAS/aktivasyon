"""Kategoriye göre kendini kuran başvuru formu.

Çekirdek alanlar ModelForm'dan gelir; kategoriye özel alanlar
`KategoriAlani` tanımlarına bakılarak çalışma anında eklenir.
"""

import re

from django import forms
from django.core.exceptions import ValidationError

from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu
from apps.basvurular.validators import belge_dogrula
from apps.katalog.models import AlanTipi, Kampanya, KategoriAlani, MusteriTipi, Tarife

GIRDI_SINIFI = "girdi"

ALAN_SINIFLARI = {
    AlanTipi.METIN: forms.CharField,
    AlanTipi.UZUN_METIN: forms.CharField,
    AlanTipi.SAYI: forms.IntegerField,
    AlanTipi.TUTAR: forms.DecimalField,
    AlanTipi.TARIH: forms.DateField,
    AlanTipi.TELEFON: forms.CharField,
    AlanTipi.EPOSTA: forms.EmailField,
    AlanTipi.SECIM: forms.ChoiceField,
    AlanTipi.ONAY: forms.BooleanField,
    AlanTipi.DOSYA: forms.FileField,
    AlanTipi.RESIM: forms.ImageField,
}


def _widget_uret(tanim):
    """Alan tipine uygun HTML girdisini üretir."""
    ortak = {"class": GIRDI_SINIFI}
    if tanim.placeholder:
        ortak["placeholder"] = tanim.placeholder

    if tanim.tip == AlanTipi.UZUN_METIN:
        return forms.Textarea(attrs={**ortak, "rows": 3})
    if tanim.tip == AlanTipi.TARIH:
        return forms.DateInput(attrs={**ortak, "type": "date"})
    if tanim.tip == AlanTipi.TELEFON:
        return forms.TextInput(attrs={**ortak, "type": "tel", "inputmode": "numeric"})
    if tanim.tip == AlanTipi.EPOSTA:
        return forms.EmailInput(attrs={**ortak, "type": "email"})
    if tanim.tip in {AlanTipi.SAYI, AlanTipi.TUTAR}:
        return forms.NumberInput(attrs={**ortak, "inputmode": "decimal"})
    if tanim.tip == AlanTipi.ONAY:
        return forms.CheckboxInput(attrs={"class": "h-5 w-5 rounded"})
    if tanim.tip == AlanTipi.SECIM:
        return forms.Select(attrs=ortak)
    if tanim.tip == AlanTipi.RESIM:
        # Tezgâh başında kimlik fotoğrafı doğrudan telefon kamerasıyla çekilsin.
        return forms.ClearableFileInput(
            attrs={**ortak, "accept": "image/*", "capture": "environment"}
        )
    if tanim.tip == AlanTipi.DOSYA:
        return forms.ClearableFileInput(attrs={**ortak, "accept": "image/*,application/pdf"})
    return forms.TextInput(attrs=ortak)


class BasvuruFormu(forms.ModelForm):
    class Meta:
        model = Basvuru
        fields = (
            "operator",
            "tarife",
            "kampanya",
            "musteri_tipi",
            "kimlik_tipi",
            "kimlik_no",
            "isim",
            "soyisim",
            "irtibat",
            "numara",
            "adres",
            "bayi_aciklamasi",
        )
        widgets = {
            "adres": forms.Textarea(attrs={"class": GIRDI_SINIFI, "rows": 2}),
            "bayi_aciklamasi": forms.Textarea(attrs={"class": GIRDI_SINIFI, "rows": 2}),
        }

    def __init__(self, *args, kategori, **kwargs):
        super().__init__(*args, **kwargs)
        self.kategori = kategori
        self.alan_tanimlari = list(
            kategori.alanlar.filter(aktif=True).order_by("sira", "id")
        )

        for ad, alan in self.fields.items():
            if not isinstance(alan.widget, (forms.Textarea, forms.CheckboxInput)):
                alan.widget.attrs.setdefault("class", GIRDI_SINIFI)

        self._kapsami_daralt()
        self._dinamik_alanlari_ekle()

    def _kapsami_daralt(self):
        """Seçim listelerini yalnızca bu kategoriye ait kayıtlarla sınırlar."""
        self.fields["operator"].queryset = self.kategori.gecerli_operatorler()
        self.fields["tarife"].queryset = Tarife.objects.filter(
            kategori=self.kategori, aktif=True
        ).select_related("operator")
        self.fields["kampanya"].queryset = Kampanya.objects.filter(
            tarife__kategori=self.kategori, aktif=True
        ).select_related("tarife")

        self.fields["tarife"].required = self.kategori.tarife_zorunlu
        self.fields["kampanya"].required = False
        self.fields["operator"].required = True

        if self.kategori.musteri_tipi != MusteriTipi.HEPSI:
            self.fields["musteri_tipi"].initial = self.kategori.musteri_tipi
            self.fields["musteri_tipi"].widget = forms.HiddenInput()

    def _dinamik_alanlari_ekle(self):
        """KategoriAlani kayıtlarını gerçek form alanlarına dönüştürür."""
        for tanim in self.alan_tanimlari:
            alan_sinifi = ALAN_SINIFLARI.get(tanim.tip, forms.CharField)
            argumanlar = {
                "label": tanim.etiket,
                "required": tanim.zorunlu,
                "help_text": tanim.yardim_metni,
                "widget": _widget_uret(tanim),
            }

            if tanim.tip == AlanTipi.SECIM:
                secenekler = [("", "Seçiniz")] + [
                    (s, s) for s in tanim.secenek_listesi
                ]
                argumanlar["choices"] = secenekler
            elif tanim.tip in {AlanTipi.METIN, AlanTipi.UZUN_METIN, AlanTipi.TELEFON}:
                if tanim.min_uzunluk:
                    argumanlar["min_length"] = tanim.min_uzunluk
                if tanim.max_uzunluk:
                    argumanlar["max_length"] = tanim.max_uzunluk

            if tanim.dosya_mi:
                # Uzantı ve içerik denetimi; RESIM alanlarında Pillow'a ek güvence.
                argumanlar["validators"] = [belge_dogrula]

            self.fields[f"ek__{tanim.kod}"] = alan_sinifi(**argumanlar)

    def clean(self):
        temiz = super().clean()

        for tanim in self.alan_tanimlari:
            anahtar = f"ek__{tanim.kod}"
            deger = temiz.get(anahtar)

            # Koşullu alan: koşul sağlanmıyorsa zorunluluğu ve değeri düşür.
            if tanim.kosul_alani_id:
                kosul_anahtari = f"ek__{tanim.kosul_alani.kod}"
                kosul_degeri = temiz.get(kosul_anahtari)
                if str(kosul_degeri or "") != tanim.kosul_degeri:
                    temiz[anahtar] = None
                    self.errors.pop(anahtar, None)
                    continue

            if deger in (None, "", []):
                continue

            if tanim.dogrulama_deseni and isinstance(deger, str):
                if not re.fullmatch(tanim.dogrulama_deseni, deger):
                    self.add_error(anahtar, f"{tanim.etiket} beklenen biçimde değil.")

        tarife = temiz.get("tarife")
        operator = temiz.get("operator")
        if tarife and operator and tarife.operator_id != operator.pk:
            self.add_error("tarife", "Seçilen tarife bu operatöre ait değil.")

        kampanya = temiz.get("kampanya")
        if kampanya:
            if tarife and kampanya.tarife_id != tarife.pk:
                self.add_error("kampanya", "Seçilen kampanya bu tarifeye ait değil.")
            elif not kampanya.su_an_gecerli:
                self.add_error("kampanya", "Bu kampanya şu an geçerli değil.")

        return temiz

    @property
    def gruplu_alanlar(self):
        """Dinamik alanları `grup` başlığına göre öbekler; şablon böyle çizer."""
        obekler = {}
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi:
                continue
            obekler.setdefault(tanim.grup or "", []).append(self[f"ek__{tanim.kod}"])
        return obekler.items()

    @property
    def belge_alanlari(self):
        return [
            (tanim, self[f"ek__{tanim.kod}"])
            for tanim in self.alan_tanimlari
            if tanim.dosya_mi
        ]

    def kaydet(self, bayi):
        """Başvuruyu, ek bilgileri ve yüklenen belgeleri birlikte kaydeder."""
        basvuru = super().save(commit=False)
        basvuru.bayi = bayi
        basvuru.kategori = self.kategori
        basvuru.durum = BasvuruDurumu.objects.filter(baslangic_durumu=True, aktif=True).first()
        if basvuru.durum is None:
            raise ValidationError(
                "Başlangıç durumu tanımlanmamış. Yönetim panelinden bir durumu "
                "“Başlangıç Durumu” olarak işaretleyin."
            )

        ek_bilgiler = {}
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi:
                continue
            deger = self.cleaned_data.get(f"ek__{tanim.kod}")
            if deger in (None, ""):
                continue
            ek_bilgiler[tanim.kod] = str(deger)
        basvuru.ek_bilgiler = ek_bilgiler
        basvuru.full_clean(exclude=["referans_no"])
        basvuru.save()

        for tanim in self.alan_tanimlari:
            if not tanim.dosya_mi:
                continue
            dosya = self.cleaned_data.get(f"ek__{tanim.kod}")
            if dosya:
                BasvuruBelgesi.objects.update_or_create(
                    basvuru=basvuru,
                    alan_kodu=tanim.kod,
                    defaults={"dosya": dosya, "etiket": tanim.etiket},
                )

        return basvuru
