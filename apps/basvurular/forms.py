"""Kategoriye göre kendini kuran başvuru formu.

Formda hangi alanların soruluacağına, ne yazacağına, zorunlu olup olmadığına
ve hangi tipte (metin, sayı, tarih, dosya…) olacağına tamamen yönetim
panelindeki `KategoriAlani` kayıtları karar verir. Kodda sabit alan listesi
yoktur.

Alanın `cekirdek_alan` değeri doluysa girilen değer başvurunun kendi
kolonuna yazılır (aranabilir olur); boşsa `ek_bilgiler` içinde saklanır.
"""

import re

from django import forms
from django.core.exceptions import ValidationError

from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu, KimlikTipi
from apps.basvurular.validators import belge_dogrula
from apps.katalog.models import AlanTipi, Kampanya, MusteriTipi, Tarife

GIRDI_SINIFI = "girdi"
ALAN_ONEKI = "alan__"

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


class BasvuruFormu(forms.Form):
    """Hat seçimi sabit, geri kalan her şey kategori tanımından gelir."""

    operator = forms.ModelChoiceField(label="Operatör", queryset=None)
    tarife = forms.ModelChoiceField(label="Tarife", queryset=None, required=False)
    kampanya = forms.ModelChoiceField(label="Kampanya", queryset=None, required=False)
    musteri_tipi = forms.ChoiceField(label="Müşteri tipi", choices=MusteriTipi.choices)
    bayi_aciklamasi = forms.CharField(
        label="Operasyona iletmek istediğin bir şey var mı?",
        required=False,
        widget=forms.Textarea(attrs={"class": GIRDI_SINIFI, "rows": 2}),
    )

    def __init__(self, *args, kategori, bayi=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.kategori = kategori
        self.bayi = bayi
        self.alan_tanimlari = list(
            kategori.alanlar.filter(aktif=True).order_by("sira", "id")
        )

        self._kapsami_daralt()
        self._tanimli_alanlari_ekle()

    # -- kurulum ----------------------------------------------------------

    def _kapsami_daralt(self):
        self.fields["operator"].queryset = self.kategori.gecerli_operatorler()
        self.fields["tarife"].queryset = Tarife.objects.filter(
            kategori=self.kategori, aktif=True
        ).select_related("operator")
        self.fields["kampanya"].queryset = Kampanya.objects.filter(
            tarife__kategori=self.kategori, aktif=True
        ).select_related("tarife")
        self.fields["tarife"].required = self.kategori.tarife_zorunlu

        for ad in ("operator", "tarife", "kampanya", "musteri_tipi"):
            self.fields[ad].widget.attrs.setdefault("class", GIRDI_SINIFI)

        if self.kategori.musteri_tipi != MusteriTipi.HEPSI:
            self.fields["musteri_tipi"].initial = self.kategori.musteri_tipi
            self.fields["musteri_tipi"].widget = forms.HiddenInput()

    def _tanimli_alanlari_ekle(self):
        """KategoriAlani kayıtlarını gerçek form alanlarına dönüştürür."""
        for tanim in self.alan_tanimlari:
            alan_sinifi = ALAN_SINIFLARI.get(tanim.tip, forms.CharField)
            argumanlar = {
                "label": tanim.etiket,
                "required": tanim.zorunlu,
                "help_text": tanim.yardim_metni,
                "widget": _widget_uret(tanim),
            }

            if tanim.cekirdek_alan == "kimlik_tipi":
                # Kimlik tipi başvurunun kendi seçeneklerini kullanır.
                alan_sinifi = forms.ChoiceField
                argumanlar["choices"] = KimlikTipi.choices
                argumanlar["widget"] = forms.Select(attrs={"class": GIRDI_SINIFI})
            elif tanim.tip == AlanTipi.SECIM:
                argumanlar["choices"] = [("", "Seçiniz")] + [
                    (s, s) for s in tanim.secenek_listesi
                ]
            elif tanim.tip in {AlanTipi.METIN, AlanTipi.UZUN_METIN, AlanTipi.TELEFON}:
                if tanim.min_uzunluk:
                    argumanlar["min_length"] = tanim.min_uzunluk
                if tanim.max_uzunluk:
                    argumanlar["max_length"] = tanim.max_uzunluk

            if tanim.tip == AlanTipi.SIM_KART:
                # Bayi yalnızca kendisine atanmış, stoktaki SIM'lerle işlem yapar.
                alan_sinifi = forms.CharField
                argumanlar["widget"] = forms.TextInput(
                    attrs={
                        "class": GIRDI_SINIFI,
                        "list": f"sim-{tanim.kod}",
                        "inputmode": "numeric",
                        "autocomplete": "off",
                        "placeholder": "SIM / IMEI",
                    }
                )
                argumanlar["help_text"] = (
                    tanim.yardim_metni or "Yalnızca size zimmetli SIM kartları girebilirsiniz."
                )

            if tanim.dosya_mi:
                argumanlar["validators"] = [belge_dogrula]

            self.fields[ALAN_ONEKI + tanim.kod] = alan_sinifi(**argumanlar)

    # -- doğrulama --------------------------------------------------------

    def clean(self):
        temiz = super().clean()

        for tanim in self.alan_tanimlari:
            anahtar = ALAN_ONEKI + tanim.kod

            # Koşullu alan: koşul sağlanmıyorsa zorunluluğu ve değeri düşür.
            if tanim.kosul_alani_id:
                kosul_degeri = temiz.get(ALAN_ONEKI + tanim.kosul_alani.kod)
                if str(kosul_degeri or "") != tanim.kosul_degeri:
                    temiz[anahtar] = None
                    self.errors.pop(anahtar, None)
                    continue

            deger = temiz.get(anahtar)
            if deger in (None, "", []):
                continue

            if tanim.tip == AlanTipi.SIM_KART:
                self._sim_dogrula(tanim, anahtar, str(deger).strip())
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

    def _sim_dogrula(self, tanim, anahtar, imei):
        """Girilen IMEI bayinin stoğunda mı?"""
        from apps.bayi.models import SimKart, SimKartDurumu

        if self.bayi is None:
            return

        kart = SimKart.objects.filter(imei=imei).first()
        if kart is None:
            self.add_error(anahtar, "Bu SIM kart sistemde kayıtlı değil.")
        elif kart.bayi_id != self.bayi.id:
            # Başka bayinin kartını ele vermemek için ayrıntı verilmez.
            self.add_error(anahtar, "Bu SIM kart size zimmetli değil.")
        elif kart.durum != SimKartDurumu.ATANDI:
            self.add_error(
                anahtar, f"Bu SIM kart kullanılamaz: {kart.get_durum_display()}."
            )
        else:
            self.cleaned_data[f"_sim_{tanim.kod}"] = kart

    # -- şablon yardımcıları ----------------------------------------------

    @property
    def sim_secenekleri(self):
        """Şablonda datalist doldurmak için bayinin stoktaki kartları."""
        from apps.bayi.models import SimKart

        if self.bayi is None:
            return {}
        kodlar = [t.kod for t in self.alan_tanimlari if t.tip == AlanTipi.SIM_KART]
        if not kodlar:
            return {}
        kartlar = list(
            SimKart.objects.bayinin_stogu(self.bayi)
            .select_related("operator")
            .order_by("imei")[:500]
        )
        return {kod: kartlar for kod in kodlar}

    @property
    def gruplu_alanlar(self):
        """Dosya olmayan alanları `grup` başlığına göre öbekler."""
        obekler = {}
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi:
                continue
            obekler.setdefault(tanim.grup or "", []).append(self[ALAN_ONEKI + tanim.kod])
        return obekler.items()

    @property
    def belge_alanlari(self):
        return [
            (tanim, self[ALAN_ONEKI + tanim.kod])
            for tanim in self.alan_tanimlari
            if tanim.dosya_mi
        ]

    # -- kaydetme ---------------------------------------------------------

    def kaydet(self, bayi):
        """Başvuruyu, ek bilgileri ve yüklenen belgeleri birlikte kaydeder."""
        durum = BasvuruDurumu.objects.filter(baslangic_durumu=True, aktif=True).first()
        if durum is None:
            raise ValidationError(
                "Başlangıç durumu tanımlanmamış. Yönetim panelinden bir durumu "
                "“Başlangıç Durumu” olarak işaretleyin."
            )

        basvuru = Basvuru(
            bayi=bayi,
            kategori=self.kategori,
            durum=durum,
            operator=self.cleaned_data["operator"],
            tarife=self.cleaned_data.get("tarife"),
            kampanya=self.cleaned_data.get("kampanya"),
            musteri_tipi=self.cleaned_data.get("musteri_tipi") or self.kategori.musteri_tipi,
            bayi_aciklamasi=self.cleaned_data.get("bayi_aciklamasi", ""),
        )

        ek_bilgiler = {}
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi:
                continue
            deger = self.cleaned_data.get(ALAN_ONEKI + tanim.kod)
            if deger in (None, ""):
                continue
            if tanim.cekirdek_alan:
                # Kendi kolonuna yaz: aranabilir ve indeksli kalsın.
                setattr(basvuru, tanim.cekirdek_alan, str(deger))
            else:
                ek_bilgiler[tanim.kod] = str(deger)

        basvuru.ek_bilgiler = ek_bilgiler
        basvuru.full_clean(exclude=["referans_no"])
        basvuru.save()

        for tanim in self.alan_tanimlari:
            if not tanim.dosya_mi:
                continue
            dosya = self.cleaned_data.get(ALAN_ONEKI + tanim.kod)
            if dosya:
                BasvuruBelgesi.objects.update_or_create(
                    basvuru=basvuru,
                    alan_kodu=tanim.kod,
                    defaults={"dosya": dosya, "etiket": tanim.etiket},
                )

        self._simleri_zimmetle(basvuru)
        return basvuru

    def _simleri_zimmetle(self, basvuru):
        """Kullanılan SIM kartları başvuruya bağlar ve stoktan düşer."""
        from apps.bayi.models import SimKart, SimKartDurumu

        for tanim in self.alan_tanimlari:
            if tanim.tip != AlanTipi.SIM_KART:
                continue
            kart = self.cleaned_data.get(f"_sim_{tanim.kod}")
            if not kart:
                continue
            # Yalnızca hâlâ bayiye atanmışsa güncelle: eşzamanlı iki başvuru
            # aynı kartı kullanamaz.
            SimKart.objects.filter(pk=kart.pk, durum=SimKartDurumu.ATANDI).update(
                durum=SimKartDurumu.KULLANILDI, basvuru=basvuru
            )
