"""Znet / Gencan protokolü (`tl_servis.php`).

Türkiye'deki kontör bayi yazılımlarının çoğunun ortak dili. Bizim bayilere
açtığımız kapı da bu protokolü konuşur (`apps.kontor.api`).

Gönderim — `servis/tl_servis.php`:
    ?bayi_kodu=…&sifre=…&operator=vodafone&tip=ses&kontor=100&gsmno=532…&tekilnumara=…
    OK|1|Talebiniz alınmıştır|12.50     kabul; son alan düşülen tutar
    OK|3|Yetersiz bakiye|0.00            ret; işlem açılmadı

Sonuç — `servis/tl_kontrol.php`:
    ?bayi_kodu=…&sifre=…&tekilnumara=…
    1:Yüklendi:12.50                     başarılı
    2:islemde:0                          sürüyor
    3:Numara hatalı                      iptal

Eski sistemde `OK|8` gibi tanınmayan kodlar da askıya alınıyordu; burada
da aynı: yalnızca `1` kabul, yalnızca `3` ret sayılır, gerisi belirsizdir.
Cevaplar URL kodlu gelebiliyor ("Y%C3%BCklendi+-ONAYLANDI"); çözülür.

Aynı yazılımın oyun pini ve fatura servisleri de var (sağlayıcının
`api.pdf`'i); kimliği `kod` + `sifre` ile ister, kontördeki `bayi_kodu`
değil. Oyun pini — `servis/pin_ekle.php`, sonucu `pin_kontrol.php`:
    ?oyun=1&kupur=325&referans=…&musteri_tel=&oyuncu_bilgi=…
    OK|10.12|980.88                       kabul; maliyet, kalan bakiye
    3|Açıklama                            ret
    OK|2|AB12-CD34|Açıklama               yüklendi; üçüncü alan pin
    OK|1| |Açıklama  /  OK|3| |Açıklama   sürüyor / iptal
Fatura — `servis/fatura_ekle.php`, sonucu `fatura_kontrol.php`:
    ?kurum_id=8&tahsilat_api_islem_id=…&fatura_no=…&fatura_tutari=110.15…
    OK|0.30|2644.78|110.45                kabul; maliyet, kalan, toplam düşen
    4|Daha Önce Gönderilmiş (166189)      numara başka işlemde kullanılmış: ret
    3|Açıklama                            ret
    ?tahsilat_api_islem_id=1032           (sonuç, canlıda görülen cevaplar)
    2|vodafone pos ()                     ödendi
    3|                                    iptal
    1|…                                   bekliyor
"""

import json
import re
from datetime import datetime
from urllib.parse import unquote, unquote_plus

from apps.kontor.saglayicilar import (
    Adaptor,
    Gonderim,
    GonderimSonucu,
    SaglayiciHatasi,
    SaglayiciKurumu,
    SaglayiciPaketVerisi,
    Sorgu,
    SorguSonucu,
    tutar_coz,
)
from apps.kontor.saglayicilar.http import metin_istek

# Pin ürününün karşı site kodu: "<oyun>-<kupür>" (pin listesinden "1-325").
# Sağlayıcı ürünü bu ikisiyle arıyor; tek kod alanına ikisi birden yazılır.
PIN_AYRACI = "-"


def gonderim_coz(ham):
    parcalar = [p.strip() for p in unquote_plus(ham or "").split("|")]
    mesaj = parcalar[2] if len(parcalar) > 2 else ""
    if parcalar[0].upper() == "OK" and len(parcalar) > 1:
        if parcalar[1] == "1":
            alis = tutar_coz(parcalar[3]) if len(parcalar) > 3 else None
            return GonderimSonucu(Gonderim.KABUL, mesaj=mesaj, alis=alis, ham=ham)
        if parcalar[1] == "3":
            return GonderimSonucu(Gonderim.RED, mesaj=mesaj or "Sağlayıcı reddetti.", ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=mesaj or ham[:200], ham=ham)


