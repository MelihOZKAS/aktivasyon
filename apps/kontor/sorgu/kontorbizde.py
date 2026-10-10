"""Aboneye özel paketler: sağlayıcının kontör sayfasını robot sorgular.

Turkcell ve Türk Telekom'un bizim kullanabileceğimiz açık bir sorgusu yok
(Vodafone'unki var, `vodafone.py`). Sağlayıcının (Kontorbizde) bayi
panelindeki kontör sayfası numara yazılınca operatörü kendisi bulur,
"ABONEYE ÖZEL PAKETLERİ SORGULA" o numaranın alabileceği paketleri
listeler. Bunu fatura sorgusunu yapan robot yapar (`znetfaturasorgu/`,
gerçek tarayıcı, yöneticinin oturumu); burası kuyruğu tutar ve robotun
cevabını `SorguPaketi`ne çevirir. Tek robot iki işi birden yapar.

**Kaynak operatör başınadır** (`kontorbizde-turkcell`,
`kontorbizde-avea`): Turkcell kategorisi Turkcell'inkini seçer. Robot
numarayı yazınca sayfanın bulduğu operatörü beklenenle karşılaştırır;
tutmuyorsa (numara taşınmış) hiç sorgulamaz. Robot operatörü
okuyamazsa paketlerin üstünde yazan operatöre burada bakılır. İkisinde de
bayi "bu numara Vodafone hattı" görür, başka operatörün paketleri
Operatörde Görülen'e yanlış kategoriyle düşmez.

**Cevap istek içinde beklenmez.** Kaynak çağrılınca sorguyu kuyruğa koyar
ve `SorguBekleniyor` yükseltir; bayi ekranı 2 sn'de bir, gönderim planı
işçinin her turunda yeniden sorar. Robot sonucu yazınca kaynak onu
döndürür, servis 12 saatlik önbelleğe koyar — aynı numara bir daha robota
gitmez.

Kod paketin sağlayıcıdaki numarasıdır (`yukle_onay(...)`'ın dördüncü
değeri, "8249866.00" → "8249866"); kataloğumuzdaki `Paket.kod` budur.
Dönen bütün paketler Operatörde Görülen'e işlenir: katalogda olan geçilir,
olmayan "Yeni" düşer, Kataloğa ekle içeriğiyle (DK, GB, SMS, gün) açar.
Paketin müşteriye fiyatı `fiyat`, sağlayıcının bize satışı `alis` olarak
sorgunun kaydında durur.

**Boş liste hata sayılır.** Robotun ayrıştıramadığı bir cevap "paket yok"
diye okunsaydı gönderim planı ana paketi de numarada yok sayar, her satışı
sağlayıcıya hiç gitmeden iptal ederdi. Paketi gerçekten olmayan numarada
bedeli küçük: bayi sebebi görür, plan ana paketi gönderir.
"""

import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import partial

from django.db import transaction
from django.utils import timezone

from apps.katalog.utils import turkce_slug
from apps.kontor.sorgu import SorguBekleniyor, SorguHatasi, SorguPaketi, SorguSonucu, kaynak
from apps.kontor.sorgu.vodafone import tutar_metni

# Robotun almadığı sorgu bu süreden sonra kapanır: robot meşgulse ya da
# kapandıysa bayi sonsuza dek "sorgulanıyor" görmesin, plan beklemesin.
ALINMA_SINIRI = timedelta(seconds=30)
# Robotun aldığı ama sonucunu yazmadığı sorgu bu süreden sonra kapanır.
SONUC_SINIRI = timedelta(seconds=60)
# Sonuçlanan sorgu bu süre içinde aynı numara için yeniden açılmaz: yoklayan
# bayi ekranı ve plan sonucu buradan okur, servis önbelleğe koyar. Hata da bu
# süre boyunca gösterilir; sonra yeniden denenir.
TAZELIK = timedelta(seconds=30)

BEKLEME_MESAJI = "Paketler sorgulanıyor."
HATA_MESAJI = "Paket sorgusu şu an yapılamadı."
BOS_MESAJI = "Bu numaraya özel paket bulunamadı."

