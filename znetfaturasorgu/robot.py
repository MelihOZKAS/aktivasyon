# -*- coding: utf-8 -*-
"""Znet fatura sorgu robotu — çekirdek.

Ne yapar: gerçek bir Chromium'da, senin açtığın oturumla kontorbizde fatura
sayfasını sürer, bir kurumun sorgu formuna numarayı yazıp **gerçek Sorgula
düğmesine basar** ve dönen fatura listesini ayrıştırır. Jeton (znet_token,
Turnstile) taklit edilmez; sayfanın kendi JS'i üretir, biz yalnızca DOM'u
sürüp sonucu okuruz.

Oturum iki şekilde verilir:
  • Kalıcı profil (laptop): `giris` ile bir kez elle girilir, `oturum/`
    klasöründe saklanır. Sonraki sorgular bu profili kullanır.
  • Test için: ZNET_SESSION ortam değişkenine PHPSESSID konursa onunla
    bağlanır (profil gerekmez).

CLI:
  python robot.py giris                     # tarayıcı açılır, elle giriş yap
  python robot.py katalog                   # siteyi tarar, kurumlar.json'a yazar
  python robot.py sorgu <kurum> <numara>    # kurum adı (ör. vodafone) + numara
"""

import base64
import json
import os
import pathlib
import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BURASI = pathlib.Path(__file__).resolve().parent
OTURUM = BURASI / "oturum"
# Kurum listesi (id → token, numara kuralı). Yalnızca elle yenilenir
# (`katalog.bat`); robot sorguda token'ı buradan okur, siteyi taramaz.
KURUMLAR = BURASI / "kurumlar.json"

SITE = "https://bayi.kontorbizde.com/"
FATURA = "https://bayi.kontorbizde.com/Fatura/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

# Kategori kodları sayfadaki düğmelerden gelir; bu liste onların kapsamı.
KATEGORILER = [1, 2, 3, 4, 5, 6, 15, 16, 17]

ETIKET = re.compile(r"<[^>]+>")

# Kurumun TEKİL id'si: api_adi tekil değil (171 birden çok "TL Yükle"de
# tekrar ediyor), o yüzden kendi id'mizi kurum adından türetiyoruz. Django
# bu id ile gönderir, robot id→token çevirip sorgular. Her yerde aynı hesap.
import unicodedata

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def kurum_id(ad):
    # Önce Türkçe harfleri çevir, sonra küçült: "ONLİNE" → "online"
    # (lower() İ'yi birleşik noktaya çeviriyor, sıra önemli).
    s = ad.strip().translate(_TR).lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


# ---------------------------------------------------------------- bağlantı
def baglan(p, headless=True):
    """Oturumlu bir tarayıcı context'i döndürür.

    ZNET_SESSION varsa onunla (test), yoksa kalıcı profille (laptop).
    """
    ses = os.environ.get("ZNET_SESSION")
    if ses:
        tarayici = p.chromium.launch(headless=headless)
        ctx = tarayici.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "PHPSESSID", "value": ses,
                          "domain": "bayi.kontorbizde.com", "path": "/"}])
        return ctx
    return p.chromium.launch_persistent_context(
        str(OTURUM), headless=headless, user_agent=UA,
        viewport={"width": 1280, "height": 900},
    )


def _girisli_mi(sayfa):
    """Fatura sayfası açıldıysa ve kategori düğmeleri geldiyse oturum canlıdır."""
    return sayfa.query_selector("input[onclick*='Goster=Kurumlar']") is not None


def _ubil(sayfa):
    """Kategori düğmelerinin kullandığı ubil değeri (sayfadan okunur)."""
    m = re.search(r"ubil=([A-Za-z0-9+/=]+)", sayfa.content())
    return m.group(1) if m else "NTh8fGV8fDB8fHxofA=="