def sorgu_coz(ham):
    parcalar = [p.strip() for p in unquote_plus(ham or "").split(":")]
    kod = parcalar[0]
    mesaj = parcalar[1] if len(parcalar) > 1 else ""
    if kod == "1":
        alis = tutar_coz(parcalar[2]) if len(parcalar) > 2 else None
        return SorguSonucu(Sorgu.BASARILI, mesaj=mesaj, alis=alis, ham=ham)
    if kod == "3":
        return SorguSonucu(Sorgu.IPTAL, mesaj=mesaj or "Sağlayıcı iptal etti.", ham=ham)
    # "2:islemde" ve tanınmayan her şey: bir sonraki turda yeniden sorulur.
    return SorguSonucu(Sorgu.ISLEMDE, mesaj=mesaj, ham=ham)


class Znet(Adaptor):
    """Znet ve Gencan aynı yazılımın iki adı: kullanıcı adı + şifreyle konuşur.

    Fiyat listesi `ClientWebService`'ten JSON gelir (`TopUpPrices`); bayi
    kodu, kullanıcı adı ve şifre üçü birden istenir. Listeyi vermeyen site
    hata döner, alış fiyatları o zaman rotaya elle yazılır.
    """

    kod = "znet"
    ad = "Znet / Gencan (tl_servis)"
    varsayilan_sema = "http"
    paket_listesi_var = True
    fatura_var = True

    def _kimlik(self):
        return {"bayi_kodu": self.saglayici.kullanici_adi, "sifre": self.saglayici.sifre}

    def _servis_kimligi(self):
        # Pin ve fatura servisleri aynı hesabı `kod` adıyla ister.
        return {"kod": self.saglayici.kullanici_adi, "sifre": self.saglayici.sifre}

    def gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        ham = metin_istek(
            f"{self.taban()}/servis/tl_servis.php",
            parametreler={
                **self._kimlik(),
                "operator": uzak_operator,
                "tip": uzak_tip,
                "kontor": uzak_kod,
                "gsmno": hedef,
                "tekilnumara": ref,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return gonderim_coz(ham)

    def sorgula(self, *, ref, uzak_ref):
        ham = metin_istek(
            f"{self.taban()}/servis/tl_kontrol.php",
            parametreler={**self._kimlik(), "tekilnumara": ref},
            saglayici_adi=self.saglayici.ad,
        )
        return sorgu_coz(ham)

    def paketleri_getir(self):
        """Kontör fiyat listesi ve oyun pini listesi birlikte.

        Biri alınamazsa öbürü yine döner: pin servisi olmayan sitede kontör
        listesi, kontör listesini vermeyen sitede (Kontorbizde) pinler.
        İkisi de alınamazsa hata.
        """
        sonuc, hatalar = [], []
        for getir in (self._kontor_listesi, self._pin_listesi):
            try:
                sonuc.extend(getir())
            except SaglayiciHatasi as hata:
                hatalar.append(str(hata))
        if not sonuc and hatalar:
            raise SaglayiciHatasi(" · ".join(hatalar))
        return sonuc

    def _kontor_listesi(self):
        ham = metin_istek(
            f"{self.taban()}/ClientWebService",
            form={
                "Operation": "TopUpPrices",
                "request[DealerCode]": self.saglayici.bayi_kodu,
                "request[Username]": self.saglayici.kullanici_adi,
                "request[Password]": self.saglayici.sifre,
            },
            saglayici_adi=self.saglayici.ad,
        )
        return paket_listesi_coz(ham)

    def _pin_listesi(self):
        ham = metin_istek(
            f"{self.taban()}/servis/pin_listesi.php",
            parametreler=self._servis_kimligi(),
            saglayici_adi=self.saglayici.ad,
        )
        return pin_listesi_coz(ham)

    # -- Oyun / e-pin -----------------------------------------------------

    def oyun_gonder(self, *, ref, hedef, uzak_kod, uzak_operator, uzak_tip):
        oyun, kupur = pin_kodu_coz(uzak_kod)
        ham = metin_istek(
            f"{self.taban()}/servis/pin_ekle.php",
            parametreler={
                **self._servis_kimligi(),
                "oyun": oyun,
                "kupur": kupur,
                "referans": ref,
                "musteri_tel": "",
                # Oyuncu ID ile yüklenen oyunda hesap; pin satışında boş.
                "oyuncu_bilgi": hedef or "",
            },
            saglayici_adi=self.saglayici.ad,
        )
        return pin_gonderim_coz(ham)

    def oyun_sorgula(self, *, ref, uzak_ref):
        ham = metin_istek(
            f"{self.taban()}/servis/pin_kontrol.php",
            parametreler={**self._servis_kimligi(), "tahsilat_api_islem_id": ref},
            saglayici_adi=self.saglayici.ad,
        )
        return pin_sorgu_coz(ham)

    # -- Fatura -----------------------------------------------------------

    def fatura_gonder(self, *, ref, kurum_id, abone_adi, son_odeme_tarihi, tesisat_no, fatura_no, tutar):
        ham = metin_istek(
            f"{self.taban()}/servis/fatura_ekle.php",
            parametreler={
                **self._servis_kimligi(),
                "kurum_id": kurum_id,
                "tahsilat_api_islem_id": ref,
                "abone_adi": abone_adi,
                "son_odeme_tarihi": tarih_bicimi(son_odeme_tarihi),
                "tesisat_no": tesisat_no,
                # Yalnızca iki alanlı kurumlar (Tedaş) için; bizde tek alan var.
                "kurum_kodu": "",
                "fatura_no": fatura_no,
                "fatura_tutari": f"{tutar:.2f}",
            },
            saglayici_adi=self.saglayici.ad,
        )
        return fatura_gonderim_coz(ham)

    def fatura_sorgula(self, ref):
        ham = metin_istek(
            f"{self.taban()}/servis/fatura_kontrol.php",
            parametreler={**self._servis_kimligi(), "tahsilat_api_islem_id": ref},
            saglayici_adi=self.saglayici.ad,
        )
        return fatura_sorgu_coz(ham)

    def fatura_kurumlari(self):
        ham = metin_istek(
            f"{self.taban()}/servis/kurum_listesi.php",
            parametreler=self._servis_kimligi(),
            saglayici_adi=self.saglayici.ad,
        )
        return kurum_listesi_coz(ham)


def paket_listesi_coz(ham):
    try:
        veri = json.loads(ham)
        paketler = veri["TopUpPricesResult"]["Packages"] or []
    except (ValueError, KeyError, TypeError):
        raise SaglayiciHatasi(f"Fiyat listesi okunamadı: {ham[:200]}")
    sonuc = []
    for paket in paketler:
        fiyat = tutar_coz(paket.get("Price"))
        kod = str(paket.get("ProductId") or "").strip()
        if not kod or fiyat is None:
            continue
        sonuc.append(
            SaglayiciPaketVerisi(
                kod=kod,
                ad=str(paket.get("PackageName") or kod).strip(),
                fiyat=fiyat,
                operator=str(paket.get("Operator") or "").strip(),
                tip=str(paket.get("Type") or "").strip(),
            )
        )
    return sonuc


# -- Oyun / e-pin -----------------------------------------------------------


def pin_listesi_coz(ham):
    """`pin_listesi.php` (JSON) → paket verisi; kod "<oyun_id>-<kupur>"."""
    try:
        veri = json.loads(ham)
    except (TypeError, ValueError):
        raise SaglayiciHatasi(f"Pin listesi okunamadı: {(ham or '')[:200]}")
    if not isinstance(veri, dict) or not veri.get("success"):
        hata = veri.get("error") if isinstance(veri, dict) else ""
        raise SaglayiciHatasi(f"Pin listesi alınamadı: {hata or (ham or '')[:200]}")
    sonuc = []
    for urun in veri.get("result") or []:
        if not isinstance(urun, dict):
            continue
        oyun = str(urun.get("oyun_id") or "").strip()
        kupur = str(urun.get("kupur") or "").strip()
        fiyat = tutar_coz(urun.get("fiyat"))
        if not oyun or not kupur or fiyat is None:
            continue
        sonuc.append(
            SaglayiciPaketVerisi(
                kod=f"{oyun}{PIN_AYRACI}{kupur}",
                ad=str(urun.get("adi") or "").strip() or f"{oyun}{PIN_AYRACI}{kupur}",
                fiyat=fiyat,
                operator=str(urun.get("oyun_adi") or "").strip(),
                tip="pin",
            )
        )
    return sonuc


def pin_kodu_coz(kod):
    """"1-325" → ("1", "325"). Biçime uymayan kod gönderilmez: sağlayıcı ürünü bulamaz.

    Oyun numarası sağlayıcının `oyun_id`'sidir, rakamdır. Karşı site kodu
    girilmemiş pakette bizim kod ("pubg-325") gider; o da burada durur.
    """
    oyun, ayrac, kupur = str(kod or "").strip().partition(PIN_AYRACI)
    if not ayrac or not oyun.strip().isdigit() or not kupur.strip():
        raise SaglayiciHatasi(
            f"Pin kodu “oyun-kupür” biçiminde olmalı (pin listesinden, ör. 1-325); giden kod: {kod or '—'}",
            kesin_gitmedi=True,
        )
    return oyun.strip(), kupur.strip()


def _parcalar(ham):
    parcalar = [p.strip() for p in unquote_plus(ham or "").strip().split("|")]
    while len(parcalar) > 1 and parcalar[-1] == "":
        parcalar.pop()
    return parcalar


def pin_gonderim_coz(ham):
    """`OK|maliyet|kalan` kabul, `3|Açıklama` ret, gerisi belirsiz.

    Kontörün `OK|3|…` biçimi burada kabul sayılmaz: üç alan da tutar
    olmalı, yoksa "3" maliyet diye okunurdu.
    """
    parcalar = _parcalar(ham)
    if parcalar[0].upper() == "OK" and len(parcalar) == 3:
        alis, kalan = tutar_coz(parcalar[1]), tutar_coz(parcalar[2])
        if alis is not None and kalan is not None:
            return GonderimSonucu(Gonderim.KABUL, alis=alis, maliyet=alis, ham=ham)
    if parcalar[0] == "3":
        mesaj = "|".join(parcalar[1:]) or "Sağlayıcı reddetti."
        return GonderimSonucu(Gonderim.RED, mesaj=mesaj, ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=(ham or "")[:200], ham=ham)


def pin_sorgu_coz(ham):
    """`OK|2|PİN|Açıklama` yüklendi (mesaj pin), `OK|3` iptal, gerisi sürüyor.

    Pin `+` taşıyabilir; boşluğa çevrilmesin diye yalnızca %-kodları çözülür.
    `3|Açıklama` (OK'siz) sorgunun kendi hatasıdır, işlemin iptali değil:
    sorulmaya devam edilir, yönetim cevabı karar ekranında görür.
    """
    parcalar = [p.strip() for p in (ham or "").strip().split("|")]
    if parcalar[0].upper() == "OK" and len(parcalar) > 1:
        kod = parcalar[1]
        pin = unquote(parcalar[2]).strip() if len(parcalar) > 2 else ""
        aciklama = unquote_plus("|".join(parcalar[3:])).strip(" |")
        if kod == "2":
            return SorguSonucu(Sorgu.BASARILI, mesaj=pin or aciklama, ham=ham)
        if kod == "3":
            return SorguSonucu(Sorgu.IPTAL, mesaj=aciklama or "Sağlayıcı iptal etti.", ham=ham)
        return SorguSonucu(Sorgu.ISLEMDE, mesaj=aciklama, ham=ham)
    return SorguSonucu(Sorgu.ISLEMDE, mesaj=unquote_plus(ham or "")[:200], ham=ham)


# -- Fatura -----------------------------------------------------------------


def tarih_bicimi(metin):
    """Sorgu sayfasının "14.10.2026"sı → API'nin "2026-10-14"ü; okunamazsa olduğu gibi."""
    ilk = str(metin or "").strip().split(" ")[0]
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(ilk, bicim).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return str(metin or "").strip()


def fatura_gonderim_coz(ham):
    """`OK|maliyet|kalan|toplam` kabul (alış = toplam düşen), `3|…` ve `4|…` ret.

    `4|Daha Önce Gönderilmiş` da rettir: her numarayı yalnızca bir kez
    gönderiyoruz, çakışma numaranın başka bir işlemde (eski sistem) kullanıldığını
    gösterir — bu istek orada hiçbir şey açmadı. Belirsiz sayılsaydı "Sonucu
    sorgula" aynı numarayla başka bir faturanın sonucunu okuyup ödemeyi
    kapatabilir ya da iade edebilirdi.
    """
    parcalar = _parcalar(ham)
    if parcalar[0].upper() == "OK" and len(parcalar) >= 4:
        toplam = tutar_coz(parcalar[3])
        if toplam is not None:
            return GonderimSonucu(
                Gonderim.KABUL, alis=toplam, maliyet=tutar_coz(parcalar[1]), ham=ham
            )
    if parcalar[0] in ("3", "4"):
        mesaj = "|".join(parcalar[1:]) or "Sağlayıcı reddetti."
        return GonderimSonucu(Gonderim.RED, mesaj=mesaj, ham=ham)
    return GonderimSonucu(Gonderim.BELIRSIZ, mesaj=(ham or "")[:200], ham=ham)


_FATURA_SONUCU = re.compile(r"(\d+)\s*(?:[|:](.*))?", re.S)


def fatura_sorgu_coz(ham):
    """Tek işlem: `1|…` bekliyor, `2|…` ödendi, `3|…` iptal.

    Ayraç dikey çizgidir; canlıda `2|vodafone pos ()` (ödendi) ve `3|`
    (iptal) görüldü. Bir süre iki nokta (`2:…`) beklendi: cevap okunamayınca
    "bekliyor" sayıldı, sağlayıcının onayladığı da iptal ettiği de bizde
    "Ödeniyor"da kaldı. İki nokta da okunur.

    `3`ün açıklaması olduğu gibi döner, boşsa boş: kendiliğinden iade yalnızca
    açıklamasız `3|`te yapılır (`fatura.services._sonuclandir`), çünkü `3|…`
    bir hata metni de olabilir (şifre, kayıt bulunamadı). Başka her cevap
    (boş, tanınmayan kod) `SaglayiciHatasi`'dır: gönderim olduğu gibi kalır,
    cevap "Sorgu hatası" diye yazılır — sessizce "bekliyor" sayılmaz.
    """
    metin = unquote_plus(ham or "").strip()
    eslesme = _FATURA_SONUCU.fullmatch(metin)
    if not eslesme or eslesme.group(1) not in ("1", "2", "3"):
        raise SaglayiciHatasi(f"Fatura sonucu okunamadı: {metin[:200] or 'boş cevap'}")
    kod, aciklama = eslesme.group(1), (eslesme.group(2) or "").strip(" |:")
    if kod == "2":
        return SorguSonucu(Sorgu.BASARILI, mesaj=aciklama, ham=ham)
    if kod == "3":
        return SorguSonucu(Sorgu.IPTAL, mesaj=aciklama, ham=ham)
    return SorguSonucu(Sorgu.ISLEMDE, mesaj=aciklama, ham=ham)


def kurum_listesi_coz(ham):
    """`ID,SORGU KODU,ADI,MALİYET,ÖZEL#…` → kurumlar. Ad virgül taşıyabilir."""
    sonuc = []
    for blok in unquote_plus(ham or "").split("#"):
        parcalar = [p.strip() for p in blok.strip().split(",")]
        if len(parcalar) < 5 or not parcalar[0].isdigit():
            continue
        ad = ",".join(parcalar[2:-2]).strip()
        if not ad:
            continue
        sonuc.append(
            SaglayiciKurumu(kod=parcalar[0], ad=ad, sorgu_kodu=parcalar[1], maliyet=tutar_coz(parcalar[-2]))
        )
    if not sonuc:
        raise SaglayiciHatasi(f"Kurum listesi alınamadı: {(ham or '')[:200] or 'boş cevap'}")
    return sonuc
