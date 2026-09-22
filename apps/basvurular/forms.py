"""Kategoriye göre kendini kuran başvuru formu.

Formda hangi alanların soruluacağına, ne yazacağına, zorunlu olup olmadığına
ve hangi tipte (metin, sayı, tarih, dosya…) olacağına tamamen yönetim
panelindeki `KategoriAlani` kayıtları karar verir. Kodda sabit alan listesi
yoktur.

Alanın `cekirdek_alan` değeri doluysa girilen değer başvurunun kendi
kolonuna yazılır (aranabilir olur); boşsa `ek_bilgiler` içinde saklanır.
"""

import re
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.basvurular.models import Basvuru, BasvuruBelgesi, BasvuruDurumu, KimlikTipi
from apps.basvurular.gorsel import gorseli_kucult
from apps.basvurular.validators import belge_dogrula
from apps.bayi.templatetags.panel import para
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
        # `capture` bilinçli olarak yok: telefonda doğrudan kamerayı açıyor ve
        # galeriye hiç girilemiyordu. Müşterinin kimliği çoğu zaman zaten
        # çekilmiş oluyor. `accept` ile telefon "Fotoğraf Çek" ve "Galeriden
        # Seç" seçeneklerini birlikte gösterir; kamera bir tık uzakta kalır.
        return forms.ClearableFileInput(attrs={**ortak, "accept": "image/*"})
    if tanim.tip == AlanTipi.DOSYA:
        return forms.ClearableFileInput(attrs={**ortak, "accept": "image/*,application/pdf"})
    return forms.TextInput(attrs=ortak)


