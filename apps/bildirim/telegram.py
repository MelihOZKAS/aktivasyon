"""Telegram bildirimleri.

Bildirim hiçbir zaman işin önüne geçmez: mesaj gönderimi transaction
tamamlandıktan sonra ayrı bir iş parçacığında yapılır ve hata yükseltmez.
Telegram erişilemez olsa bile bayinin başvurusu kaydedilmiş kalır.

Eski sistemde `requests.get()` doğrudan view içinde çağrılıyordu; Telegram
yavaşladığında bayi bekliyor, çöktüğünde başvuru kaydedilmiş olmasına rağmen
hata sayfası dönüyordu.
"""

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from html import escape

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

API_ADRESI = "https://api.telegram.org/bot{token}/sendMessage"
ZAMAN_ASIMI = 5


def yapilandirilmis_mi():
    return bool(
        getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        and getattr(settings, "TELEGRAM_SOHBET_ID", "")
    )


def _gonder(metin):
    """Mesajı Telegram'a iletir. Hata yükseltmez, yalnızca kaydeder."""
    veri = urllib.parse.urlencode(
        {
            "chat_id": settings.TELEGRAM_SOHBET_ID,
            "text": metin,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode()

    istek = urllib.request.Request(
        API_ADRESI.format(token=settings.TELEGRAM_BOT_TOKEN), data=veri
    )
    try:
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            sonuc = json.loads(yanit.read().decode())
        if not sonuc.get("ok"):
            logger.warning("Telegram mesajı reddetti: %s", sonuc.get("description"))
    except (urllib.error.URLError, OSError, ValueError) as hata:
        logger.warning("Telegram bildirimi gönderilemedi: %s", hata)


def mesaj_gonder(metin):
    """Bildirimi transaction tamamlandıktan sonra, arka planda gönderir.

    `TELEGRAM_ARKA_PLAN=False` yapıldığında gönderim eşzamanlı olur; testlerde
    ve hata ayıklarken sonucu hemen görmek için kullanılır.
    """
    if not yapilandirilmis_mi():
        return

    def calistir():
        # Bildirim hiçbir koşulda çağıran akışı bozmamalı: beklenmedik bir
        # hata bile yalnızca günlüğe düşer.
        try:
            if getattr(settings, "TELEGRAM_ARKA_PLAN", True):
                threading.Thread(target=_gonder, args=(metin,), daemon=True).start()
            else:
                _gonder(metin)
        except Exception:  # noqa: BLE001 - bildirim asla işi durdurmaz
            logger.exception("Telegram bildirimi gönderilirken beklenmedik hata")

    # Geri alınan bir kaydın bildirimi gitmesin.
    transaction.on_commit(calistir)


def _satir(etiket, deger):
    return f"<b>{escape(etiket)}:</b> {escape(str(deger))}" if deger else None


def basvuru_bildir(basvuru, yeni=False):
    """Yeni başvuru ya da durum değişikliği için operasyon grubuna mesaj atar."""
    if not yapilandirilmis_mi():
        return

    bayi_adi = ""
    profil = getattr(basvuru.bayi, "bayi_profili", None)
    if profil and profil.unvan:
        bayi_adi = profil.unvan
    else:
        bayi_adi = basvuru.bayi.get_username()

    baslik = (
        f"🆕 <b>Yeni başvuru</b> · {escape(basvuru.kategori.ad)}"
        if yeni
        else f"🔔 <b>Durum değişti</b> · {escape(basvuru.durum.ad)}"
    )

    hat = basvuru.operator.ad if basvuru.operator else ""
    if basvuru.tarife:
        hat = f"{hat} · {basvuru.tarife.ad}" if hat else basvuru.tarife.ad

    satirlar = [
        baslik,
        "",
        _satir("Bayi", bayi_adi),
        _satir("Müşteri", basvuru.ad_soyad),
        _satir("Hat", hat),
        _satir("Referans", basvuru.referans_no),
    ]

    if not yeni:
        satirlar.insert(3, _satir("Kategori", basvuru.kategori.ad))
        if basvuru.para_islendi and basvuru.hakedis:
            satirlar.append(_satir("Hakediş", f"{basvuru.hakedis} ₺"))

    mesaj_gonder("\n".join(s for s in satirlar if s is not None))


def destek_talebi_bildir(talep):
    """Bayi yeni bir destek talebi açtığında operasyon grubuna haber verir.

    Yanıtlar bildirilmez: açık bir talebin devamı zaten yönetim panelinde
    rozetle sayılıyor, her mesajda grup dolmasın.
    """
    profil = getattr(talep.bayi, "bayi_profili", None)
    unvan = profil.unvan if profil and profil.unvan else talep.bayi.get_username()
    mesaj_gonder(
        "\n".join(
            [
                "💬 <b>Yeni destek talebi</b>",
                "",
                _satir("Talep No", talep.referans_no),
                _satir("Bayi", unvan),
                _satir("Konu", talep.konu),
            ]
        )
    )


def bayi_basvurusu_bildir(basvuru):
    """Bayi olmak isteyen biri form doldurduğunda operasyon grubuna haber verir."""
    mesaj_gonder(
        "\n".join(
            s
            for s in [
                "🤝 <b>Yeni bayi başvurusu</b>",
                "",
                _satir("Ad Soyad", basvuru.ad_soyad),
                _satir("Telefon", basvuru.irtibat),
            ]
            if s is not None
        )
    )
