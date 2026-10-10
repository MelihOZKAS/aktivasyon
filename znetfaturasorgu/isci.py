# -*- coding: utf-8 -*-
"""Fatura işçisi — Django kuyruğundan iş çekip sorgular.

Sözleşme: DJANGO_API.md. Tek tarayıcı açık tutulur (her sorguda yeniden
açılmaz), oturum `oturum/` profilinde yaşar. Aynı numara iki işçiye gitmez:
işi veren uç atomik kilitler, işçi sadece "bana iş ver" der.

Kurum listesi (id → token) `kurumlar.json`'dan okunur, site sürekli
taranmaz. Yalnızca elle yenilenir: `python isci.py katalog` (katalog.bat).
Çalışan işçi dosyanın değiştiğini görür, yeniden başlatmaya gerek yoktur.

Ayar: ayar.json (yönetim panelinde Sorgu Robotları → Yeni anahtar).
Çalıştır: python isci.py            (isci.bat)
          python isci.py katalog    (katalog.bat)
"""

import datetime as dt
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

import robot

BURASI = pathlib.Path(__file__).resolve().parent
AYAR = BURASI / "ayar.json"


def ayarlar():
    if not AYAR.exists():
        raise SystemExit("ayar.json yok. Yönetim panelinde Sorgu Robotları → Yeni anahtar.")
    return json.loads(AYAR.read_text(encoding="utf-8"))


