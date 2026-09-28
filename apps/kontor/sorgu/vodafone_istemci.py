"""
Vodafone Kolay Paket ve Numara Sorgu Servisi
vodafone.txt içerisindeki request akışına uygun olarak hazırlanmıştır.
Django projelerinde import edilerek veya terminalden doğrudan çalıştırılabilir.
"""

import json
import re
from typing import Any, Dict, List, Optional
import requests

BASE_URL = "https://m.vodafone.com.tr/maltgtwaycbu/api"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6",
    "Origin": "https://www.vodafone.com.tr",
    "Referer": "https://www.vodafone.com.tr/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def format_msisdn(phone: str) -> str:
    """
    Telefon numarasını 10 haneli standart formata (örn: 5461234567) getirir.
    """
    cleaned = re.sub(r"\D", "", str(phone))
    if cleaned.startswith("90") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return cleaned


class VodafoneSorgu:
    """
    Vodafone numara doğrulama, maskelenmiş isim ve kolay paket sorgulama sınıfı.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get_masked_user_name(self, msisdn: str) -> Dict[str, Any]:
        """
        1. Adım: Numaranın kime ait olduğunu (maskeli isim) sorgular.
        """
        msisdn = format_msisdn(msisdn)
        url = f"{BASE_URL}?method=getMaskedUserName"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = self.session.post(
            url,
            data={"msisdn": msisdn},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_public_token(self, msisdn: str, token_type: int = 3) -> Dict[str, Any]:
        """
        2. Adım: Paketleri çekmek için gerekli publicToken değerini alır.
        """
        msisdn = format_msisdn(msisdn)
        url = f"{BASE_URL}?method=getPublicToken&msisdn={msisdn}&type={token_type}"
        headers = {"Content-Length": "0"}

        response = self.session.post(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_kolay_packs(self, public_token: str) -> Dict[str, Any]:
        """
        3. Adım: Public token kullanarak hatta yüklenebilecek kolay paketleri listeler.
        """
        url = f"{BASE_URL}?method=getKolayPacks&publicToken={public_token}"
        headers = {"Content-Length": "0"}

        response = self.session.post(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_filtering_parameters(self, public_token: str) -> Dict[str, Any]:
        """
        Filtreleme kriterlerini (kategoriler, geçerlilik süreleri vs.) sorgular.
        """
        url = f"{BASE_URL}?method=getFilteringParameters&publicToken={public_token}"
        headers = {"Content-Length": "0"}

        response = self.session.post(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def sorgula(self, msisdn: str) -> Dict[str, Any]:
        """
        Tek adımda tüm süreci yürütür:
        1. Maskeli isim alma
        2. PublicToken alma
        3. Kolay paketleri listeleme
        """
        phone = format_msisdn(msisdn)
        sonuc: Dict[str, Any] = {
            "success": False,
            "msisdn": phone,
            "masked_name": None,
            "public_token": None,
            "categories": [],
            "packages": [],
            "error": None,
        }

        try:
            # 1. Maskeli İsim
            name_resp = self.get_masked_user_name(phone)
            res_meta = name_resp.get("result", {})
            if res_meta.get("result") != "SUCCESS":
                sonuc["error"] = res_meta.get("resultDesc") or "Numara sorgulanamadı."
                return sonuc

            sonuc["masked_name"] = name_resp.get("maskedUserName", "").strip()

            # 2. Token
            token_resp = self.get_public_token(phone)
            token = token_resp.get("publicToken")
            if not token:
                sonuc["error"] = "Yetkilendirme anahtarı (publicToken) alınamadı."
                return sonuc
            sonuc["public_token"] = token

            # 3. Paketler
            packs_resp = self.get_kolay_packs(token)
            categories = packs_resp.get("kolayPackCategory", [])
            sonuc["categories"] = categories

            # Paketleri düz liste olarak da çıkartalım
            duz_paketler: List[Dict[str, Any]] = []
            for cat in categories:
                cat_desc = cat.get("description", "")
                for pack in cat.get("kolayPacks", []):
                    fee = pack.get("usageFee", {})
                    duz_paketler.append(
                        {
                            "category": cat_desc,
                            "id": pack.get("id"),
                            "name": pack.get("description"),
                            "price": fee.get("string") or f"{fee.get('value')} {fee.get('unit')}",
                            "price_value": fee.get("value"),
                            "detail": pack.get("detail"),
                            "tag": pack.get("tag"),
                        }
                    )

            sonuc["packages"] = duz_paketler
            sonuc["success"] = True
            return sonuc

        except requests.RequestException as e:
            sonuc["error"] = f"İstek hatası: {str(e)}"
            return sonuc
        except Exception as e:
            sonuc["error"] = f"Beklenmeyen hata: {str(e)}"
            return sonuc


# Django view veya servis kullanımı için pratik fonksiyon
def vodafone_paket_sorgula(msisdn: str) -> Dict[str, Any]:
    """
    Django projelerinden doğrudan çağrılabilecek fonksiyon:
    from vodafone_sorgu import vodafone_paket_sorgula
    veri = vodafone_paket_sorgula('5XXXXXXXXX')
    """
    client = VodafoneSorgu()
    return client.sorgula(msisdn)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit("Kullanım: python vodafone_istemci.py 5XXXXXXXXX")
    numara = sys.argv[1]
    print(f"[*] Vodafone sorgulanıyor: {numara}...\n")

    sonuc = vodafone_paket_sorgula(numara)

    if sonuc["success"]:
        print(f"[+] Hat Sahibi: {sonuc['masked_name']}")
        print(f"[+] Public Token: {sonuc['public_token']}")
        print(f"[+] Toplam Paket Sayısı: {len(sonuc['packages'])}\n")
        print("--- Örnek İlk 5 Paket ---")
        for p in sonuc["packages"][:5]:
            print(f"- [{p['price']}] {p['name']} ({p['detail']})")
    else:
        print(f"[-] Hata: {sonuc['error']}")
