"""eSIM Go (esim-go.com) adaptörü — belgeden yazıldı, canlı anahtarla denenmedi.

Belge: https://docs.esim-go.com/api/ (v2.5). Kimlik `X-API-Key` başlığı,
yanıtlar zarfsız (dizi ya da nesne), hatalar `{"message": "..."}`.
Fiyat kuruluş para biriminde ondalık sayı — hesap USD açıldıysa USD.
Hacim MB (`dataAmount`), süre gün. Sınırsız paketler alınmaz.

Sipariş **eşzamanlıdır**: `POST /orders` profili (ICCID, SM-DP+, eşleşme
kodu) hemen döndürür; `profil_getir` yalnızca yeniden sorgulamada kullanılır.

Kayıt: self-servis, en az 1.000 $ yükleme. Sandbox yok — `type: validate`
yalnızca fiyat doğrular. **İade** hesapta ayrıca açtırılmalı: açık değilse
`DELETE .../bundles/...?refundToBalance=true` paketi geri alır ama parayı
**iade etmez** (belge böyle diyor). İadeyi kullanmadan önce eSIM Go'dan
açtırın; aksi hâlde bayiye iade edilen para bizden çıkar.
"""

from decimal import Decimal, InvalidOperation

from apps.esim.saglayicilar import Adaptor, PaketVerisi, ProfilVerisi, SaglayiciHatasi
from apps.esim.saglayicilar.http import json_istek

ADRES = "https://api.esim-go.com/v2.5"
SAYFA_BOYU = 200
MB = 1024**2


class EsimGo(Adaptor):
    kod = "esimgo"
    ad = "eSIM Go"
    denenmedi = True

    def _istek(self, yol, *, yontem="GET", govde=None):
        durum, sonuc = json_istek(
            ADRES + yol,
            yontem=yontem,
            govde=govde,
            basliklar={"X-API-Key": self.saglayici.erisim_kodu},
            saglayici_adi=self.ad,
        )
        if durum >= 400:
            mesaj = sonuc.get("message") if isinstance(sonuc, dict) else ""
            raise SaglayiciHatasi(mesaj or f"eSIM Go HTTP {durum}", str(durum))
        return sonuc

    # -- Arayüz ----------------------------------------------------------

    def paketleri_getir(self):
        paketler = []
        sayfa = 1
        while True:
            liste = self._istek(f"/catalogue?page={sayfa}&perPage={SAYFA_BOYU}")
            if isinstance(liste, dict):
                liste = liste.get("bundles") or []
            if not liste:
                break
            for ham in liste:
                paket = self._paket(ham)
                if paket:
                    paketler.append(paket)
            if len(liste) < SAYFA_BOYU:
                break
            sayfa += 1
        return paketler

    @staticmethod
    def _paket(ham):
        if ham.get("unlimited") or not ham.get("name"):
            return None
        if (ham.get("billingType") or "FixedCost") != "FixedCost":
            return None
        ulkeler = [
            (u.get("iso") or "").upper() for u in ham.get("countries") or [] if u.get("iso")
        ]
        if not ulkeler:
            return None
        try:
            fiyat = Decimal(str(ham.get("price") or 0))
        except InvalidOperation:
            return None
        return PaketVerisi(
            kod=ham["name"],
            ad=ham.get("description") or ham["name"],
            ulkeler=ulkeler,
            hacim_bayt=int(ham.get("dataAmount") or 0) * MB,
            sure_gun=int(ham.get("duration") or 0),
            alis_usd=fiyat,
            hiz=ham.get("speed") or "",
            aciklama="",
            ulke_adlari={
                (u.get("iso") or "").upper(): u.get("name", "") for u in ham.get("countries") or []
            },
        )

    def bakiye(self):
        obj = self._istek("/organisation")
        try:
            return Decimal(str(obj.get("balance") or 0))
        except InvalidOperation:
            raise SaglayiciHatasi("eSIM Go bakiyesi okunamadı.")

    def siparis_ver(self, paket_kodu, islem_no, alis_usd):
        # eSIM Go'da tekil işlem anahtarı yok; istek yinelenmez.
        obj = self._istek(
            "/orders",
            yontem="POST",
            govde={
                "type": "transaction",
                "assign": True,
                "order": [
                    {"type": "bundle", "quantity": 1, "item": paket_kodu, "allowReassign": False}
                ],
            },
        )
        if (obj.get("status") or "").lower() not in ("completed", "success", ""):
            raise SaglayiciHatasi(obj.get("statusMessage") or f"eSIM Go sipariş durumu: {obj.get('status')}")
        kalemler = obj.get("order") or []
        siparis_no = obj.get("orderReference") or (kalemler[0].get("orderReference") if kalemler else "")
        if not siparis_no:
            raise SaglayiciHatasi("eSIM Go sipariş referansı vermedi.")

        esimler = kalemler[0].get("esims") if kalemler else None
        profil = self._profil_kur(esimler[0]) if esimler else None
        return siparis_no, profil

    def profil_getir(self, saglayici_siparis_no):
        obj = self._istek(f"/orders/{saglayici_siparis_no}")
        kalemler = obj.get("order") or []
        esimler = kalemler[0].get("esims") if kalemler else None
        if not esimler:
            return None
        esim = esimler[0]
        if not esim.get("matchingId"):
            # Sipariş kaydında yoksa eSIM kaydından tamamla.
            esim = self._istek(f"/esims/{esim.get('iccid')}")
        return self._profil_kur(esim)

    @staticmethod
    def _profil_kur(esim):
        smdp = (esim.get("smdpAddress") or "").replace("https://", "").replace("http://", "").strip("/")
        eslesme = esim.get("matchingId") or ""
        if not smdp or not eslesme:
            return None
        return ProfilVerisi(
            esim_no=esim.get("iccid") or "",
            iccid=esim.get("iccid") or "",
            ac=f"LPA:1${smdp}${eslesme}",
            durum=esim.get("profileStatus") or "",
        )

    def iptal_et(self, esim_no, *, iccid="", paket_kodu=""):
        iccid = iccid or esim_no
        if not iccid or not paket_kodu:
            raise SaglayiciHatasi("eSIM Go iptali için ICCID ve paket kodu gerekir.")
        self._istek(
            f"/esims/{iccid}/bundles/{paket_kodu}?refundToBalance=true", yontem="DELETE"
        )
