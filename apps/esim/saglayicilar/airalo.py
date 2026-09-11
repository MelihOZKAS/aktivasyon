"""Airalo Partner API adaptörü — belgeden yazıldı, canlı anahtarla denenmedi.

Belge: https://developers.partners.airalo.com — OAuth2 istemci kimliği:
`POST /v2/token` (form) ile jeton alınır, sonra `Authorization: Bearer`.
Jeton uçlarında dakikada 3 istek sınırı var; jeton `Saglayici`
kaydında saklanır ve süresi dolmadan yeniden alınmaz. Panelde *Erişim Kodu*
= client_id, *Gizli Anahtar* = client_secret.

Sandbox ve üretim **aynı adreste**; hangisi olduğu hesabın modudur.
Yanıtlar `{"data": ..., "meta": {"message": ...}}` zarfında. Toptan fiyat
`net_price` (USD), hacim MB (`amount`), süre gün (`day`).

Sipariş eşzamanlıdır: `POST /v2/orders` profili (`sims[]`) hemen döndürür.
**İade** anında değildir: `POST /v2/refund` talebi Airalo destek ekibi elle
inceler. Bu yüzden `iptal_et` talebi iletir ama **hata yükseltir** — bizim
sistem bayiye parayı otomatik iade etmesin; Airalo onaylayınca yönetici
cüzdan işlemiyle elle iade eder.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.esim.saglayicilar import Adaptor, PaketVerisi, ProfilVerisi, SaglayiciHatasi
from apps.esim.saglayicilar.http import json_istek

ADRES = "https://partners-api.airalo.com"
SAYFA_BOYU = 100
MB = 1024**2
# Belge jetonun ömrü konusunda tutarsız (24 saat / 1 yıl); güvenli tarafta
# kalınır, 401 gelirse zaten yenilenir.
JETON_OMRU = timedelta(hours=20)


class Airalo(Adaptor):
    kod = "airalo"
    ad = "Airalo"
    denenmedi = True

    # -- Kimlik ----------------------------------------------------------

    def _jeton(self, yenile=False):
        s = self.saglayici
        if not yenile and s.oturum_anahtari and s.oturum_bitis and s.oturum_bitis > timezone.now():
            return s.oturum_anahtari

        durum, sonuc = json_istek(
            ADRES + "/v2/token",
            yontem="POST",
            form=True,
            govde={
                "client_id": s.erisim_kodu,
                "client_secret": s.gizli_anahtar,
                "grant_type": "client_credentials",
            },
            saglayici_adi=self.ad,
        )
        veri = (sonuc.get("data") or {}) if isinstance(sonuc, dict) else {}
        jeton = veri.get("access_token")
        if durum >= 400 or not jeton:
            raise SaglayiciHatasi(self._mesaj(sonuc) or f"Airalo jeton alınamadı (HTTP {durum})", str(durum))

        s.oturum_anahtari = jeton
        s.oturum_bitis = timezone.now() + JETON_OMRU
        s.save(update_fields=["oturum_anahtari", "oturum_bitis"])
        return jeton

    @staticmethod
    def _mesaj(sonuc):
        if not isinstance(sonuc, dict):
            return ""
        meta = sonuc.get("meta") or {}
        mesaj = meta.get("message") or sonuc.get("message") or ""
        veri = sonuc.get("data")
        if isinstance(veri, dict) and mesaj and "invalid" in mesaj:
            # Doğrulama hatası: alan adıyla açıklama `data` içinde.
            ayrinti = "; ".join(f"{k}: {v}" for k, v in veri.items() if isinstance(v, str))
            if ayrinti:
                mesaj = f"{mesaj} ({ayrinti})"
        return mesaj

    def _istek(self, yol, *, yontem="GET", govde=None, _tekrar=True):
        durum, sonuc = json_istek(
            ADRES + yol,
            yontem=yontem,
            govde=govde,
            basliklar={"Authorization": f"Bearer {self._jeton()}"},
            saglayici_adi=self.ad,
        )
        if durum == 401 and _tekrar:
            self._jeton(yenile=True)
            return self._istek(yol, yontem=yontem, govde=govde, _tekrar=False)
        if durum >= 400:
            raise SaglayiciHatasi(self._mesaj(sonuc) or f"Airalo HTTP {durum}", str(durum))
        return sonuc if isinstance(sonuc, dict) else {}

    # -- Arayüz ----------------------------------------------------------

    def paketleri_getir(self):
        paketler = []
        for tur in ("local", "global"):
            sayfa = 1
            while True:
                sonuc = self._istek(f"/v2/packages?filter[type]={tur}&limit={SAYFA_BOYU}&page={sayfa}")
                for bolge in sonuc.get("data") or []:
                    paketler.extend(self._bolge_paketleri(bolge))
                meta = sonuc.get("meta") or {}
                son = meta.get("last_page") or 1
                if sayfa >= son or not sonuc.get("data"):
                    break
                sayfa += 1
        return paketler

    @staticmethod
    def _bolge_paketleri(bolge):
        """Ülke/bölge → operatörler → paketler; ülkeler operatörden ya da bölgeden okunur."""
        sonuc = []
        bolge_kodu = (bolge.get("country_code") or "").upper()
        for operator in bolge.get("operators") or []:
            ulkeler = [
                (u.get("country_code") or "").upper()
                for u in operator.get("countries") or []
                if u.get("country_code")
            ]
            if not ulkeler and bolge_kodu:
                ulkeler = [bolge_kodu]
            if not ulkeler:
                continue
            adlar = {
                (u.get("country_code") or "").upper(): u.get("title", "")
                for u in operator.get("countries") or []
            }
            if bolge_kodu and bolge.get("title"):
                adlar.setdefault(bolge_kodu, bolge["title"])

            for paket in operator.get("packages") or []:
                if paket.get("is_unlimited") or (paket.get("type") or "data") != "data":
                    continue
                fiyat = paket.get("net_price")
                if fiyat is None:
                    fiyatlar = (paket.get("prices") or {}).get("net_price") or {}
                    fiyat = fiyatlar.get("USD")
                if fiyat is None or not paket.get("id"):
                    continue
                try:
                    fiyat = Decimal(str(fiyat))
                except InvalidOperation:
                    continue
                sonuc.append(
                    PaketVerisi(
                        kod=paket["id"],
                        ad=f"{operator.get('title') or bolge.get('title') or ''} {paket.get('title') or ''}".strip(),
                        ulkeler=ulkeler,
                        hacim_bayt=int(paket.get("amount") or 0) * MB,
                        sure_gun=int(paket.get("day") or 0),
                        alis_usd=fiyat,
                        aciklama=paket.get("short_info") or "",
                        ulke_adlari=adlar,
                    )
                )
        return sonuc

    def bakiye(self):
        sonuc = self._istek("/v2/balance")
        veri = sonuc.get("data") or {}
        bakiyeler = veri.get("balances") or veri
        kullanilabilir = (
            bakiyeler.get("availableBalance")
            or bakiyeler.get("available_balance")
            or bakiyeler.get("balance")
            or {}
        )
        tutar = kullanilabilir.get("amount") if isinstance(kullanilabilir, dict) else kullanilabilir
        try:
            return Decimal(str(tutar))
        except (InvalidOperation, TypeError):
            raise SaglayiciHatasi("Airalo bakiyesi okunamadı; belge bu ucu net vermiyor.")

    def siparis_ver(self, paket_kodu, islem_no, alis_usd):
        sonuc = self._istek(
            "/v2/orders",
            yontem="POST",
            govde={
                "quantity": "1",
                "package_id": paket_kodu,
                "type": "sim",
                # Kendi anahtarımız açıklamada durur; Airalo'da tekil anahtar yok.
                "description": islem_no,
            },
        )
        veri = sonuc.get("data") or {}
        siparis_no = str(veri.get("id") or veri.get("code") or "")
        if not siparis_no:
            raise SaglayiciHatasi("Airalo sipariş numarası vermedi.")
        simler = veri.get("sims") or []
        profil = self._profil_kur(simler[0]) if simler else None
        return siparis_no, profil

    def profil_getir(self, saglayici_siparis_no):
        # Sipariş eşzamanlı; buraya yalnızca ilk yanıt kaydedilemediyse düşülür.
        sonuc = self._istek(f"/v2/orders/{saglayici_siparis_no}")
        veri = sonuc.get("data") or {}
        simler = veri.get("sims") or []
        return self._profil_kur(simler[0]) if simler else None

    @staticmethod
    def _profil_kur(sim):
        ac = sim.get("qrcode") or ""
        if not ac.startswith("LPA:") and sim.get("lpa") and sim.get("matching_id"):
            ac = f"LPA:1${sim['lpa']}${sim['matching_id']}"
        if not ac:
            return None
        return ProfilVerisi(
            esim_no=sim.get("iccid") or "",
            iccid=sim.get("iccid") or "",
            ac=ac,
            qr_url=sim.get("qrcode_url") or "",
            apn=sim.get("apn_value") or "",
        )

    def iptal_et(self, esim_no, *, iccid="", paket_kodu=""):
        iccid = iccid or esim_no
        if not iccid:
            raise SaglayiciHatasi("Airalo iadesi için ICCID gerekir.")
        sonuc = self._istek(
            "/v2/refund",
            yontem="POST",
            govde={"iccids": [iccid], "reason": "OTHERS", "notes": "Bayi iptal etti; profil kurulmadı."},
        )
        talep = (sonuc.get("data") or {}).get("refund_id", "")
        # Talep kabul edildi ama iade Airalo'nun incelemesine bağlı; bayiye
        # otomatik iade yapılmasın diye hata olarak döner.
        raise SaglayiciHatasi(
            f"İade talebi Airalo'ya iletildi (talep {talep or '?'}); Airalo onaylayınca "
            "bayiye iadeyi cüzdan işlemiyle elle yapın.",
            "202",
        )
