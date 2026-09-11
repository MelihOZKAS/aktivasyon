"""eSIM Access (esimaccess.com) adaptörü.

Belge: https://docs.esimaccess.com — bütün uçlar POST, gövde JSON, kimlik
`RT-AccessCode` başlığında. Gizli anahtar girilmişse istek HMAC-SHA256 ile
de imzalanır (`RT-Timestamp`, `RT-RequestID`, `RT-Signature`); anahtar
boşsa yalnızca erişim kodu gider — sağlayıcı ikisini de kabul ediyor.

Fiyatlar USD ve **10.000 ile çarpılmış tam sayı** (10000 = 1,00 $). Hacim
bayt, süre gün. Sandbox yok: her sipariş gerçek bakiyeden düşer, deneme
siparişi `iptal_et` ile iade edilir.

Yalnızca **sabit paketler** (dataType 1) alınır. Günlük paketler
(dataType 2, "1GB/Gün") gün sayısına göre kademeli indirimle fiyatlanıyor;
bu sürümde onlar katalogda yok.
"""

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

from apps.esim.saglayicilar import (
    Adaptor,
    PaketVerisi,
    ProfilVerisi,
    SaglayiciHatasi,
    YuklemeVerisi,
)

logger = logging.getLogger(__name__)

ADRES = "https://api.esimaccess.com/api/v1/open/"
ZAMAN_ASIMI = 30
FIYAT_CARPANI = Decimal(10000)

# Sağlayıcı bu kodla "profil hâlâ hazırlanıyor" der; hata değil, beklemedir.
HAZIRLANIYOR = "200010"
SABIT_PAKET = 1