# ------------------------------------------------------------------ katalog
def token_coz(token):
    """Kurum token'ını (base64) kurum bilgisine ve alan tanımına çevirir."""
    ham = base64.b64decode(token).decode("utf-8", "replace").lstrip("&")
    veri = {}
    for parca in ham.split("&"):
        if "=" in parca:
            k, v = parca.split("=", 1)
            veri[k] = v
    bilgi = {
        "id": veri.get("id", ""),
        "api_adi": veri.get("api_adi", ""),
        "kurum_adi": veri.get("kurum_adi", ""),
        "aktif": veri.get("api_durum", "") == "a",
        "aciklama": veri.get("api_aciklama", ""),
        "alanlar": [],
    }
    xml = urllib.parse.unquote_plus(veri.get("xml", ""))
    for blok in re.findall(r"\{(.*?)\}", xml):
        parcalar = blok.split("#")
        alan = {"etiket": parcalar[0].strip()}
        for pr in parcalar[1:]:
            if "=" in pr:
                k, v = pr.split("=", 1)
                alan[k.strip()] = v.strip()
        bilgi["alanlar"].append(alan)
    return bilgi


def katalog(ctx):
    """Bütün kategorilerdeki kurumları, token ve alan tanımlarıyla toplar."""
    sayfa = ctx.pages[0] if ctx.pages else ctx.new_page()
    sayfa.goto(FATURA, wait_until="domcontentloaded")
    sayfa.wait_for_timeout(600)
    if not _girisli_mi(sayfa):
        raise RuntimeError("Oturum yok/düşmüş. Önce 'python robot.py giris'.")
    ubil = _ubil(sayfa)
    sonuc = []
    for cat in KATEGORILER:
        sayfa.evaluate(
            "([c,u])=>post_ajax('Fatura/bilgi_api.php?Goster=Kurumlar&cat='+c+'&','ubil='+u,'ajdiv')",
            [cat, ubil],
        )
        sayfa.wait_for_timeout(900)
        aj = sayfa.inner_html("#ajdiv") if sayfa.query_selector("#ajdiv") else ""
        for tok in re.findall(r"token=([A-Za-z0-9+/=]+)", aj):
            try:
                bilgi = token_coz(tok)
            except Exception:  # noqa: BLE001
                continue
            if not bilgi["kurum_adi"]:
                continue
            bilgi["id"] = kurum_id(bilgi["kurum_adi"])
            bilgi["kategori"] = cat
            bilgi["token"] = tok
            sonuc.append(bilgi)
    # id çakışırsa (aynı ada iki kurum) sona sıra numarası ekle — tekil kalsın.
    gorulen = {}
    for k in sonuc:
        n = gorulen.get(k["id"], 0) + 1
        gorulen[k["id"]] = n
        if n > 1:
            k["id"] = f"{k['id']}-{n}"
    return sonuc


def _tahmini_sorgusuz(ad):
    a = ad.lower()
    return any(x in a for x in ("tl yükle", "tl ile yükle", "tc ile", "tc i̇le", "plaka"))


def katalog_temiz(ham):
    """Ham katalogu kurumlar.json biçimine indirger (Django da bunu okur)."""
    temiz = []
    for k in ham:
        alan = k["alanlar"][0] if k["alanlar"] else {}
        temiz.append({
            "id": k["id"],
            "kurum_adi": k["kurum_adi"],
            "api_adi": k["api_adi"],
            "kategori": k["kategori"],
            "aktif": k["aktif"],
            "token": k["token"],
            "alan_etiketi": alan.get("etiket", ""),
            "min_hane": int(alan["min"]) if str(alan.get("min", "")).isdigit() else None,
            "max_hane": int(alan["max"]) if str(alan.get("max", "")).isdigit() else None,
            "sadece_rakam": alan.get("tur") == "int",
            "tahmini_sorgusuz": _tahmini_sorgusuz(k["kurum_adi"]),
            "aciklama": k["aciklama"],
        })
    temiz.sort(key=lambda x: (x["kategori"], x["kurum_adi"]))
    return temiz