OPERATOR_ADLARI = {"turkcell": "Turkcell", "vodafone": "Vodafone", "avea": "Türk Telekom"}
# Sayfadaki adlar → protokol adı. "Avea" Türk Telekom'un eski adıdır,
# sağlayıcılar hâlâ öyle yazıyor (`Kategori.PROTOKOL_OPERATORLERI`).
_OPERATOR_ESLERI = {"turktelekom": "avea", "tt": "avea", "ttmobil": "avea"}


def operator_kodu(metin):
    """"Avea", "Türk Telekom", "TURKCELL" → protokol adı; tanınmazsa boş."""
    sade = turkce_slug(str(metin or "")).replace("-", "")
    sade = _OPERATOR_ESLERI.get(sade, sade)
    return sade if sade in OPERATOR_ADLARI else ""


def baska_operator_mesaji(operator):
    ad = OPERATOR_ADLARI.get(operator, operator)
    return f"Bu numara {ad} hattı görünüyor (taşınmış olabilir); {ad} kategorisinden sorgula."


# -- Robotun cevabı ----------------------------------------------------------


def _kod(deger):
    """"8249866.00" → "8249866"; rakam değilse olduğu gibi (en çok 60)."""
    metin = str(deger or "").strip()
    eslesme = re.fullmatch(r"(\d+)(?:\.0+)?", metin)
    return eslesme.group(1) if eslesme else metin[:60]