class EsimAccess(Adaptor):
    kod = "esimaccess"
    ad = "eSIM Access"

    # -- HTTP ------------------------------------------------------------

    def _istek(self, yol, govde=None):
        veri = json.dumps(govde or {}, separators=(",", ":")).encode()
        basliklar = {
            "Content-Type": "application/json",
            "RT-AccessCode": self.saglayici.erisim_kodu,
        }
        if self.saglayici.gizli_anahtar:
            basliklar.update(self._imza(veri))

        istek = urllib.request.Request(ADRES + yol, data=veri, headers=basliklar)
        try:
            with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
                sonuc = json.loads(yanit.read().decode())
        except urllib.error.HTTPError as hata:
            raise SaglayiciHatasi(f"eSIM Access HTTP {hata.code}", str(hata.code))
        except (urllib.error.URLError, OSError, ValueError) as hata:
            raise SaglayiciHatasi(f"eSIM Access'e ulaşılamadı: {hata}")

        if not sonuc.get("success"):
            kod = str(sonuc.get("errorCode") or "")
            raise SaglayiciHatasi(
                sonuc.get("errorMsg") or f"eSIM Access hata kodu {kod}", kod
            )
        return sonuc.get("obj") or {}

    def _imza(self, govde):
        zaman = str(int(time.time() * 1000))
        istek_no = uuid.uuid4().hex
        metin = zaman + istek_no + self.saglayici.erisim_kodu + govde.decode()
        imza = hmac.new(
            self.saglayici.gizli_anahtar.encode(), metin.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "RT-Timestamp": zaman,
            "RT-RequestID": istek_no,
            "RT-Signature": imza,
        }

    # -- Arayüz ----------------------------------------------------------

    def paketleri_getir(self):
        obj = self._istek("package/list", {"type": "BASE"})
        return self._paketleri_coz(obj)

    def _paketleri_coz(self, obj):
        paketler = []
        for ham in obj.get("packageList") or []:
            if ham.get("dataType") != SABIT_PAKET:
                continue
            if (ham.get("durationUnit") or "DAY") != "DAY":
                continue
            ulkeler = [k.strip().upper() for k in (ham.get("location") or "").split(",") if k.strip()]
            if not ulkeler:
                continue

            adlar, operatorler = {}, []
            for konum in ham.get("locationNetworkList") or []:
                kod = (konum.get("locationCode") or "").upper()
                if kod and konum.get("locationName"):
                    adlar[kod] = konum["locationName"]
                for op in konum.get("operatorList") or []:
                    etiket = " ".join(
                        p for p in (op.get("operatorName"), op.get("networkType")) if p
                    )
                    if etiket and etiket not in operatorler:
                        operatorler.append(etiket)

            paketler.append(
                PaketVerisi(
                    kod=ham["packageCode"],
                    slug=ham.get("slug") or "",
                    ad=ham.get("name") or ham["packageCode"],
                    ulkeler=ulkeler,
                    hacim_bayt=int(ham.get("volume") or 0),
                    sure_gun=int(ham.get("duration") or 0),
                    alis_usd=Decimal(int(ham.get("price") or 0)) / FIYAT_CARPANI,
                    hiz=ham.get("speed") or "",
                    operatorler=", ".join(operatorler)[:255],
                    aciklama=ham.get("description") or "",
                    ulke_adlari=adlar,
                )
            )
        return paketler

    def bakiye(self):
        obj = self._istek("balance/query")
        return Decimal(int(obj.get("balance") or 0)) / FIYAT_CARPANI

    def siparis_ver(self, paket_kodu, islem_no, alis_usd):
        # Fiyat da gönderilir: sağlayıcı zam yaptıysa sipariş 200005 ile
        # düşer, bayiden eski fiyata alınmış bir işlem zararına açılmaz.
        fiyat = int(Decimal(alis_usd) * FIYAT_CARPANI)
        obj = self._istek(
            "esim/order",
            {
                "transactionId": islem_no,
                "amount": fiyat,
                "packageInfoList": [{"packageCode": paket_kodu, "count": 1, "price": fiyat}],
            },
        )
        siparis_no = obj.get("orderNo")
        if not siparis_no:
            raise SaglayiciHatasi("eSIM Access sipariş numarası vermedi.")
        # Profil eşzamansız tahsis edilir; `profil_getir` ile sorulur.
        return siparis_no, None

    def profil_getir(self, saglayici_siparis_no):
        try:
            obj = self._istek(
                "esim/query",
                {"orderNo": saglayici_siparis_no, "pager": {"pageNum": 1, "pageSize": 10}},
            )
        except SaglayiciHatasi as hata:
            if hata.kod == HAZIRLANIYOR:
                return None
            raise

        esimler = obj.get("esimList") or []
        if not esimler:
            return None
        esim = esimler[0]
        if not esim.get("ac"):
            return None
        return ProfilVerisi(
            esim_no=esim.get("esimTranNo") or "",
            iccid=esim.get("iccid") or "",
            ac=esim["ac"],
            qr_url=esim.get("qrCodeUrl") or "",
            kisa_url=esim.get("shortUrl") or "",
            apn=esim.get("apn") or "",
            durum=esim.get("esimStatus") or "",
        )

    def iptal_et(self, esim_no, *, iccid="", paket_kodu=""):
        govde = {"esimTranNo": esim_no} if esim_no else {"iccid": iccid}
        self._istek("esim/cancel", govde)

    # -- Yükleme ---------------------------------------------------------

    def yukleme_paketleri(self, esim_no, *, iccid="", paket_kodu=""):
        """Bu eSIM'e uyan yükleme paketleri; kod "TOPUP_" ile başlar."""
        govde = {"type": "TOPUP"}
        if esim_no:
            govde["esimTranNo"] = esim_no
        elif iccid:
            govde["iccid"] = iccid
        else:
            govde["packageCode"] = paket_kodu
        return self._paketleri_coz(self._istek("package/list", govde))

    def yukle(self, esim_no, yukleme_kodu, islem_no, alis_usd, *, iccid=""):
        govde = {
            "packageCode": yukleme_kodu,
            "transactionId": islem_no,
            "amount": str(int(Decimal(alis_usd) * FIYAT_CARPANI)),
        }
        if esim_no:
            govde["esimTranNo"] = esim_no
        else:
            govde["iccid"] = iccid
        obj = self._istek("esim/topup", govde)
        return YuklemeVerisi(
            yukleme_no=obj.get("topUpEsimTranNo") or "",
            toplam_hacim_bayt=int(obj.get("totalVolume") or 0),
            toplam_sure_gun=int(obj.get("totalDuration") or 0),
            son_kullanma=obj.get("expiredTime") or "",
        )