def katalog_kaydet(ctx):
    """Siteyi tarar, kurumlar.json'u yazar ve listeyi döndürür."""
    temiz = katalog_temiz(katalog(ctx))
    if not temiz:
        raise RuntimeError("Katalog boş geldi; oturum düşmüş olabilir. Önce giris.bat.")
    KURUMLAR.write_text(json.dumps(temiz, ensure_ascii=False, indent=2), encoding="utf-8")
    return temiz


def kurumlari_oku():
    """kurumlar.json'daki liste; dosya yoksa boş."""
    if not KURUMLAR.exists():
        return []
    return json.loads(KURUMLAR.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- sorgu
def _temiz(s):
    return ETIKET.sub("", s).replace("&nbsp;", " ").strip()


def _tutar(s):
    m = re.search(r"([\d.]+,\d{2})", s or "")
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def cevabi_coz(html):
    """sorgu_api.php cevabındaki fatura listesini yapıya çevirir."""
    def span(etiket):
        m = re.search(etiket + r":\s*<span[^>]*>(.*?)</span>", html, re.S)
        return _temiz(m.group(1)) if m else ""

    sonuc = {
        "durum": "sonuc_yok",   # bulundu | borc_yok | hata | sonuc_yok
        "mesaj": "",
        "abone_adi": span("Abone Adı"),
        "tesisat_no": span("Tesisat No"),
        "kurum": span("Kurum"),
        "odenmesi_gereken": None,
        "faturalar": [],
    }
    m = re.search(r"id='tamami_toplami'\s+value='([\d.]+)'", html)
    if m:
        sonuc["odenmesi_gereken"] = float(m.group(1))
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        if "name='fatura_" not in tr:
            continue
        td = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(td) < 7:
            continue
        tok = re.search(r"name='fatura_\d+'[^>]*value='([^']+)'", tr)
        bedeli = re.search(r"([\d.]+,\d{2})", td[3])
        sonuc["faturalar"].append({
            "fatura_no": _temiz(td[1]),
            "son_odeme_tarihi": _temiz(td[2]),
            "fatura_bedeli": bedeli.group(1) if bedeli else "",
            "fatura_bedeli_tl": _tutar(td[3]),
            "g_hizmet_bedeli": _tutar(td[4]),
            "islem_bedeli": _tutar(td[5]),
            "toplam_tutar": _tutar(td[6]),
            "odeme_token": tok.group(1) if tok else "",
        })

    # Durum: tablo varsa bulundu; sağlayıcı "ZNET=n-HATA=..." dediyse hata
    # (ör. gece bloğu: "23:00-06:00 arasında tahsilat yapılamaz"); ikisi de
    # yoksa borç/sonuç yok. Mesaj her hâlde bayiye gösterilebilir.
    duz = _temiz(html)
    hata = re.search(r"ZNET=\d+-HATA=(.+?)(?:<|$)", duz)
    if sonuc["faturalar"]:
        sonuc["durum"] = "bulundu"
    elif hata:
        sonuc["durum"] = "hata"
        # Mesaja sağlayıcının JS'i bulaşabiliyor; ilk script izinde kes.
        mesaj = re.split(r"document\.|\$\(|function\s", hata.group(1))[0]
        sonuc["mesaj"] = mesaj.strip().rstrip(".") or "Sağlayıcı hatası."
    else:
        sonuc["durum"] = "borc_yok"
        sonuc["mesaj"] = "Bu numara/aboneye ait ödenecek fatura bulunamadı."
    return sonuc


def sorgula(ctx, token, numara):
    """Verilen kurum token'ıyla numarayı sorgular, ayrıştırılmış sonucu döndürür.

    Her çağrı kendi sayfasını açıp kapatır: işçi döngüsünde aynı sayfaya
    dinleyici birikmesin, bir sorgunun cevabı diğerine karışmasın.
    """
    sayfa = ctx.new_page()
    try:
        sayfa.goto(FATURA, wait_until="domcontentloaded")
        sayfa.wait_for_timeout(600)
        if not _girisli_mi(sayfa):
            raise RuntimeError("Oturum yok/düşmüş. Önce 'python robot.py giris'.")

        ham_cevap = {}

        def yakala(cevap):
            if "sorgu_api.php" in cevap.url:
                try:
                    ham_cevap["govde"] = cevap.text()
                except Exception:  # noqa: BLE001
                    pass

        sayfa.on("response", yakala)

        # Kurum token'ı kategoriden bağımsız çalışır: doğrudan Tahsilat'ı açar.
        sayfa.evaluate(
            "(tok)=>post_ajax('Fatura/bilgi_api.php?Goster=Tahsilat&','token='+tok,'ajdiv')",
            token,
        )
        sayfa.wait_for_timeout(1200)
        if not sayfa.query_selector("#sorgu_input_0"):
            raise RuntimeError("Sorgu formu açılmadı (kurum token'ı geçersiz olabilir).")
        sayfa.fill("#sorgu_input_0", str(numara))
        basildi = sayfa.evaluate(
            """()=>{const c=[...document.querySelectorAll('input,button,a,div,span')];
            const el=c.find(e=>((e.value||'')+(e.textContent||'')).toLowerCase().includes('sorgula')
              && (e.onclick||e.getAttribute('onclick')));
            if(el){el.click();return true;} return false;}"""
        )
        if not basildi:
            raise RuntimeError("Sorgula düğmesi bulunamadı.")
        for _ in range(25):
            sayfa.wait_for_timeout(1000)
            if "govde" in ham_cevap:
                break
        if "govde" not in ham_cevap:
            raise RuntimeError("Sorgu cevabı gelmedi (zaman aşımı).")
        cozum = cevabi_coz(ham_cevap["govde"])
        cozum["_ham_uzunluk"] = len(ham_cevap["govde"])
        return cozum
    finally:
        sayfa.close()


# --------------------------------------------------------------------- CLI
def _giris():
    print("Tarayıcı açılıyor. Siteye gir, ekrandaki resmi çöz, panel açılınca")
    print("buraya dönüp Enter'a bas. Oturum 'oturum/' klasöründe saklanacak.")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(OTURUM), headless=False, user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        sayfa = ctx.pages[0] if ctx.pages else ctx.new_page()
        sayfa.goto(SITE, wait_until="domcontentloaded")
        input("Giriş bitince Enter > ")
        sayfa.goto(FATURA, wait_until="domcontentloaded")
        sayfa.wait_for_timeout(1000)
        print("Oturum hazır." if _girisli_mi(sayfa) else "DİKKAT: hâlâ giriş gerekli görünüyor.")
        ctx.close()


def _kurum_bul(ctx, aranan):
    # Önce yerel liste; dosya yoksa site bir kez taranır.
    kat = kurumlari_oku() or katalog_kaydet(ctx)
    for k in kat:                       # önce tekil id ile tam eşleşme
        if k["id"] == aranan.lower():
            return k
    for k in kat:                       # sonra kurum adında geçiyorsa
        if aranan.lower() in k["kurum_adi"].lower():
            return k
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    komut = sys.argv[1]
    if komut == "giris":
        _giris()
        return
    with sync_playwright() as p:
        ctx = baglan(p, headless=True)
        try:
            if komut == "katalog":
                liste = katalog_kaydet(ctx)
                for k in liste:
                    print(f"  {k['id']:<40} {k['kurum_adi']}")
                print(f"\n{len(liste)} kurum kurumlar.json'a yazıldı.")
            elif komut == "sorgu":
                aranan, numara = sys.argv[2], sys.argv[3]
                if len(aranan) > 40:            # token verilmiş
                    token = aranan
                else:                           # kurum adı verilmiş
                    k = _kurum_bul(ctx, aranan)
                    if not k:
                        print(f"Kurum bulunamadı: {aranan}")
                        return
                    token = k["token"]
                print(json.dumps(sorgula(ctx, token, numara), ensure_ascii=False, indent=2))
            else:
                print(__doc__)
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
