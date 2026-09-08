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
    """Mesajı Telegram'a iletir. Hata yükseltmez, yalnızca kaydeder.

    Sonucu `(gitti_mi, açıklama)` olarak da döndürür: `telegram_dene`
    komutu bunu ekrana yazar. Sunucuda uyarı günlüğe düşüyordu ama oraya
    bakmak container log'unu taramak demekti; "ayarlar dolu, mesaj yok"
    şikâyetinin sebebi (yanlış sohbet id, kapatılmış bot) tek komutla
    görünsün.
    """
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
    except urllib.error.HTTPError as hata:
        # Telegram hatayı gövdede açıklar: "chat not found", "Unauthorized"…
        try:
            aciklama = json.loads(hata.read().decode()).get("description", str(hata))
        except (ValueError, OSError):
            aciklama = str(hata)
        logger.warning("Telegram mesajı reddetti: %s", aciklama)
        return False, aciklama
    except (urllib.error.URLError, OSError, ValueError) as hata:
        logger.warning("Telegram bildirimi gönderilemedi: %s", hata)
        return False, str(hata)

    if not sonuc.get("ok"):
        aciklama = sonuc.get("description", "bilinmeyen hata")
        logger.warning("Telegram mesajı reddetti: %s", aciklama)
        return False, aciklama
    return True, "gönderildi"


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


def _bayi_adi(kullanici):
    """Bildirimlerde bayi ünvanıyla anılır.

    Kullanıcı adı telefon numarasıdır; numara tek başına hangi firma olduğunu
    anlatmıyor. Ünvan yoksa numaraya düşülür.
    """
    profil = getattr(kullanici, "bayi_profili", None)
    if profil and profil.unvan:
        return profil.unvan
    return kullanici.get_username()


def basvuru_bildir(basvuru, yeni=False):
    """Yeni başvuru ya da durum değişikliği için operasyon grubuna mesaj atar."""
    if not yapilandirilmis_mi():
        return

    bayi_adi = _bayi_adi(basvuru.bayi)

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
    mesaj_gonder(
        "\n".join(
            [
                "💬 <b>Yeni destek talebi</b>",
                "",
                _satir("Talep No", talep.referans_no),
                _satir("Bayi", _bayi_adi(talep.bayi)),
                _satir("Konu", talep.konu),
            ]
        )
    )


def odeme_bildirimi_bildir(bildirim):
    """Bayi havale yaptığını bildirdiğinde operasyon grubuna haber verir.

    Bildirim para hareketi değildir: onaylanana kadar cüzdana dokunulmaz.
    Yani bayi parayı gönderip beklemeye geçiyor ve kimse panele bakmazsa
    bakiyesi saatlerce yüklenmiyordu — mesaj tam da bu bekleyişi kısaltmak
    için var, o yüzden "kontrol et" diye biter.

    Karar (onay/red) bildirilmez: bekleyenler yan menüde zaten rozetle
    sayılıyor, kararı veren de yönetimin kendisi.
    """
    satirlar = [
        "💸 <b>Yeni ödeme bildirimi</b>",
        "",
        _satir("Bayi", _bayi_adi(bildirim.bayi)),
        _satir("Tutar", f"{bildirim.tutar} ₺"),
        _satir("Yatırılan Hesap", bildirim.banka.banka_adi if bildirim.banka else ""),
        _satir("Gönderen", bildirim.gonderen_adi),
        _satir("Açıklama", bildirim.aciklama),
        "",
        "Havale hesaba geçtiyse panelden onayla — onaylanana kadar bayinin "
        "bakiyesine yazılmaz.",
    ]
    mesaj_gonder("\n".join(s for s in satirlar if s is not None))


def siparis_bildir(siparis):
    """Bayi mağazadan ürün aldığında operasyon grubuna haber verir.

    Para siparişle birlikte bakiyeden düştüğü için onay beklenmiyor; mesaj
    "hazırla ve uğradığında ver" demek. Teslim ve iptal bildirilmez —
    bekleyen siparişler yan menüde zaten rozetle sayılıyor.
    """
    mesaj_gonder(
        "\n".join(
            s
            for s in [
                "🛒 <b>Yeni ürün siparişi</b>",
                "",
                _satir("Sipariş No", siparis.referans_no),
                _satir("Bayi", _bayi_adi(siparis.bayi)),
                _satir("Ürün", f"{siparis.urun_adi} ×{siparis.adet}"),
                _satir("Tutar", f"{siparis.tutar} ₺"),
                _satir("Not", siparis.bayi_notu),
            ]
            if s is not None
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