class _YonlendirmeYok(urllib.request.HTTPRedirectHandler):
    """Yönlendirme izlenmez: urllib yönlendirmede POST'u GET'e çevirip gövdeyi
    düşürüyor, sonuç Django'ya sessizce hiç ulaşmazdı. Adres yanlışsa
    (ör. www'siz) açıkça söylenir."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(
            f"django_url yönlendiriliyor → {newurl}. ayar.json'da adresi bununla değiştir."
        )


_ACICI = urllib.request.build_opener(_YonlendirmeYok)


def _ipucu(hata):
    """HTTP hatasının terminalde ne yapılacağını söyleyen kısa açıklaması."""
    metin = str(hata)
    if "401" in metin:
        return "→ api_key yanlış ya da robot panelde kapalı (Fatura → Sorgu Robotları → Yeni anahtar)"
    if "403" in metin:
        return "→ sunucunun önündeki güvenlik katmanı isteği kesti"
    return ""


def _istek(url, api_key, govde=None):
    veri = json.dumps(govde).encode() if govde is not None else None
    r = urllib.request.Request(
        url, data=veri, method="POST" if veri else "GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare Python'un varsayılan kimliğini ("Python-urllib") bot
            # sayıp "error code: 1010" ile 403 veriyor; istek Django'ya hiç
            # ulaşmıyordu. Robot kendi adıyla gider.
            "User-Agent": "FaturaRobotu/1.0",
        },
    )
    with _ACICI.open(r, timeout=20) as cevap:
        govde = cevap.read().decode("utf-8")
        return json.loads(govde) if govde.strip() else {}


def calisma_saatleri(metin):
    """"08:00-23:00" → (time(8, 0), time(23, 0))."""
    bas, bit = (parca.strip() for parca in metin.split("-", 1))
    return tuple(dt.time(*map(int, saat.split(":"))) for saat in (bas, bit))


def mesai_icinde(simdi, bas, bit):
    """Gece yarısını aşan aralık da olur ("22:00-06:00")."""
    t = simdi.time()
    return bas <= t < bit if bas <= bit else (t >= bas or t < bit)


def _harita(kurumlar):
    return {k["id"]: k["token"] for k in kurumlar if k.get("token")}


def _degisme_zamani():
    return robot.KURUMLAR.stat().st_mtime if robot.KURUMLAR.exists() else 0


def katalog_komutu():
    """Siteyi tarar, kurumlar.json'u yazar; ayar.json varsa Django'ya da yollar."""
    print("Kurum listesi taranıyor…")
    with sync_playwright() as p:
        ctx = robot.baglan(p, headless=True)
        try:
            kurumlar = robot.katalog_kaydet(ctx)
        finally:
            ctx.close()
    print(f"{len(kurumlar)} kurum kurumlar.json'a yazıldı.")
    if not AYAR.exists():
        print("ayar.json yok; Django'ya yollanmadı.")
        return
    a = ayarlar()
    try:
        cevap = _istek(f"{a['django_url'].rstrip('/')}/fatura/robot/katalog/", a["api_key"],
                       {"robot": a.get("robot_adi", "robot"), "kurumlar": kurumlar})
        print(f"Django: {cevap.get('eklenen', 0)} yeni kurum (kapalı açıldı), "
              f"{cevap.get('guncellenen', 0)} kuralı güncellendi.")
    except Exception as hata:  # noqa: BLE001
        print("Django'ya yollanamadı:", hata)


def main():
    a = ayarlar()
    taban = a["django_url"].rstrip("/")
    anahtar = a["api_key"]
    ad = a.get("robot_adi", "robot")
    aralik = a.get("aralik_sn", 5)
    # Çalışma saatleri dışında Django'ya hiç istek atılmaz; robot dakikada
    # bir yalnızca kendi saatine bakar. Saatler nabızla Django'ya da gider:
    # bayi mesai dışında "08:00–23:00 arasında" görür, "sistem bağlı değil" değil.
    saatler = a.get("calisma_saatleri", "08:00-23:00")
    bas, bit = calisma_saatleri(saatler)

    # Nabız yalnızca durum değişince ya da dakikada bir gider: her "iş var
    # mı?" isteği sunucuda zaten nabız sayılıyor (çevrimiçi göstergesi ondan
    # beslenir). Bu istek yalnızca meşgul/oturum düştü bilgisini taşır.
    son_nabiz = {"durum": None, "zaman": 0.0}

    def nabiz(durum, oturum):
        anahtar_durum = (durum, oturum)
        if anahtar_durum == son_nabiz["durum"] and time.time() - son_nabiz["zaman"] < 60:
            return
        try:
            _istek(f"{taban}/fatura/robot/kalp/", anahtar,
                   {"robot": ad, "durum": durum, "oturum": oturum, "mesai": saatler})
            son_nabiz.update(durum=anahtar_durum, zaman=time.time())
        except Exception:  # noqa: BLE001
            pass

    def basarisiz(talep_id, hata):
        try:
            _istek(f"{taban}/fatura/robot/sonuc/", anahtar,
                   {"talep_id": talep_id, "robot": ad, "basarisiz": True, "hata": str(hata)[:300]})
        except Exception:  # noqa: BLE001
            pass

    print(f"[{ad}] işçi başladı. Django: {taban} · {aralik} sn aralık · çalışma {saatler}")
    with sync_playwright() as p:
        ctx = robot.baglan(p, headless=True)
        kurumlar = robot.kurumlari_oku()
        if not kurumlar:
            print("  kurumlar.json yok; site bir kez taranıyor…")
            kurumlar = robot.katalog_kaydet(ctx)
        harita = _harita(kurumlar)
        dosya_zamani = _degisme_zamani()
        print(f"  {len(harita)} kurum yüklendi.")

        uyuyor = False
        while True:
            if not mesai_icinde(dt.datetime.now(), bas, bit):
                if not uyuyor:
                    print(f"  mesai dışı ({saatler}): {bas:%H:%M}'e kadar Django'ya istek atılmıyor")
                    uyuyor = True
                time.sleep(60)
                continue
            if uyuyor:
                print("  mesai başladı, işler alınıyor")
                uyuyor = False
                son_nabiz["durum"] = None   # ilk turda nabız hemen gitsin

            # katalog.bat dosyayı yenilediyse yeni listeyi al (yeniden başlatmadan).
            if _degisme_zamani() != dosya_zamani:
                harita = _harita(robot.kurumlari_oku())
                dosya_zamani = _degisme_zamani()
                print(f"  kurum listesi yeniden yüklendi ({len(harita)} kurum)")

            try:
                nabiz("bos", "canli")
                # Ad adrese kodlanarak konur: Türkçe harfli ad ("İş-laptopu")
                # ham yazılınca istek satırı ASCII'ye çevrilemiyor, robot her
                # turda "'ascii' codec can't encode" verip hiç iş alamıyordu.
                is_ = _istek(f"{taban}/fatura/robot/is/?{urllib.parse.urlencode({'robot': ad})}", anahtar)
            except Exception as e:  # noqa: BLE001
                print("  Django'ya ulaşılamadı:", e, _ipucu(e))
                time.sleep(aralik)
                continue
            if not is_.get("var"):
                time.sleep(aralik)
                continue

            t = is_["talep"]
            print(f"  iş #{t['talep_id']}: {t['kurum_id']} / {t['numara']}")
            nabiz("mesgul", "canli")
            token = harita.get(t["kurum_id"])
            if not token:
                print("    kurum kurumlar.json'da yok → katalog.bat ile yenile")
                basarisiz(t["talep_id"], "kurum kurumlar.json'da yok; katalog.bat ile yenile")
                continue
            try:
                veri = robot.sorgula(ctx, token, t["numara"])
            except Exception as e:  # noqa: BLE001
                # Sonuç hemen yazılır: bayi zaman aşımını beklemesin, yönetim
                # sebebi Sorgular listesinde görsün.
                print("    HATA:", e)
                basarisiz(t["talep_id"], e)
                if "turum" in str(e):
                    # Oturum düştü: yönetici laptopta giris.bat ile girene kadar bekle.
                    nabiz("bos", "dustu")
                    time.sleep(15)
                elif "token" in str(e):
                    print("    token eskimiş olabilir → katalog.bat ile yenile")
                continue
            try:
                _istek(f"{taban}/fatura/robot/sonuc/", anahtar,
                       {"talep_id": t["talep_id"], "robot": ad, "veri": veri})
                print(f"    → {veri['durum']}")
            except Exception as e:  # noqa: BLE001
                print("    sonuç yollanamadı:", e)


if __name__ == "__main__":
    # Konsol UTF-8 değilse (bat'sız açılış, dosyaya yönlendirme) Türkçe yazı
    # basarken çökmesin; basılamayan harf "?" olur.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1 and sys.argv[1] == "katalog":
        katalog_komutu()
    else:
        main()