class SimKartSecici(forms.Select):
    """SIM kart kutusu; her seçenek kendi operatörünü `data-operator` taşır.

    Operatör seçilince tarayıcı listeyi buna göre daraltır — sunucuya ikinci
    bir tur atılmaz. Kural sunucuda da denetlenir (`_sim_dogrula`).

    Operatör haritası `choices`ın içinde değil ayrı tutulur: Django seçenek
    listesini normalleştirirken ikili demet bekliyor, üçlü demet oraya
    sığmıyor.
    """

    def __init__(self, *args, operatorler=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.operatorler = operatorler or {}

    def optgroups(self, name, value, attrs=None):
        gruplar = super().optgroups(name, value, attrs)
        for _, secenekler, _ in gruplar:
            for secenek in secenekler:
                secenek["attrs"]["data-operator"] = self.operatorler.get(
                    str(secenek["value"]), ""
                )
        return gruplar


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
            kategori.alanlar.filter(aktif=True)
            .prefetch_related("tarifeler")
            .order_by("sira", "id")
        )

        self._kapsami_daralt()
        self._tanimli_alanlari_ekle()

    # -- kurulum ----------------------------------------------------------

    def _kapsami_daralt(self):
        self.fields["operator"].queryset = self.kategori.gecerli_operatorler()
        self.fields["tarife"].queryset = Tarife.objects.filter(
            kategoriler=self.kategori, aktif=True
        ).select_related("operator")
        self.fields["kampanya"].queryset = Kampanya.objects.filter(
            tarife__kategoriler=self.kategori, aktif=True
        ).select_related("tarife")
        self.fields["tarife"].required = self.kategori.tarife_zorunlu

        for ad in ("operator", "tarife", "kampanya", "musteri_tipi"):
            self.fields[ad].widget.attrs.setdefault("class", GIRDI_SINIFI)

        if self.kategori.musteri_tipi != MusteriTipi.HEPSI:
            self.fields["musteri_tipi"].initial = self.kategori.musteri_tipi
            self.fields["musteri_tipi"].widget = forms.HiddenInput()

    @property
    def secili_tarife_id(self):
        """Formda o an seçili tarife (POST'ta gönderilen, GET'te yok)."""
        return self.data.get("tarife") if self.is_bound else self.initial.get("tarife")

    @property
    def gecerli_kampanyalar(self):
        """Kutuda gösterilecek kampanyalar: yalnızca seçili tarifeninkiler.

        Tarife seçilmeden bütün kategorinin kampanyaları listeleniyordu;
        bayi başka tarifenin kampanyasını seçebiliyor, hatayı ancak formu
        gönderince görüyordu. SIM kart kutusundaki kuralın aynısı: listeye
        yalnızca seçilebilecek olan girer. Sunucu doğrulaması yerinde durur.
        """
        tarife_id = self.secili_tarife_id
        if not tarife_id:
            return []
        return [
            kampanya
            for kampanya in self.fields["kampanya"].queryset.filter(tarife_id=tarife_id)
            .order_by("sira", "ad")
            if kampanya.su_an_gecerli
        ]

    def _sim_secenekleri(self):
        """Bayinin stoğundaki kartlar. Aynı formda iki SIM alanı olabilir,
        sorgu bir kez çalışır.

        Her seçenek kendi operatörünü de taşır (`data-operator`): operatör
        seçilince liste ona göre daralır. Vodafone kartıyla Turkcell
        aktivasyonu yapılamaz — hatlar BTK'da IMEI bazında lisanslı.
        """
        from apps.bayi.models import SimKart

        if hasattr(self, "_sim_stogu"):
            return self._sim_stogu

        if self.bayi is None:
            self._sim_stogu = [("", "SIM kart seçin")]
            self._sim_operatorleri = {}
            return self._sim_stogu

        kartlar = (
            SimKart.objects.bayinin_stogu(self.bayi)
            .select_related("operator")
            .order_by("imei")[:500]
        )
        secenekler = [
            (k.imei, f"{k.imei} · {k.operator.ad}" if k.operator_id else k.imei)
            for k in kartlar
        ]
        self._sim_operatorleri = {
            k.imei: str(k.operator_id or "") for k in kartlar
        }
        # Stok boşsa sebebini söyle: boş bir kutu "bir şey bozuldu" gibi durur.
        self._sim_stogu = (
            [("", "SIM kart seçin"), *secenekler]
            if secenekler
            else [("", "Stoğunuzda kullanılabilir SIM kart yok")]
        )
        return self._sim_stogu

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
                # Bayi yalnızca kendisine atanmış, stoktaki SIM'lerle işlem
                # yapabildiği için numarayı elle yazdırmanın anlamı yok: liste
                # zaten girilebilecek kartların tamamı. Seçim kutusu telefonda
                # yerel seçiciyi açar, 16 hane yazarken yapılan hatayı da keser.
                # Değer yine sunucuda doğrulanır (`_sim_dogrula`).
                alan_sinifi = forms.CharField
                argumanlar["widget"] = SimKartSecici(
                    choices=self._sim_secenekleri(),
                    operatorler=self._sim_operatorleri,
                    attrs={"class": GIRDI_SINIFI, "data-sim-kutusu": "1"},
                )
                argumanlar["help_text"] = (
                    tanim.yardim_metni
                    or "Listede yalnızca size zimmetli, seçtiğin operatöre ait "
                    "kullanılmamış kartlar var."
                )

            if tanim.dosya_mi:
                argumanlar["validators"] = [belge_dogrula]

            self.fields[ALAN_ONEKI + tanim.kod] = alan_sinifi(**argumanlar)

    # -- doğrulama --------------------------------------------------------

    def _secili_tarife(self, temiz):
        return temiz.get("tarife")

    def _secili_operator(self, temiz):
        return temiz.get("operator")

    def _bakiye_kapisi(self, temiz, operator, tarife):
        """Bedeli olan işlem parası olmayana verilmez. Kategori ekranı en ucuz
        seçeneğe göre eliyor; burada seçilen operatör ve tarifenin gerçek
        tutarı denetlenir. Sunucu doğrulaması kapıyı son kez kapatır."""
        if self.bayi is None:
            return
        from apps.finans.services import basvuru_bedeli

        bedel = basvuru_bedeli(self.bayi, self.kategori, operator=operator, tarife=tarife)
        cuzdan = getattr(self.bayi, "cuzdan", None)
        bakiye = cuzdan.bakiye if cuzdan else Decimal("0.00")
        if bedel > bakiye:
            self.add_error(
                None,
                f"Bu başvuru için bakiyen yetersiz. Gereken {para(bedel)} ₺, "
                f"bakiyen {para(bakiye)} ₺. Bakiye yüklemek için yöneticinle "
                "iletişime geç.",
            )

    def clean(self):
        temiz = super().clean()

        secili_tarife = self._secili_tarife(temiz)

        for tanim in self.alan_tanimlari:
            anahtar = ALAN_ONEKI + tanim.kod

            # Tarifeye bağlı alan: başka tarife seçilmişse hiç sorulmamış
            # sayılır. Kutu tarayıcıda da gizleniyor ama kural burada durur —
            # gizli girdi elle gönderilse de değer alınmaz, zorunluluk aranmaz.
            if not tanim.tarifede_sorulur_mu(
                secili_tarife.pk if secili_tarife else None
            ):
                temiz[anahtar] = None
                self.errors.pop(anahtar, None)
                continue

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

        tarife = secili_tarife
        operator = self._secili_operator(temiz)
        if tarife and operator and tarife.operator_id != operator.pk:
            self.add_error("tarife", "Seçilen tarife bu operatöre ait değil.")

        self._bakiye_kapisi(temiz, operator, tarife)

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
        elif not self._sim_operatore_uyuyor(kart):
            # Operatörler birbirinin kartını kullanamaz; hatlar BTK'da IMEI
            # bazında lisanslı. Kutu zaten daraltılıyor ama kural burada durur:
            # aksi hâlde ucuz kartı seçip pahalı işlem girmek mümkün olurdu.
            secilen = self._secili_operator(self.cleaned_data)
            self.add_error(
                anahtar,
                f"Bu SIM kart {kart.operator.ad} kartı; "
                f"{secilen.ad if secilen else 'seçtiğiniz operatör'} "
                "aktivasyonunda kullanılamaz.",
            )
        else:
            self.cleaned_data[f"_sim_{tanim.kod}"] = kart

    def _sim_operatore_uyuyor(self, kart):
        """Kartın operatörü, başvurunun operatörüyle aynı mı?

        Kartın operatörü girilmemişse (eski kayıt) engellenmez; yönetici
        stoğu tamamlayana kadar iş durmasın.
        """
        secilen = self._secili_operator(self.cleaned_data)
        if secilen is None or kart.operator_id is None:
            return True
        return kart.operator_id == secilen.pk

    # -- şablon yardımcıları ----------------------------------------------

    @property
    def gruplu_alanlar(self):
        """Dosya olmayan alanları `grup` başlığına göre öbekler.

        Tanımın kendisi de veriliyor: şablon alanın hangi tarifelerde
        sorulduğunu (`tarife_kodlari`) kutunun sarmalayıcısına yazıyor.
        """
        obekler = {}
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi:
                continue
            obekler.setdefault(tanim.grup or "", []).append(
                (tanim, self[ALAN_ONEKI + tanim.kod])
            )
        return obekler.items()

    @property
    def belge_alanlari(self):
        """(tanım, alan, mevcut belge). Yeni başvuruda mevcut belge yoktur;
        düzeltme formu eskisini gösterir."""
        return [
            (tanim, self[ALAN_ONEKI + tanim.kod], None)
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
                    defaults={"dosya": gorseli_kucult(dosya), "etiket": tanim.etiket},
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


class BasvuruDuzeltmeFormu(BasvuruFormu):
    """Bayinin düzenleyebildiği durumdaki (Eksik Evrak) başvuruyu düzeltip
    yeniden gönderme formu.

    Aynı form tanımı, dolu değerlerle: kategori alanları, belgeler, SIM ve
    not düzeltilebilir. **Hat bilgileri (operatör, tarife, kampanya)
    kilitlidir** — fiyat onlardan çıkıyor ve giriş bedeli çoktan kesildi;
    yanlışsa yönetim düzeltir. Bakiye kapısı işlemez: iş zaten satın alındı.

    Belge yalnızca yoksa zorunludur; yüklenmezse eskisi kalır. Onaydan sonra
    silinmiş kimlik görüntüleri (belgeler_silindi) yeniden istenirken alan
    yine zorunlu olur, çünkü kayıt yoktur.

    SIM kutusuna bayinin stoğu ve başvurudaki sağlam kart girer; arızalı
    kart hiç girmez, bayi yerine yenisini seçmek zorunda kalır.
    """

    KILITLI = ("operator", "tarife", "kampanya")

    def __init__(self, *args, basvuru, **kwargs):
        self.basvuru = basvuru
        self.mevcut_belgeler = {b.alan_kodu: b for b in basvuru.belgeler.all()}
        self.mevcut_simler = {
            k.imei: k for k in basvuru.kullanilan_simler
        }
        kwargs.setdefault("initial", {}).update(self._baslangic_degerleri())
        super().__init__(*args, kategori=basvuru.kategori, bayi=basvuru.bayi, **kwargs)
        for ad in self.KILITLI:
            self.fields.pop(ad, None)
        for tanim in self.alan_tanimlari:
            if tanim.dosya_mi and tanim.kod in self.mevcut_belgeler:
                self.fields[ALAN_ONEKI + tanim.kod].required = False

    # -- kurulum ----------------------------------------------------------

    def _baslangic_degerleri(self):
        degerler = {
            "musteri_tipi": self.basvuru.musteri_tipi,
            "bayi_aciklamasi": self.basvuru.bayi_aciklamasi,
        }
        for tanim in self.basvuru.kategori.alanlar.filter(aktif=True):
            if tanim.dosya_mi:
                continue
            if tanim.cekirdek_alan:
                deger = getattr(self.basvuru, tanim.cekirdek_alan, "")
            else:
                deger = self.basvuru.ek_bilgiler.get(tanim.kod)
            if deger in (None, ""):
                continue
            # Evet/Hayır metin olarak ("True") saklanıyor; kutu boolean ister.
            if tanim.tip == AlanTipi.ONAY:
                deger = str(deger) == "True"
            degerler[ALAN_ONEKI + tanim.kod] = deger
        return degerler

    def _sim_secenekleri(self):
        """Stoğun başına başvurudaki sağlam kart eklenir; arızalı girmez."""
        secenekler = super()._sim_secenekleri()
        if hasattr(self, "_duzeltme_simleri_eklendi"):
            return secenekler
        self._duzeltme_simleri_eklendi = True
        mevcut = [
            (k.imei, f"{k.imei} · {k.operator.ad} (takılı)" if k.operator_id else f"{k.imei} (takılı)")
            for k in self.mevcut_simler.values()
        ]
        if not mevcut:
            return secenekler
        for k in self.mevcut_simler.values():
            self._sim_operatorleri[k.imei] = str(k.operator_id or "")
        self._sim_stogu = [("", "SIM kart seçin"), *mevcut, *[s for s in secenekler if s[0]]]
        return self._sim_stogu

    # -- doğrulama --------------------------------------------------------

    def _secili_tarife(self, temiz):
        return self.basvuru.tarife

    def _secili_operator(self, temiz):
        return self.basvuru.operator

    def _bakiye_kapisi(self, temiz, operator, tarife):
        # İş zaten satın alındı; düzeltme yeni bir ücret doğurmaz.
        return

    def _sim_dogrula(self, tanim, anahtar, imei):
        kart = self.mevcut_simler.get(imei)
        if kart is not None:
            # Takılı kart olduğu gibi kalıyor.
            self.cleaned_data[f"_sim_{tanim.kod}"] = kart
            return
        super()._sim_dogrula(tanim, anahtar, imei)

    # -- şablon yardımcıları ----------------------------------------------

    @property
    def belge_alanlari(self):
        """(tanım, alan, mevcut belge) — şablon eskisini gösterir."""
        return [
            (tanim, self[ALAN_ONEKI + tanim.kod], self.mevcut_belgeler.get(tanim.kod))
            for tanim in self.alan_tanimlari
            if tanim.dosya_mi
        ]

    @property
    def bozuk_simler(self):
        return list(self.basvuru.bozuk_simler)

    # -- kaydetme ---------------------------------------------------------

    def kaydet_duzeltme(self, degistiren):
        """Değişenleri yazar, başvuruyu bildirim öncesi durumuna döndürür.

        Neyin değiştiği durum geçmişine düşer; yönetim "bayi neyi düzeltti"
        diye alan alan karşılaştırmasın.
        """
        from django.db import transaction

        from apps.basvurular.services import duzeltmeyi_gonder

        basvuru = self.basvuru
        degisenler = []

        with transaction.atomic():
            basvuru.musteri_tipi = self.cleaned_data.get("musteri_tipi") or basvuru.musteri_tipi
            basvuru.bayi_aciklamasi = self.cleaned_data.get("bayi_aciklamasi", "")

            for tanim in self.alan_tanimlari:
                if tanim.dosya_mi:
                    continue
                anahtar = ALAN_ONEKI + tanim.kod
                if tanim.tip == AlanTipi.SIM_KART:
                    degisiklik = self._simi_guncelle(tanim)
                    if degisiklik:
                        degisenler.append(degisiklik)
                    continue
                deger = self.cleaned_data.get(anahtar)
                yeni = "" if deger in (None, "") else str(deger)
                if tanim.cekirdek_alan:
                    eski = getattr(basvuru, tanim.cekirdek_alan, "") or ""
                    if yeni != eski:
                        setattr(basvuru, tanim.cekirdek_alan, yeni)
                        degisenler.append(tanim.etiket)
                else:
                    eski = basvuru.ek_bilgiler.get(tanim.kod) or ""
                    if yeni != eski:
                        if yeni:
                            basvuru.ek_bilgiler[tanim.kod] = yeni
                        else:
                            basvuru.ek_bilgiler.pop(tanim.kod, None)
                        degisenler.append(tanim.etiket)

            for tanim in self.alan_tanimlari:
                if not tanim.dosya_mi:
                    continue
                dosya = self.cleaned_data.get(ALAN_ONEKI + tanim.kod)
                if dosya:
                    # Eski dosya kayıt değişince commit sonrasında diskten silinir
                    # (apps/dosya.py).
                    BasvuruBelgesi.objects.update_or_create(
                        basvuru=basvuru,
                        alan_kodu=tanim.kod,
                        defaults={"dosya": gorseli_kucult(dosya), "etiket": tanim.etiket},
                    )
                    degisenler.append(tanim.etiket)

            basvuru.full_clean(exclude=["referans_no"])
            basvuru.save()
            duzeltmeyi_gonder(basvuru, degistiren=degistiren, degisenler=degisenler)

        return basvuru

    def _simi_guncelle(self, tanim):
        """SIM değiştiyse eski kartı serbest bırakır, yenisini takar.

        Sağlam eski kart bayinin stoğuna döner (elinde duruyor, kullanılmadı);
        arızalı kart arızalı kalır, takibi ayrı. Yeni kart yalnızca hâlâ
        stoktaysa takılır: eşzamanlı iki başvuru aynı kartı kullanamaz.

        **Hangi başvuruda kullanıldığı silinmez** (`basvuru` bağı durur;
        iptalde kartları serbest bırakan `basvurunun_simlerini_serbest_birak`
        da aynısını yapar). Bağ koparıldığında "bu kart hangi işte bozuldu"
        sorusu cevapsız kalıyordu: yönetici kartı sonradan arızalı işaretlese
        de arıza sayfasında başvuru satırı boş çıkıyordu. Kart yeniden
        kullanılırsa bağ yeni başvuruyla güncellenir.

        Değişiklik özeti IMEI'leri taşır: geçmişte "SIM Kart" yazması hangi
        kartın çıktığını söylemiyordu.
        """
        from apps.bayi.models import SimKart, SimKartDurumu

        basvuru = self.basvuru
        yeni_kart = self.cleaned_data.get(f"_sim_{tanim.kod}")
        eski_imei = basvuru.ek_bilgiler.get(tanim.kod) or ""
        if yeni_kart is None or yeni_kart.imei == eski_imei:
            return ""

        adet = SimKart.objects.filter(pk=yeni_kart.pk, durum=SimKartDurumu.ATANDI).update(
            durum=SimKartDurumu.KULLANILDI, basvuru=basvuru
        )
        if not adet:
            raise ValidationError(
                {ALAN_ONEKI + tanim.kod: "Bu SIM kart az önce başka bir başvuruda kullanıldı."}
            )
        SimKart.objects.filter(
            imei=eski_imei, basvuru=basvuru, durum=SimKartDurumu.KULLANILDI
        ).update(durum=SimKartDurumu.ATANDI)
        basvuru.ek_bilgiler[tanim.kod] = yeni_kart.imei
        return (
            f"{tanim.etiket} ({eski_imei} → {yeni_kart.imei})"
            if eski_imei
            else f"{tanim.etiket} ({yeni_kart.imei})"
        )