def _ondalik(deger):
    if deger in (None, ""):
        return None
    try:
        return Decimal(str(deger).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _tam_sayi(deger):
    """"750", "1.000" → 750, 1000; anlaşılmazsa 0."""
    rakamlar = re.sub(r"[.,\s]", "", str(deger or ""))
    return int(rakamlar) if rakamlar.isdigit() else 0


def _icerikten(aciklama, *birimler):
    """Açıklamadaki "750 Dk", "60 Gb" gibi rakamı ilk eşleşen birimle bulur."""
    for birim in birimler:
        eslesme = re.search(rf"(\d[\d.,]*)\s*{birim}\b", aciklama, re.IGNORECASE)
        if eslesme:
            return eslesme.group(1)
    return ""


def _mb(gb):
    """GB → MB (katalogdaki gibi 1 GB = 1000 MB); "1,5" de olur."""
    miktar = _ondalik(gb)
    return int(miktar * 1000) if miktar else 0


def veriyi_temizle(veri):
    """Robotun gönderdiğini yalnızca bilinen alanlara indirger.

    Robotun cevabı dış kaynaktır: kayda giren ve kataloğa açılacak paketin
    içeriğini belirleyen veri burada süzülür. İçerik önce paket kutusunun
    `data-*` değerlerinden, yoksa açıklamadan ("30 Gün, Heryöne 750 Dk, 60
    Gb İnternet, Heryöne 250 Sms") okunur.
    """
    veri = veri if isinstance(veri, dict) else {}
    paketler = []
    for paket in veri.get("paketler") or []:
        if not isinstance(paket, dict):
            continue
        kod = _kod(paket.get("kod"))
        if not kod:
            continue
        aciklama = " ".join(str(paket.get("aciklama") or "").split())[:500]
        fiyat = _ondalik(paket.get("fiyat"))
        alis = _ondalik(paket.get("alis"))
        paketler.append({
            "kod": kod,
            "ad": " ".join(str(paket.get("ad") or "").split())[:200],
            "grup": " ".join(str(paket.get("grup") or "").split())[:100],
            "operator": operator_kodu(paket.get("operator")),
            "aciklama": aciklama,
            "fiyat": str(fiyat) if fiyat is not None else "",
            "alis": str(alis) if alis is not None else "",
            "gun": _tam_sayi(paket.get("gun") or _icerikten(aciklama, "gün", "gun")),
            "dakika": _tam_sayi(paket.get("dk") or _icerikten(aciklama, "dk", "dakika")),
            "internet_mb": _mb(paket.get("gb") or _icerikten(aciklama, "gb")),
            "sms": _tam_sayi(paket.get("sms") or _icerikten(aciklama, "sms")),
        })
    # Numaranın operatörü: robot sayfadan okuduysa o, yoksa paketlerin üstündeki.
    operator = operator_kodu(veri.get("operator"))
    if not operator:
        operator = next((p["operator"] for p in paketler if p["operator"]), "")
    return {
        "durum": "hata" if veri.get("durum") == "hata" else "",
        "mesaj": str(veri.get("mesaj") or "").strip()[:255],
        "operator": operator,
        "paketler": paketler,
    }


def paketleri_coz(sonuc):
    """Temizlenmiş sonuç → `list[SorguPaketi]`. Ağa çıkmaz; test edilebilir.

    Aynı kod bir cevapta iki kez gelirse (farklı ad ya da fiyatla) iç kod
    `kod-paket-adı-tutar` olur — Vodafone'da `reasonCode`'u paylaşan
    paketlerin tek pakete çökmesinin aynı dersi. Birebir tekrar düşülür.
    """
    paketler = [p for p in (sonuc or {}).get("paketler") or [] if p.get("kod")]
    sayilar = Counter(p["kod"] for p in paketler)
    gorulen, cikti = set(), []
    for paket in paketler:
        fiyat = _ondalik(paket.get("fiyat"))
        kod = paket["kod"]
        if sayilar[kod] > 1:
            kod = f"{kod}-{turkce_slug(paket.get('ad') or '')}" + (f"-{tutar_metni(fiyat)}" if fiyat is not None else "")
            kod = kod[:60]
        if kod in gorulen:
            continue
        gorulen.add(kod)
        cikti.append(
            SorguPaketi(
                kod=kod,
                ad=paket.get("ad") or "",
                aciklama=paket.get("aciklama") or "",
                fiyat=fiyat,
                gun=paket.get("gun") or 0,
                dakika=paket.get("dakika") or 0,
                internet_mb=paket.get("internet_mb") or 0,
                sms=paket.get("sms") or 0,
            )
        )
    return cikti


# -- Kuyruk -------------------------------------------------------------------


def suresi_dolanlari_kapat():
    """Robotun almadığı ya da sonucunu yazmadığı sorguları kapatır."""
    from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

    simdi = timezone.now()
    kapat = dict(durum=RobotSorgusuDurumu.HATA, mesaj=HATA_MESAJI, sonuc_tarihi=simdi, guncelleme_tarihi=simdi)
    RobotSorgusu.objects.filter(
        durum=RobotSorgusuDurumu.BEKLIYOR, olusturma_tarihi__lt=simdi - ALINMA_SINIRI
    ).update(**kapat, sonuc={"robot_hatasi": "Robot almadı (meşgul ya da kapalı)."})
    RobotSorgusu.objects.filter(
        durum=RobotSorgusuDurumu.SORGULANIYOR, alinma_tarihi__lt=simdi - SONUC_SINIRI
    ).update(**kapat, sonuc={"robot_hatasi": "Robot sonucu yazmadı (zaman aşımı)."})


def _paket_robotlari():
    from apps.fatura.models import Robot

    return Robot.objects.filter(aktif=True, paket_sorgusu=True)


def robot_hazir_mi():
    from apps.fatura.models import CEVRIMICI_SURESI

    return _paket_robotlari().filter(son_nabiz__gte=timezone.now() - CEVRIMICI_SURESI).exists()


def sonuc_al(numara, operator):
    """Numaranın paketleri; robot henüz cevaplamadıysa `SorguBekleniyor`.

    Sırası: açık sorgu varsa beklenir; az önce sonuçlandıysa (`TAZELIK`)
    sonucu ya da hatası döner; yoksa robot açıksa yeni sorgu açılır. Robot
    kapalıysa sorgu açılmaz, sebebi (çalışma saatleri) söylenir — kuyrukta
    kimse bakmadan beklemesin.
    """
    from apps.fatura.services import kapali_mesaji
    from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

    suresi_dolanlari_kapat()
    son = RobotSorgusu.objects.filter(numara=numara, operator=operator).order_by("-olusturma_tarihi", "-pk").first()
    if son is not None:
        if son.acik:
            raise SorguBekleniyor(BEKLEME_MESAJI)
        if son.sonuc_tarihi and timezone.now() - son.sonuc_tarihi < TAZELIK:
            if son.durum == RobotSorgusuDurumu.TAMAM:
                return SorguSonucu(paketleri_coz(son.sonuc))
            raise SorguHatasi(son.mesaj or HATA_MESAJI)
    if not robot_hazir_mi():
        raise SorguHatasi(kapali_mesaji("Paket sorgusu", robotlar=_paket_robotlari()))
    RobotSorgusu.objects.create(numara=numara, operator=operator)
    raise SorguBekleniyor(BEKLEME_MESAJI)


def ilk_bekleyen():
    """Kuyruktaki en eski sorgunun açılış zamanı; boşsa `None`."""
    from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

    return (
        RobotSorgusu.objects.filter(
            durum=RobotSorgusuDurumu.BEKLIYOR, olusturma_tarihi__gte=timezone.now() - ALINMA_SINIRI
        )
        .order_by("olusturma_tarihi")
        .values_list("olusturma_tarihi", flat=True)
        .first()
    )


def is_ver(robot):
    """Robota bekleyen bir paket sorgusu verir; yoksa `None`.

    Aynı sorgu iki robota gitmez: satır `SELECT … FOR UPDATE SKIP LOCKED`
    ile alınır — fatura kuyruğunun aynısı.
    """
    from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

    suresi_dolanlari_kapat()
    simdi = timezone.now()
    with transaction.atomic():
        sorgu = (
            RobotSorgusu.objects.select_for_update(skip_locked=True)
            .filter(durum=RobotSorgusuDurumu.BEKLIYOR, olusturma_tarihi__gte=simdi - ALINMA_SINIRI)
            .order_by("olusturma_tarihi", "pk")
            .first()
        )
        if sorgu is None:
            return None
        sorgu.durum = RobotSorgusuDurumu.SORGULANIYOR
        sorgu.robot = robot
        sorgu.alinma_tarihi = simdi
        sorgu.save(update_fields=["durum", "robot", "alinma_tarihi", "guncelleme_tarihi"])
    return sorgu


def sonuc_yaz(robot, talep_id, *, veri=None, hata=""):
    """Robotun sonucunu sorguya yazar. Geç gelen sonuç (sorgu kapandı) yutulur.

    Robotun iç hatası (oturum düştü, sayfa açılmadı) bayiye ham
    gösterilmez; yönetim Robot Paket Sorguları listesinde görür.
    """
    from apps.kontor.models import RobotSorgusu, RobotSorgusuDurumu

    with transaction.atomic():
        sorgu = RobotSorgusu.objects.select_for_update().filter(pk=talep_id).first()
        if sorgu is None or not sorgu.acik:
            return sorgu
        sorgu.robot = robot
        sorgu.sonuc_tarihi = timezone.now()
        if hata or veri is None:
            sorgu.durum = RobotSorgusuDurumu.HATA
            sorgu.mesaj = HATA_MESAJI
            sorgu.sonuc = {"robot_hatasi": str(hata or "sonuç yok")[:500]}
        else:
            temiz = veriyi_temizle(veri)
            sorgu.sonuc = temiz
            if temiz["operator"] and temiz["operator"] != sorgu.operator:
                sorgu.durum = RobotSorgusuDurumu.HATA
                sorgu.mesaj = baska_operator_mesaji(temiz["operator"])
            elif temiz["durum"] == "hata":
                # Sağlayıcının kendi mesajı bayiye gösterilir: ne yapacağını söyler.
                sorgu.durum = RobotSorgusuDurumu.HATA
                sorgu.mesaj = temiz["mesaj"] or HATA_MESAJI
            elif not temiz["paketler"]:
                sorgu.durum = RobotSorgusuDurumu.HATA
                sorgu.mesaj = temiz["mesaj"] or BOS_MESAJI
            else:
                sorgu.durum = RobotSorgusuDurumu.TAMAM
                sorgu.mesaj = ""
        sorgu.save()
    return sorgu


def _sorgula(numara, *, sahip=False, operator):
    # Sayfa hat sahibinin adını vermiyor; `sahip` istenmiş olsa da boş kalır.
    return sonuc_al(numara, operator)


for _operator in ("turkcell", "avea"):
    kaynak(f"kontorbizde-{_operator}", f"{OPERATOR_ADLARI[_operator]} aboneye özel paketler (robot)")(
        partial(_sorgula, operator=_operator)
    )
