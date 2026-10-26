"""Fatura iş kuralları: sorgu kuyruğu, robot sözleşmesi, ödeme, sağlayıcıya gönderim ve karar.

Para yalnızca `finans.services` üzerinden hareket eder (`siparis_odemesini_isle`
/ `siparis_odemesini_geri_al`); burada bakiyeye doğrudan dokunulmaz.

**Sağlayıcıya gönderimde kontörün tek gönderim ilkesi geçerlidir.** Her
fatura sağlayıcının bakiyesinden ödenir; aynı fatura kendiliğinden ikinci
kez gönderilmez. Gönderim ağa çıkmadan `Gonderim` olarak yazılır; cevap
anlaşılamazsa ya da sağlayıcı gönderimi reddederse ödeme yönetime kalır
(Karar ekranı). Yalnızca sağlayıcı kabul edip sonra "iptal" derse tutar
kendiliğinden iade edilir.
"""

import base64
import binascii
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from apps.fatura.models import (
    CEVRIMICI_SURESI,
    Gonderim,
    GonderimDurumu,
    GrupFiyati,
    Kurum,
    Odeme,
    OdemeDurumu,
    Robot,
    RobotHesabi,
    SUREN_GONDERIM,
    Sorgu,
    SorguDurumu,
)
from apps.finans.services import (
    SiparisVerilemez,
    _cuzdani_getir,
    siparis_odemesini_geri_al,
    siparis_odemesini_isle,
)
from apps.kontor.models import Saglayici
from apps.kontor.saglayicilar import Gonderim as Cevap
from apps.kontor.saglayicilar import SaglayiciHatasi
from apps.kontor.saglayicilar import Sorgu as Sonuc
from apps.kontor.saglayicilar.http import son_istek, son_istek_sifirla
from apps.magaza.models import Siparis, SiparisDurumu

logger = logging.getLogger(__name__)

# Robotun almadığı sorgu bu süreden sonra kapanır: kuyrukta kimse yokken
# bayi sonsuza dek "sorgulanıyor" görmesin.
ALINMA_SINIRI = timedelta(seconds=45)
# Robotun aldığı ama sonucunu yazmadığı sorgu (laptop kapandı, tarayıcı
# takıldı) bu süreden sonra kapanır. Robot en çok ~35 sn bekliyor.
SONUC_SINIRI = timedelta(seconds=75)
# Ödeme bu kadar eski sorgudan yapılmaz: tutar bu arada değişmiş olabilir.
ODEME_SURESI = timedelta(minutes=30)
# Aynı numaraya aynı kalem (sorgusuz) bu süre içinde ikinci kez açılmaz;
# çift dokunuş ya da yenilenen sayfa iki kez ödetmesin.
TEKRAR_KORUMASI = timedelta(minutes=2)
# Aynı numaranın sorgusu kısa süre içinde tekrar istenirse yenisi açılmaz.
SORGU_TEKRARI = timedelta(seconds=60)
# Ödeme açıldığı anda arka planda gönderilir; işçi bu kadar bekleyip
# gönderilmemiş kalanı devralır (iş parçacığı ölmüş demektir).
GONDERIM_BEKLEMESI = timedelta(seconds=10)
# Kendiliğinden gönderim yalnızca bu kadar yeni ödemede yapılır. Daha eskisi
# (işçi uzun süre kapalı kaldı, sağlayıcı sonradan tanımlandı) yönetimindir:
# o arada elle ödemiş olabilir, işçi ikinci kez ödetmesin.
OTOMATIK_GONDERIM_SURESI = timedelta(minutes=5)
# Gönderimin cevabı en çok ~20 sn sürer (`http.ZAMAN_ASIMI`); bundan uzun
# "Gönderiliyor"da kalan kayıt yarıda ölmüş süreçtir, belirsize düşer.
YARIM_GONDERIM = timedelta(minutes=2)
# Sağlayıcıya "ödendi mi?" bu aralıktan sık sorulmaz; ilk sorgu da gönderimden
# bu kadar sonra. Kontördeki gibi 25 sn'ydi; yönetim "10 dakikada bir yeter"
# dedi — fatura saniyeler içinde ödenmiyor, erken sorgu hep "bekliyor" döner.
# Yönetimin "Sonucu sorgula"sı bu süreye bağlı değildir.
SONUC_ARALIGI = timedelta(minutes=10)
# Süren gönderim bundan uzun süredir sorulmadıysa işçi çalışmıyordur: karar
# ekranı "bir şey yapman gerekmiyor" demez, işçiye bakılmasını söyler. Son
# sorgunun zamanı ekranda yokken sağlayıcıda ödenmiş fatura saatlerce
# "Ödeniyor"da duruyor, işçinin mi sağlayıcının mı beklettiği görünmüyordu.
SORGU_GECIKMESI = SONUC_ARALIGI * 3
# İşçinin bir fatura turunda sonuç sormaya ayırdığı en uzun süre (saniye).
# Sorgu gönderim başına tektir; sağlayıcı yavaşsa kalanlar sonraki tura
# kalır — aynı işçi kontör işlemlerini de yürütüyor, onları bekletmesin.
SORGU_TURU_SURESI = 30

ROBOT_YOK_MESAJI = "Fatura sorgusu şu an yapılamıyor. Biraz sonra yeniden dene."
ZAMAN_ASIMI_MESAJI = "Sorgu yanıt vermedi, yeniden dene."


class FaturaHatasi(SiparisVerilemez):
    """İşlem yapılamadı; sebebi bayiye gösterilebilir. Para hareket etmedi."""


class KararVerilemez(Exception):
    """Yönetimin kararı uygulanamadı (ödeme zaten sonuçlanmış gibi)."""


# -- Kurum ---------------------------------------------------------------


def satistaki_kurum(kod, grup=None):
    return Kurum.objects.bayiye_acik(grup).select_related("kategori", "operator").filter(kod=kod).first()


# -- Fiyat (kontör fiyat gruplarıyla, kontörün kuralı) ---------------------
#
# Tek hesap yeri: bayi ekranı ve ödeme buradan okur. Gruplar kontörle
# ortaktır; bayi kontörde hangi gruptaysa faturada da o grubun rakamını
# öder. Grupta rakam yazılmamışsa kurum o gruba **satılmaz** (`None`).
# Grup yoksa (varsayılan grup da yoksa) kurumun kendi rakamı geçerli —
# kontördeki `grup_fiyati` ile aynı.


def fiyat_grubu(bayi):
    """Bayinin fiyat grubu: cüzdandaki kontör grubu, boşsa varsayılan grup."""
    from apps.kontor.services import bayi_grubu

    return bayi_grubu(bayi)


def grup_tutarlari(grup, kurumlar):
    """{kurum_id: tutar}: bu grupta yazılmış rakamlar (liste başına tek sorgu)."""
    if grup is None:
        return {}
    return dict(GrupFiyati.objects.filter(grup=grup, kurum__in=kurumlar).values_list("kurum_id", "tutar"))


def hizmet_bedeli(kurum, grup, tutarlar=None):
    """Sorgulu kurumda bu gruptaki bayinin fatura başına hizmet bedeli; yoksa `None`."""
    if grup is None:
        return kurum.hizmet_bedeli
    tutarlar = grup_tutarlari(grup, [kurum]) if tutarlar is None else tutarlar
    return tutarlar.get(kurum.pk)


def sabit_fiyat(kurum, grup, tutarlar=None):
    """Sorgusuz kalemde bu gruptaki bayinin ödeyeceği; yoksa `None` (satılmaz)."""
    if grup is None:
        fiyat = kurum.bayi_fiyati
    else:
        tutarlar = grup_tutarlari(grup, [kurum]) if tutarlar is None else tutarlar
        fiyat = tutarlar.get(kurum.pk)
    return fiyat if fiyat and fiyat > 0 else None


def cevrimici_robotlar(tur="fatura"):
    """O türü (fatura / paket) bugün hâlâ yapabilen, çevrimiçi robotlar.

    Hakkı kalan hesabı olmayan robot listeden düşer: bütün hesapları dolduysa
    o robot artık o türde sorgulayamaz. Sayı az (birkaç robot × birkaç
    on hesap), süzme Python'da.
    """
    qs = Robot.objects.filter(aktif=True, son_nabiz__gte=timezone.now() - CEVRIMICI_SURESI).prefetch_related("hesaplar")
    if tur == "paket":
        qs = qs.filter(paket_sorgusu=True)
    return [r for r in qs if r.hak_kalan_mi(tur)]


def robot_cevrimici_mi():
    return bool(cevrimici_robotlar("fatura"))


def hesap_sec_ve_say(robot, tur):
    """Robotun o türde hakkı kalan hesabını seçip sayacını **gönderim anında**
    bir arttırır; hesabı döndürür (yoksa `None`).

    Sayım sonucu beklemeden burada yapılır: sağlayıcıya işi yolladığımız an o
    hesabın günlük hakkı eksilir. Hesaplar `select_for_update` ile kilitlenir
    (eş zamanlı istek aynı sayacı iki kez yazmasın). En az kullanılmış hesap
    seçilir ki haklar dengeli tükensin. Gün değiştiyse sayaç 0'dan başlar
    (gece 00:00 sıfırı; cron yok).
    """
    bugun = timezone.localdate()
    alan = "kontor_sayaci" if tur == "paket" else "fatura_sayaci"
    with transaction.atomic():
        hesaplar = list(
            RobotHesabi.objects.select_for_update().filter(robot=robot, aktif=True).order_by("sira", "pk")
        )
        adaylar = [h for h in hesaplar if not h.limit_doldu(tur, bugun)]
        if not adaylar:
            return None
        hesap = min(adaylar, key=lambda h: (h.bugunku_sayi(tur, bugun), h.sira, h.pk))
        if hesap.sayac_gunu != bugun:
            hesap.sayac_gunu = bugun
            hesap.fatura_sayaci = 0
            hesap.kontor_sayaci = 0
        setattr(hesap, alan, getattr(hesap, alan) + 1)
        hesap.save(update_fields=["sayac_gunu", "fatura_sayaci", "kontor_sayaci", "guncelleme_tarihi"])
    return hesap


def saglayici_limiti_doldu(hesap_pk, tur):
    """Sağlayıcı bu **hesabın** bu türdeki günlük hakkının dolduğunu söyledi.

    "Sorgu limitinizi doldurdunuz" uyarısı gelince çağrılır: o hesap bugünlük
    o türde iş almaz (saydığımız limit 0/sınırsız olsa da), gece 00:00'da
    (gün değişince) kendiliğinden açılır. Sorgunun kendisi yeniden denenebilir
    hata yapılır; iş robotun başka hesabına ya da başka robota düşer.
    """
    if not hesap_pk:
        return
    alan = "kontor_doldu" if tur == "paket" else "fatura_doldu"
    RobotHesabi.objects.filter(pk=hesap_pk).update(**{alan: timezone.localdate(), "guncelleme_tarihi": timezone.now()})


def kapali_mesaji(ne="Fatura sorgusu", robotlar=None, tur="fatura"):
    """Robot yokken bayiye ne denir: mesai dışıysa saatler, hak dolduysa onu.

    Robot çalışma saatleri dışında bilerek susar; bayi "sistem bağlı değil"
    görüp yöneticiyi aramasın, ne zaman sorgulayabileceğini görsün. Çevrimiçi
    ama hepsi bugünkü hakkını doldurduysa sebep saat değil hak: yarın açılır.
    Kontörün paket sorgusu da aynı robotları bekler; `ne`, `robotlar`, `tur`
    onun için verilir.
    """
    robotlar = list(Robot.objects.filter(aktif=True) if robotlar is None else robotlar)
    saatli = [r for r in robotlar if r.mesai_metni]
    simdi = timezone.localtime().time()
    if saatli and not any(r.mesai_icinde(simdi) for r in saatli):
        araliklar = " / ".join(sorted({r.mesai_metni for r in saatli}))
        return f"{ne} {araliklar} arasında yapılır."
    # Çevrimiçi, hesabı olan ama hepsinin hakkı bugün dolduysa: sebep saat
    # değil, hak (yarın açılır). Hiç hesabı olmayan robot buraya girmez —
    # o bir ayar sorunu, "yarın açılır" yanıltıcı olur; genel mesaj verilir.
    hesapli = [
        r for r in robotlar
        if r.cevrimici and r.mesai_icinde(simdi) and any(h.aktif for h in r.hesaplar.all())
    ]
    if hesapli and not any(r.hak_kalan_mi(tur) for r in hesapli):
        return f"Bugünkü {ne.lower()} hakkı doldu. Yarın yeniden açılır."
    return f"{ne} şu an yapılamıyor. Biraz sonra yeniden dene."


def _numara(kurum, numara):
    try:
        return kurum.numarayi_dogrula(numara)
    except ValidationError as hata:
        raise FaturaHatasi(hata.messages[0]) from hata


# -- Sorgu kuyruğu -------------------------------------------------------


def sorgu_baslat(bayi, kurum, numara):
    """Bayinin sorgusunu kuyruğa koyar; robot birazdan alır.

    Robot çevrimdışıysa sorgu açılmaz — kuyrukta bekleyip zaman aşımına
    düşeceğini bilerek bayiyi bekletmek yerine baştan söylenir. Aynı numara
    az önce sorgulandıysa yenisi açılmaz, o döner (çift dokunuş robotu iki
    kez yormasın).
    """
    if not kurum.sorgulu:
        raise FaturaHatasi("Bu kurumda sorgu yok. Tutarı seçip doğrudan ödenir.")
    if not Kurum.objects.bayiye_acik(fiyat_grubu(bayi)).filter(pk=kurum.pk).exists():
        raise FaturaHatasi("Bu kurum şu an kapalı.")
    numara = _numara(kurum, numara)
    if not robot_cevrimici_mi():
        raise FaturaHatasi(kapali_mesaji())

    simdi = timezone.now()
    onceki = (
        Sorgu.objects.filter(
            bayi=bayi, kurum=kurum, numara=numara, olusturma_tarihi__gte=simdi - SORGU_TEKRARI
        )
        .exclude(durum=SorguDurumu.HATA)
        .order_by("-olusturma_tarihi")
        .first()
    )
    if onceki is not None:
        return onceki
    return Sorgu.objects.create(bayi=bayi, kurum=kurum, numara=numara)


def suresi_dolanlari_kapat():
    """Robotun almadığı ya da sonucunu yazmadığı sorguları kapatır."""
    simdi = timezone.now()
    Sorgu.objects.filter(
        durum=SorguDurumu.BEKLIYOR, olusturma_tarihi__lt=simdi - ALINMA_SINIRI
    ).update(durum=SorguDurumu.HATA, mesaj=ROBOT_YOK_MESAJI, sonuc_tarihi=simdi, guncelleme_tarihi=simdi)
    Sorgu.objects.filter(
        durum=SorguDurumu.SORGULANIYOR, alinma_tarihi__lt=simdi - SONUC_SINIRI
    ).update(durum=SorguDurumu.HATA, mesaj=ZAMAN_ASIMI_MESAJI, sonuc_tarihi=simdi, guncelleme_tarihi=simdi)


def is_ver(robot):
    """Robota bekleyen bir sorgu verir; yoksa (ya da hesabı kalmadıysa) `None`.

    **Aynı sorgu iki robota gitmez:** satır `SELECT … FOR UPDATE SKIP
    LOCKED` ile alınır. İş bir hesaba atanır ve o hesabın hakkı **gönderim
    anında** eksilir (`hesap_sec_ve_say`); hakkı kalan hesap yoksa iş
    atanmaz, başka robota/hesaba kalır.
    """
    suresi_dolanlari_kapat()
    simdi = timezone.now()
    with transaction.atomic():
        sorgu = (
            Sorgu.objects.select_for_update(skip_locked=True)
            .filter(durum=SorguDurumu.BEKLIYOR, olusturma_tarihi__gte=simdi - ALINMA_SINIRI)
            .order_by("olusturma_tarihi")
            .first()
        )
        if sorgu is None:
            return None
        hesap = hesap_sec_ve_say(robot, "fatura")
        if hesap is None:
            return None
        sorgu.durum = SorguDurumu.SORGULANIYOR
        sorgu.robot = robot
        sorgu.hesap = hesap
        sorgu.alinma_tarihi = simdi
        sorgu.save(update_fields=["durum", "robot", "hesap", "alinma_tarihi", "guncelleme_tarihi"])
    return Sorgu.objects.select_related("kurum", "hesap").get(pk=sorgu.pk)


def _ilk_bekleyen():
    return (
        Sorgu.objects.filter(durum=SorguDurumu.BEKLIYOR, olusturma_tarihi__gte=timezone.now() - ALINMA_SINIRI)
        .order_by("olusturma_tarihi")
        .values_list("olusturma_tarihi", flat=True)
        .first()
    )


def siradaki_is(robot, *, paket=False):
    """Robotun sıradaki işi: `("fatura", Sorgu)`, `("paket", RobotSorgusu)` ya da `None`.

    Tek robot iki işi de yapar: fatura sorgusu ve kontörün aboneye özel
    paket sorgusu (`apps/kontor/sorgu/kontorbizde.py`). İki kuyrukta da
    bekleyen varsa **önce gelen** verilir — ikisinde de ekranında bekleyen
    bir bayi var. Paket işi yalnızca onu yapabildiğini söyleyen robota gider
    (`paket`); eski sürüm robot yalnızca fatura alır.

    Bugünkü hakkı dolan türde iş verilmez: fatura hesaplarının hakkı bitse de
    kontör sürer, kontör bitse de fatura (`Robot.hak_kalan_mi`).
    """
    fatura_acik = robot.hak_kalan_mi("fatura")
    paket_acik = paket and robot.hak_kalan_mi("paket")
    if not (fatura_acik or paket_acik):
        return None

    from apps.kontor.sorgu import kontorbizde

    if paket_acik:
        kontorbizde.suresi_dolanlari_kapat()
    if fatura_acik:
        suresi_dolanlari_kapat()
    if paket_acik:
        paket_ilk = kontorbizde.ilk_bekleyen()
        fatura_ilk = _ilk_bekleyen() if fatura_acik else None
        if paket_ilk is not None and (fatura_ilk is None or paket_ilk <= fatura_ilk):
            is_ = kontorbizde.is_ver(robot)
            if is_ is not None:
                return "paket", is_
    if fatura_acik:
        sorgu = is_ver(robot)
        if sorgu is not None:
            return "fatura", sorgu
    if paket_acik:
        # Fatura kuyruğu boşaldıysa (başka robot kaptı) bekleyen paket işi.
        is_ = kontorbizde.is_ver(robot)
        if is_ is not None:
            return "paket", is_
    return None


def _tutar(deger):
    if deger in (None, ""):
        return None
    try:
        return Decimal(str(deger).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def fatura_tutari(fatura):
    """Faturanın kendi bedeli: bayinin ve müşterinin rakamı bunun üstüne kurulur.

    Sağlayıcının "Toplam Tutar"ı kendi işlem bedelini (20 ₺) ve G. hizmet
    bedelini katıyor. Bir süre taban oydu: 487 ₺'lik fatura Perakende'de
    (+7,50) bayiye 514,50 ₺, müşteriye (+20) 527 ₺ yazıyordu. Yönetim: "487'yi
    alacağız, hizmet bedelini karıştırmayacağız." Doğrusu 494,50 / 507.
    Bedel okunamadıysa (eski kayıt) toplam kullanılır.
    """
    bedel = _tutar(fatura.get("fatura_bedeli"))
    return bedel if bedel is not None and bedel > 0 else Decimal(fatura["toplam_tutar"])


def dekont_ozeti(odeme):
    """Dekontta müşteriye dönük rakamlar: fatura bedelleri ve toplam.

    Toplam müşteri fiyatıdır (`tavsiye_fiyati`: faturaların bedeli + kurumun
    müşteriye eki). Hizmet bedeli ayrı satır olarak yazılmaz, her fatura
    satırının içindedir (fatura + ek). Bayinin ödediği dekonta girmez; yalnızca müşteri fiyatı kaydı
    olmayan ödemede o yazılır — başka bilinen rakam yok. Sorgusuz kalemde
    (HGS 100 TL) fatura satırı yoktur.
    """
    # Fatura satırı müşterinin o fatura için ödediğidir: bedel + kurumun
    # müşteri eki. Yalnızca bedel yazılınca satırlar toplamı tutmuyordu
    # (548,25 + 19,68 altında TOPLAM 607,93): bayi "fatura başı toplamı
    # görmek istiyorum" dedi.
    ek = odeme.kurum.tavsiye if odeme.tavsiye_fiyati and odeme.kurum_id else None
    satirlar = [
        {
            "fatura_no": f.get("fatura_no", ""),
            "son_odeme": f.get("son_odeme_tarihi", ""),
            "tutar": odeme.kurum.musteri_tutari(fatura_tutari(f)) if ek else fatura_tutari(f),
        }
        for f in odeme.faturalar
    ]
    return {"odeme": odeme, "satirlar": satirlar, "toplam": odeme.tavsiye_fiyati or odeme.siparis.tutar}


def vade_durumu(son_odeme_tarihi, bugun=None):
    """Son ödeme gününe göre "gecikmis" / "bugun" / "" (anlaşılamadıysa da "").

    Sağlayıcı tarihi metin olarak yazıyor ("14.10.2026"); başka biçimde
    gelirse renk çizilmez, ekran tarihi yine olduğu gibi gösterir.
    """
    parcalar = str(son_odeme_tarihi or "").split()
    if not parcalar:
        return ""
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            gun = datetime.strptime(parcalar[0], bicim).date()
            break
        except ValueError:
            continue
    else:
        return ""
    bugun = bugun or timezone.localdate()
    if gun < bugun:
        return "gecikmis"
    return "bugun" if gun == bugun else ""


def _veriyi_temizle(veri):
    """Robotun gönderdiğini yalnızca bilinen alanlara indirger.

    Robotun cevabı bir dış kaynaktır; kayda giren ve sonra ödemenin
    tutarını belirleyen veri burada süzülür. Tutar `str` olarak saklanır ki
    `Decimal`'e kayıpsız dönsün.
    """
    faturalar = []
    for f in (veri or {}).get("faturalar") or []:
        if not isinstance(f, dict):
            continue
        no = str(f.get("fatura_no") or "").strip()[:60]
        toplam = _tutar(f.get("toplam_tutar"))
        bedel = _tutar(f.get("fatura_bedeli_tl"))
        if toplam is None and bedel is not None:
            toplam = bedel + (_tutar(f.get("g_hizmet_bedeli")) or 0) + (_tutar(f.get("islem_bedeli")) or 0)
        if not no or toplam is None or toplam <= 0:
            continue
        faturalar.append({
            "fatura_no": no,
            "son_odeme_tarihi": str(f.get("son_odeme_tarihi") or "").strip()[:20],
            "fatura_bedeli": str(bedel) if bedel is not None else "",
            "islem_bedeli": str(_tutar(f.get("islem_bedeli")) or "0.00"),
            "toplam_tutar": str(toplam),
            "odeme_token": str(f.get("odeme_token") or "")[:1000],
        })
    durum = str((veri or {}).get("durum") or "")
    if faturalar:
        durum = "bulundu"
    elif durum not in ("borc_yok", "hata", "limit"):
        durum = "borc_yok"
    return {
        "durum": durum,
        "mesaj": str((veri or {}).get("mesaj") or "").strip()[:255],
        "abone_adi": str((veri or {}).get("abone_adi") or "").strip()[:120],
        "tesisat_no": str((veri or {}).get("tesisat_no") or "").strip()[:40],
        "odenmesi_gereken": str(_tutar((veri or {}).get("odenmesi_gereken")) or ""),
        "faturalar": faturalar,
    }


def sonuc_yaz(robot, talep_id, *, veri=None, hata=""):
    """Robotun sonucunu sorguya yazar. Geç gelen sonuç (sorgu kapandı) yutulur."""
    with transaction.atomic():
        sorgu = Sorgu.objects.select_for_update().filter(pk=talep_id).first()
        if sorgu is None or not sorgu.acik:
            return sorgu
        # İş yalnızca atandığı robottan sonuç kabul eder: başka robot (anahtarı
        # sızsa bile) ne sonucu yazabilir ne de bu işin hesabını "limit doldu"
        # diye kapatabilir. Atanmamışsa (eski/test akışı) serbest.
        if sorgu.robot_id is not None and sorgu.robot_id != robot.pk:
            return sorgu
        sorgu.robot = robot
        sorgu.sonuc_tarihi = timezone.now()
        if hata or veri is None:
            # Robotun iç hatası (oturum düştü, zaman aşımı) bayiye ham
            # gösterilmez; yönetim sonuçta görür.
            sorgu.durum = SorguDurumu.HATA
            sorgu.mesaj = "Sorgu şu an yapılamadı. Biraz sonra yeniden dene."
            sorgu.sonuc = {"robot_hatasi": str(hata or "sonuç yok")[:500]}
        else:
            # Sayım gönderim anında yapıldı (hesap_sec_ve_say); burada sayılmaz.
            temiz = _veriyi_temizle(veri)
            sorgu.sonuc = temiz
            if temiz["durum"] == "limit":
                # Sağlayıcı bu hesabın hakkının dolduğunu söyledi: hesabı
                # bugünlük kapat, sorguyu yeniden denenebilir hata yap (başka
                # hesaba/robota düşsün).
                saglayici_limiti_doldu(sorgu.hesap_id, "fatura")
                sorgu.durum = SorguDurumu.HATA
                sorgu.mesaj = "Sorgu şu an yapılamadı. Biraz sonra yeniden dene."
                sorgu.save()
                return sorgu
            if temiz["durum"] == "hata":
                # Sağlayıcının kendi mesajı ("23:00-06:00 arasında tahsilat
                # yapılamaz") bayiye gösterilir: ne yapacağını söyler.
                sorgu.durum = SorguDurumu.HATA
                sorgu.mesaj = temiz["mesaj"] or "Kurum sorguyu kabul etmedi."
            else:
                sorgu.durum = SorguDurumu.TAMAM
                sorgu.mesaj = "" if temiz["faturalar"] else (
                    temiz["mesaj"] or "Bu numaraya ait ödenecek fatura yok."
                )
        sorgu.save()
    return sorgu


def _mesai(metin):
    """"08:00-23:00" → (time, time); okunamazsa (None, None)."""
    try:
        bas, bit = (p.strip() for p in str(metin).split("-", 1))
        return tuple(datetime.strptime(s, "%H:%M").time() for s in (bas, bit))
    except (ValueError, TypeError):
        return (None, None)


def nabiz(robot, *, durum="", oturum="", mesai=""):
    alanlar = {
        "son_nabiz": timezone.now(),
        "mesgul": durum == "mesgul",
        "oturum_canli": oturum != "dustu",
    }
    if mesai:
        bas, bit = _mesai(mesai)
        if bas is not None:
            alanlar.update(mesai_baslangic=bas, mesai_bitis=bit)
    Robot.objects.filter(pk=robot.pk).update(**alanlar)


def tahmini_sorgusuz(ad):
    """"100 TL Yükle Plaka", "250 TL TC İle Yükle" gibi sabit tutarlı kalemler."""
    a = (ad or "").lower()
    return any(k in a for k in ("tl yükle", "tl ile yükle", "tc ile", "tc i̇le", "plaka"))


def _alan_kurali(veri):
    """Robotun ham kataloğundan da temiz `kurumlar.json`'dan da kuralı çıkarır."""
    if veri.get("alanlar"):
        a = veri["alanlar"][0] or {}
        mn, mx = str(a.get("min", "")), str(a.get("max", ""))
        return {
            "alan_etiketi": str(a.get("etiket") or "").strip()[:60],
            "min_hane": int(mn) if mn.isdigit() else None,
            "max_hane": int(mx) if mx.isdigit() else None,
            "sadece_rakam": a.get("tur") == "int",
        }
    return {
        "alan_etiketi": str(veri.get("alan_etiketi") or "").strip()[:60],
        "min_hane": veri.get("min_hane"),
        "max_hane": veri.get("max_hane"),
        "sadece_rakam": veri.get("sadece_rakam"),
    }


def uzak_id_coz(veri):
    """Kurumun sağlayıcıdaki numarası: verilmişse o, yoksa robotun token'ından.

    Robotun kataloğundaki token sağlayıcının kendi kurum bilgisidir (base64,
    `&id=120&…&api_adi=92&…`); `id` fatura API'sinin KURUM ID'sidir
    (`kurum_listesi.php`'de "120,92,TTNET Mobil"), `api_adi` tekil olmayan
    sorgu kodu.
    """
    deger = str(veri.get("uzak_id") or "").strip()
    if deger.isdigit():
        return deger
    token = str(veri.get("token") or "").strip()
    if not token:
        return ""
    try:
        ham = base64.b64decode(token).decode("utf-8", "replace")
    except (ValueError, binascii.Error):
        return ""
    for parca in ham.lstrip("&").split("&"):
        anahtar, _, deger = parca.partition("=")
        if anahtar == "id" and deger.strip().isdigit():
            return deger.strip()
    return ""


def katalog_yaz(kurumlar, *, yeni_aktif=False, var_olani_guncelle=True, kategoriler=None, operatorler=None):
    """Kurum listesini kod anahtarıyla işler. Dönüş: (eklenen, güncellenen).

    Sağlayıcının verisi (numara kuralı, sağlayıcıdaki kurum numarası)
    güncellenir, yönetimin kararı (ad, kategori, fiyat, aktif, sorgulu)
    **korunur** — eSIM eşitlemesindeki kuralın aynısı. Robotun getirdiği
    yeni kurum kapalı açılır (`yeni_aktif=False`): yönetim bakmadan bayiye
    çıkmasın. `kategoriler`/`operatorler` yalnızca yeni kayıtta kullanılır:
    kod → kayıt. Kurulumun tohumu `var_olani_guncelle=False` verir: her
    açılışta çalışır ve panelde düzeltilmiş bir kuralı geri almamalı; yalnızca
    boş kurum numarasını doldurur.
    """
    eklenen = guncellenen = 0
    for veri in kurumlar or []:
        if not isinstance(veri, dict):
            continue
        kod = str(veri.get("id") or veri.get("kod") or "").strip()[:80]
        ad = str(veri.get("kurum_adi") or veri.get("ad") or "").strip()[:120]
        if not kod or not ad:
            continue
        kural = {k: v for k, v in _alan_kurali(veri).items() if v not in (None, "")}
        uzak_id = uzak_id_coz(veri)[:20]
        kurum = Kurum.objects.filter(kod=kod).first()
        if kurum is None:
            Kurum.objects.create(
                kod=kod,
                ad=ad,
                kategori=(kategoriler or {}).get(kod),
                operator=(operatorler or {}).get(kod),
                sorgulu=not veri.get("tahmini_sorgusuz", tahmini_sorgusuz(ad)),
                aciklama=str(veri.get("aciklama") or "").strip()[:255],
                aktif=yeni_aktif and bool(veri.get("aktif", True)),
                uzak_id=uzak_id,
                **kural,
            )
            eklenen += 1
            continue
        if not var_olani_guncelle:
            if uzak_id and not kurum.uzak_id:
                kurum.uzak_id = uzak_id
                kurum.save(update_fields=["uzak_id", "guncelleme_tarihi"])
                guncellenen += 1
            continue
        if uzak_id:
            kural["uzak_id"] = uzak_id
        degisen = [alan for alan, deger in kural.items() if getattr(kurum, alan) != deger]
        if degisen:
            for alan in degisen:
                setattr(kurum, alan, kural[alan])
            kurum.save(update_fields=[*degisen, "guncelleme_tarihi"])
            guncellenen += 1
    return eklenen, guncellenen


# -- Ödeme ---------------------------------------------------------------


def _anahtarli_odeme(bayi, anahtar):
    if not anahtar:
        return None
    siparis = Siparis.objects.filter(islem_anahtari=anahtar, bayi=bayi).select_related("fatura").first()
    if siparis is not None and hasattr(siparis, "fatura"):
        return siparis.fatura
    return None


def odenmis_faturalar(kurum, numara):
    """Bu kurumda bu numaranın ödenmiş ya da ödenmekte olan fatura numaraları."""
    nolar = set()
    for odeme in Odeme.objects.filter(kurum=kurum, numara=numara).exclude(durum=OdemeDurumu.IPTAL):
        nolar.update(odeme.fatura_nolari)
    return nolar


def odeme_baslat(bayi, sorgu, secilen, *, anahtar=None):
    """Sorgudan seçilen faturaları öder: tutar bakiyeden düşer.

    Tutarlar bayinin formundan değil **sorgunun kaydından** okunur. Aynı
    fatura iki kez ödenmez (iptal edilmemiş bir ödemede varsa reddedilir).
    Borca yazılmaz; bakiye yetmezse hiçbir şey açılmaz (`SiparisVerilemez`).
    """
    secilen = [str(n).strip() for n in (secilen or []) if str(n).strip()]
    if not secilen:
        raise FaturaHatasi("Ödenecek faturayı seç.")
    anahtar = (anahtar or "").strip()[:64] or None

    with transaction.atomic():
        # Bayinin cüzdanı en başta kilitlenir: aynı bayinin eşzamanlı iki
        # isteği sıraya girer, ikincisi birincinin kaydını görür.
        _cuzdani_getir(bayi.pk)
        mevcut = _anahtarli_odeme(bayi, anahtar)
        if mevcut is not None:
            return mevcut

        sorgu = Sorgu.objects.select_for_update(of=("self",)).select_related("kurum").get(pk=sorgu.pk)
        if sorgu.bayi_id != bayi.pk:
            raise FaturaHatasi("Sorgu bulunamadı.")
        if sorgu.durum != SorguDurumu.TAMAM or not sorgu.faturalar:
            raise FaturaHatasi("Bu sorguda ödenecek fatura yok.")
        if not sorgu.sonuc_tarihi or timezone.now() - sorgu.sonuc_tarihi > ODEME_SURESI:
            raise FaturaHatasi("Sorgu eskidi, tutar değişmiş olabilir. Yeniden sorgula.")
        kurum = sorgu.kurum
        grup = fiyat_grubu(bayi)
        hizmet = hizmet_bedeli(kurum, grup)
        if hizmet is None or not Kurum.objects.bayiye_acik(grup).filter(pk=kurum.pk).exists():
            raise FaturaHatasi("Bu kurum şu an kapalı.")

        faturalar = {f["fatura_no"]: f for f in sorgu.faturalar}
        if any(no not in faturalar for no in secilen):
            raise FaturaHatasi("Seçilen fatura bu sorguda yok.")
        cakisan = odenmis_faturalar(kurum, sorgu.numara) & set(secilen)
        if cakisan:
            raise FaturaHatasi(
                f"{', '.join(sorted(cakisan))} numaralı fatura zaten ödendi ya da ödeniyor."
            )

        kalemler, saglayici, bayi_toplam, musteri = [], Decimal("0"), Decimal("0"), Decimal("0")
        for f in sorgu.faturalar:            # sorgudaki sırayla
            if f["fatura_no"] not in secilen:
                continue
            bedel = fatura_tutari(f)
            bayi_tutari = kurum.bayi_tutari(bedel, hizmet)
            kalemler.append({**f, "bayi_tutari": str(bayi_tutari)})
            saglayici += bedel
            bayi_toplam += bayi_tutari
            musteri += kurum.musteri_tutari(bedel)

        siparis = Siparis.objects.create(
            bayi=bayi,
            urun=None,
            urun_adi=f"Fatura · {kurum.ad} · {sorgu.numara}"[:200],
            adet=1,
            birim_fiyat=bayi_toplam,
            tutar=bayi_toplam,
            islem_anahtari=anahtar,
        )
        odeme = Odeme.objects.create(
            siparis=siparis,
            bayi=bayi,
            kurum=kurum,
            kurum_adi=kurum.ad,
            sorgu=sorgu,
            numara=sorgu.numara,
            abone_adi=sorgu.abone_adi[:120],
            faturalar=kalemler,
            saglayici_tutari=saglayici,
            hizmet_bedeli=bayi_toplam - saglayici,
            # Müşteri eki tanımlı değilse müşteri fiyatı yoktur: dekont ve
            # Kazancım bayinin ödediğini yazar (sorgu ekranındaki büyük rakam).
            # Bir süre faturanın çıplak bedeli yazılıyordu; dekont bayinin
            # ödediğinden az, Kazancım eksi kazanç gösteriyordu.
            tavsiye_fiyati=musteri if kurum.tavsiye else None,
            otomatik=bool(kurum.uzak_id) and Saglayici.fatura_saglayicisi() is not None,
        )
        siparis_odemesini_isle(siparis, olusturan=bayi)
        if odeme.otomatik:
            transaction.on_commit(partial(arka_planda_gonder, odeme.pk))
    return odeme


def sepeti_ode(bayi, kalemler, *, anahtar=None):
    """Sepetteki faturaları tek seferde öder; açılan ödemeleri döndürür.

    Her sorgu (kurum + numara) ayrı bir ödemedir — iptali, dekontu,
    sağlayıcıya gönderimi tek ödemeyle aynı — ama **hepsi ya da hiçbiri**:
    biri açılamazsa (bakiye, eski sorgu, ödenmiş fatura) hiçbiri açılmaz,
    para düşmez. Ödemelerin anahtarı sepetin anahtarından türetilir: sayfa
    yenilenince aynı sepet ikinci kez ödenmez.
    """
    gruplar = {}
    for referans, fatura_no in kalemler:
        gruplar.setdefault(referans, []).append(fatura_no)
    if not gruplar:
        raise FaturaHatasi("Sepet boş.")
    odemeler = []
    with transaction.atomic():
        for referans, nolar in gruplar.items():
            sorgu = Sorgu.objects.select_related("kurum").filter(bayi=bayi, referans_no=referans).first()
            if sorgu is None:
                raise FaturaHatasi("Sepetteki bir sorgu bulunamadı. Sepeti yenile.")
            try:
                odemeler.append(
                    odeme_baslat(bayi, sorgu, nolar, anahtar=f"{anahtar}:{referans}" if anahtar else None)
                )
            except SiparisVerilemez as hata:
                raise type(hata)(f"{sorgu.kurum.ad} · {sorgu.numara}: {hata}") from hata
    return odemeler


def sabit_odeme_baslat(bayi, kurum, numara, *, anahtar=None):
    """Sorgusuz kalemi (HGS 100 TL gibi) öder: kurumun bayi fiyatı düşer."""
    if kurum.sorgulu:
        raise FaturaHatasi("Bu kurumda önce fatura sorgulanır.")
    grup = fiyat_grubu(bayi)
    fiyat = sabit_fiyat(kurum, grup)
    if fiyat is None or not Kurum.objects.bayiye_acik(grup).filter(pk=kurum.pk).exists():
        raise FaturaHatasi("Bu kalem şu an satışta değil.")
    numara = _numara(kurum, numara)
    anahtar = (anahtar or "").strip()[:64] or None

    with transaction.atomic():
        _cuzdani_getir(bayi.pk)
        mevcut = _anahtarli_odeme(bayi, anahtar)
        if mevcut is not None:
            return mevcut
        if Odeme.objects.filter(
            bayi=bayi, kurum=kurum, numara=numara,
            olusturma_tarihi__gte=timezone.now() - TEKRAR_KORUMASI,
        ).exclude(durum=OdemeDurumu.IPTAL).exists():
            raise FaturaHatasi(
                "Bu numaraya aynı kalem az önce verildi. İkinci kez istiyorsan iki dakika sonra yeniden dene."
            )
        siparis = Siparis.objects.create(
            bayi=bayi,
            urun=None,
            urun_adi=f"Fatura · {kurum.ad} · {numara}"[:200],
            adet=1,
            birim_fiyat=fiyat,
            tutar=fiyat,
            islem_anahtari=anahtar,
        )
        odeme = Odeme.objects.create(
            siparis=siparis,
            bayi=bayi,
            kurum=kurum,
            kurum_adi=kurum.ad,
            numara=numara,
            saglayici_tutari=kurum.alis_fiyati,
            hizmet_bedeli=(fiyat - kurum.alis_fiyati) if kurum.alis_fiyati is not None else Decimal("0"),
            tavsiye_fiyati=kurum.tavsiye,
        )
        siparis_odemesini_isle(siparis, olusturan=bayi)
    return odeme


# -- Yönetimin kararı ----------------------------------------------------
#
# Karar hangi yoldan verilirse verilsin buradan geçer; ödeme formunda durum
# alanı salt okunurdur. Para yalnızca `siparis_odemesini_geri_al` ile döner.


def _kilitle(odeme):
    kilitli = Odeme.objects.select_for_update(of=("self",)).select_related("siparis").get(pk=odeme.pk)
    if kilitli.durum != OdemeDurumu.BEKLIYOR:
        raise KararVerilemez("Bu ödeme zaten sonuçlanmış.")
    return kilitli


def odendi_isaretle(odeme, *, olusturan=None, not_=""):
    """Yönetim sağlayıcıda ödedi: ödeme kapanır, para bayide düşülü kalır."""
    with transaction.atomic():
        kilitli = _kilitle(odeme)
        kilitli.durum = OdemeDurumu.ODENDI
        kilitli.sonuc_notu = (not_ or "").strip()[:255]
        kilitli.karar_veren = olusturan
        kilitli.karar_tarihi = timezone.now()
        kilitli.save()
        siparis = kilitli.siparis
        siparis.durum = SiparisDurumu.TESLIM
        siparis.yonetim_notu = ("Ödendi. " + kilitli.sonuc_notu).strip()[:255]
        siparis.save(update_fields=["durum", "yonetim_notu", "guncelleme_tarihi"])
    return kilitli


def iptal_et(odeme, *, olusturan=None, sebep=""):
    """Ödeme yapılamadı: kapanır, tutar ters kayıtla bayiye döner."""
    sebep = (sebep or "").strip()[:200] or "Ödeme yapılamadı."
    with transaction.atomic():
        kilitli = _kilitle(odeme)
        kilitli.durum = OdemeDurumu.IPTAL
        kilitli.sonuc_notu = sebep
        kilitli.karar_veren = olusturan
        kilitli.karar_tarihi = timezone.now()
        kilitli.save()
        siparis = kilitli.siparis
        siparis.durum = SiparisDurumu.IPTAL
        siparis.yonetim_notu = f"İade edildi: {sebep}"[:255]
        siparis.save(update_fields=["durum", "yonetim_notu", "guncelleme_tarihi"])
        siparis_odemesini_geri_al(siparis, olusturan=olusturan)
    return kilitli


# -- Sağlayıcıya gönderim -------------------------------------------------
#
# Ödeme açılınca her fatura kurumun sağlayıcıdaki numarasıyla
# (`Kurum.uzak_id`) fatura sağlayıcısına (`Saglayici.fatura_odemesi`)
# gönderilir; sonucu tek tek sorulur. Bütün faturalar ödendiyse ödeme
# kendiliğinden "Ödendi"ye, sağlayıcı hepsini iptal ettiyse "İptal + iade"ye
# geçer. Gerisi (ret, belirsiz cevap, karışık sonuç) yönetimin kararıdır.


SAGLAYICI_YOK = "Fatura sağlayıcısı seçili değil (Kontör → Sağlayıcılar → “Fatura ödemeleri buraya”)."


def gonderim_engeli(odeme, saglayici=None):
    """Bu ödeme sağlayıcıya neden gönderilemez; gönderilebiliyorsa boş."""
    saglayici = saglayici if saglayici is not None else Saglayici.fatura_saglayicisi()
    if saglayici is None:
        return SAGLAYICI_YOK
    if not odeme.faturalar:
        return "Sabit tutarlı kalem sağlayıcıya gönderilmez; sağlayıcıda elle yüklenir."
    if odeme.kurum is None or not odeme.kurum.uzak_id:
        return f"{odeme.kurum_adi} kurumunun sağlayıcıdaki numarası boş (Fatura → Kurumlar)."
    return ""


def arka_planda_gonder(pk):
    """Ödemeyi ayrı iş parçacığında gönderir; bayi sağlayıcının cevabını beklemez.

    İş parçacığı ölürse işçi (`kontor_isle`) `GONDERIM_BEKLEMESI` sonra
    devralır. Testler `FATURA_ARKA_PLAN = False` ile aynı iş parçacığında çalıştırır.
    """
    if not getattr(settings, "FATURA_ARKA_PLAN", True):
        odemeyi_gonder(pk)
        return
    threading.Thread(target=_is_parcacigi, args=(pk,), daemon=True).start()


def _is_parcacigi(pk):
    try:
        odemeyi_gonder(pk)
    except Exception:
        logger.exception("Fatura ödemesi arka planda gönderilemedi (%s)", pk)
    finally:
        connection.close()


def odemeyi_gonder(pk, *, elle=False):
    """Ödemenin faturalarını sağlayıcıya gönderir; açılan gönderimleri döndürür.

    Kendiliğinden gönderimde her fatura **bir kez** gider (kısıt:
    `fatura_gonderim_otomatik_tekil`). `elle` yönetimin bilinçli yeniden
    gönderimidir: sonucu sürmeyen ve ödenmemiş faturalar yeniden gider,
    gönderilemiyorsa sebebi `KararVerilemez` ile söylenir.

    Gönderimler önce kısa bir transaction'da yazılır (commit), sonra ağa
    çıkılır: süreç düşerse kayıt "Gönderiliyor"da kalır, yeniden gönderilmez.
    """
    if connection.in_atomic_block and getattr(settings, "FATURA_ATOMIK_DENETIMI", True):
        # Açık transaction'da gönderim kaydı commit edilmez; süreç düşerse
        # kaybolur ve fatura ikinci kez ödenirdi. Çağıran görünüm
        # `non_atomic_requests` olmalı.
        raise RuntimeError("Fatura gönderimi transaction içinden yapılamaz.")
    saglayici = Saglayici.fatura_saglayicisi()
    try:
        with transaction.atomic():
            odeme = (
                Odeme.objects.select_for_update(of=("self",))
                .select_related("kurum", "sorgu")
                .filter(pk=pk)
                .first()
            )
            if odeme is None or odeme.durum != OdemeDurumu.BEKLIYOR:
                if elle:
                    raise KararVerilemez("Bu ödeme zaten sonuçlanmış.")
                return []
            engel = gonderim_engeli(odeme, saglayici)
            if engel:
                if elle:
                    raise KararVerilemez(engel)
                return []
            if not elle and not odeme.otomatik:
                return []
            son = odeme.son_gonderimler()
            yeni = []
            for fatura in odeme.faturalar:
                onceki = son.get(fatura["fatura_no"])
                if elle:
                    if onceki is not None and (onceki.suruyor or onceki.durum == GonderimDurumu.ODENDI):
                        continue
                elif onceki is not None:
                    continue
                yeni.append(
                    Gonderim.objects.create(
                        odeme=odeme,
                        saglayici=saglayici,
                        fatura_no=fatura["fatura_no"],
                        ref=saglayici.yeni_ref(),
                        tutar=fatura_tutari(fatura),
                        elle=elle,
                    )
                )
            if elle and not yeni:
                raise KararVerilemez("Gönderilecek fatura yok: hepsi ödendi ya da sağlayıcıda sürüyor.")
    except IntegrityError:
        # Başka süreç aynı faturayı aynı anda aldı; o gönderiyor.
        return []

    faturalar = {f["fatura_no"]: f for f in odeme.faturalar}
    # Sağlayıcının sorgu sayfasında gördüğü tesisat no; yoksa bayinin yazdığı numara.
    sonuc = (odeme.sorgu.sonuc if odeme.sorgu else None) or {}
    tesisat = str(sonuc.get("tesisat_no") or "").strip() or odeme.numara
    for gonderim in yeni:
        _fatura_gonder(gonderim, odeme, faturalar[gonderim.fatura_no], tesisat)
    _sonuclandir(odeme.pk)
    return yeni


def _fatura_gonder(gonderim, odeme, fatura, tesisat):
    son_istek_sifirla()
    try:
        sonuc = gonderim.saglayici.adaptor().fatura_gonder(
            ref=gonderim.ref,
            kurum_id=odeme.kurum.uzak_id,
            abone_adi=odeme.abone_adi,
            son_odeme_tarihi=fatura.get("son_odeme_tarihi", ""),
            tesisat_no=tesisat,
            fatura_no=gonderim.fatura_no,
            tutar=gonderim.tutar,
        )
    except SaglayiciHatasi as hata:
        gonderim.gonderim_istegi = son_istek()
        gonderim.gonderim_cevabi = str(hata)
        # Bağlantı hiç kurulmadıysa sağlayıcıda açılmadı; zaman aşımında açılmış olabilir.
        gonderim.durum = GonderimDurumu.REDDEDILDI if hata.kesin_gitmedi else GonderimDurumu.BELIRSIZ
        gonderim.save()
        return
    except Exception as hata:  # adaptör hatası: istek gitmiş olabilir
        logger.exception("Fatura gönderiminde beklenmeyen hata (%s)", gonderim.ref)
        gonderim.gonderim_istegi = son_istek()
        gonderim.gonderim_cevabi = f"Beklenmeyen hata: {hata}"
        gonderim.durum = GonderimDurumu.BELIRSIZ
        gonderim.save()
        return
    gonderim.gonderim_istegi = son_istek()
    gonderim.gonderim_cevabi = sonuc.ham[:2000] or sonuc.mesaj
    if sonuc.durum == Cevap.KABUL:
        gonderim.durum = GonderimDurumu.ISLEMDE
        gonderim.maliyet = sonuc.maliyet
        gonderim.dusen = sonuc.alis
    elif sonuc.durum == Cevap.RED:
        gonderim.durum = GonderimDurumu.REDDEDILDI
        gonderim.mesaj = sonuc.mesaj[:255]
    else:
        gonderim.durum = GonderimDurumu.BELIRSIZ
    gonderim.save()


def _sonucu_yaz(gonderim, sonuc, istek, simdi):
    """Sorgu cevabını gönderime yazar; durum değiştiyse `True`.

    Durum geçişi koşullu güncellemedir: işçi ve yöneticinin "Sonucu sorgula"sı
    aynı anda yazarsa biri öbürünün sonucunu ezmesin.
    """
    alanlar = {
        "son_sorgu": simdi, "sonuc_istegi": istek, "guncelleme_tarihi": simdi,
        "sonuc_cevabi": (sonuc.ham or sonuc.mesaj)[:2000],
    }
    yeni = {
        Sonuc.BASARILI: GonderimDurumu.ODENDI,
        Sonuc.IPTAL: GonderimDurumu.IPTAL,
        Sonuc.ISLEMDE: GonderimDurumu.ISLEMDE,
    }[sonuc.durum]
    if yeni == gonderim.durum:
        Gonderim.objects.filter(pk=gonderim.pk).update(**alanlar)
        return False
    # Boşsa da yazılır: açıklamasız iptal ile açıklamalı iptal ayrı işlenir
    # (`_sonuclandir`), önceki bir cevabın açıklaması üstünde kalmasın.
    alanlar["mesaj"] = sonuc.mesaj[:255]
    return bool(
        Gonderim.objects.filter(pk=gonderim.pk, durum=gonderim.durum).update(durum=yeni, **alanlar)
    )


def _sonuclari_sor(gonderimler, simdi, *, sure=None):
    """Gönderimlerin sonucunu sağlayıcıya tek tek sorar (`fatura_kontrol`).

    Dönüş: durumu değişen ödemelerin numaraları. Okunamayan cevapta ya da
    ağ hatasında gönderim olduğu gibi kalır, hata cevaba yazılır, sonraki tur
    yeniden sorar. `sure` saniye dolunca kalanlar sorulmadan bırakılır.

    **Toplu sorgu (`fatura_top_kontrol`) kullanılmaz.** İki ve daha çok
    bekleyen gönderimde ona gidiliyordu; biçimi canlıda hiç doğrulanmadı ve
    "bekleyen yazılmaz" kuralıyla boş ya da tanınmayan bir cevap sessizce
    "hepsi bekliyor" okunuyordu. Tekli sorgu bekleyeni de açıkça yazar
    (`1|…`), yönetim karar ekranında her gönderimin son cevabını görür.
    """
    degisen = set()
    basla = time.monotonic()
    for gonderim in gonderimler:
        if sure is not None and time.monotonic() - basla > sure:
            break
        son_istek_sifirla()
        try:
            sonuc = gonderim.saglayici.adaptor().fatura_sorgula(gonderim.ref)
        except SaglayiciHatasi as hata:
            logger.warning("Fatura sonucu sorulamadı (%s): %s", gonderim.ref, hata)
            Gonderim.objects.filter(pk=gonderim.pk).update(
                son_sorgu=simdi, sonuc_istegi=son_istek(), sonuc_cevabi=f"Sorgu hatası: {hata}",
                guncelleme_tarihi=simdi,
            )
            continue
        if _sonucu_yaz(gonderim, sonuc, son_istek(), simdi):
            degisen.add(gonderim.odeme_id)
    return degisen


def _sonuclandir(odeme_pk):
    """Faturaların son gönderimlerine bakıp ödemeyi kendiliğinden kapatır.

    Hepsi ödendiyse "Ödendi"; sağlayıcı hepsini kabul edip **açıklamasız**
    iptal ettiyse (`3|`, canlıda görülen biçim) "İptal + iade". Açıklamalı
    `3|…` yönetime kalır: aynı kod bir hata metni de olabilir (şifre, kayıt
    bulunamadı) ve iptal sayılsaydı sağlayıcıda ödenmiş faturanın parası
    bayiye dönerdi — para kaybı olan yön kendiliğinden yapılmaz. Bir süre
    şifre/IP gibi kelimelerin listesiyle ayrılıyordu; listede olmayan hata
    metni iade ettiriyordu. Yönetici karar ekranında metni görür, tek tıkla
    iade eder. Gerisinde dokunulmaz: ret ve belirsiz cevapta sorun çoğu zaman bizim taraftadır
    (kurum numarası, sağlayıcı bakiyesi) — kontördeki gibi her ödemeyi iade
    etmek yerine yönetim düzeltip yeniden gönderir; karışık sonuçta (biri
    ödendi, biri iptal) kısmi iade yönetimin kararıdır.

    **İade bütün gönderimlere bakar, yalnızca sonuncuya değil:** cevabı
    belirsiz kalmış eski bir gönderim sağlayıcıda ödenmiş olabilir; yönetim
    faturayı elle yeniden gönderip o iptal gelirse para iade edilmez.
    """
    odeme = Odeme.objects.prefetch_related("gonderimler").filter(pk=odeme_pk).first()
    if odeme is None or not odeme.fatura_nolari:
        return
    son = odeme.son_gonderimler()
    if odeme.durum == OdemeDurumu.IPTAL and any(g.durum == GonderimDurumu.ODENDI for g in son.values()):
        # Yönetim sağlayıcıda süren ödemeyi iade etti, sağlayıcı sonradan ödedi:
        # para hem bayiye döndü hem kuruma gitti. Sessiz kalmasın.
        logger.error("İade edilmiş fatura ödemesi sağlayıcıda ödendi (%s)", odeme.referans_no)
        return
    if odeme.durum != OdemeDurumu.BEKLIYOR or any(no not in son for no in odeme.fatura_nolari):
        return
    durumlar = {son[no].durum for no in odeme.fatura_nolari}
    odenmis_olabilir = any(
        g.durum in (*SUREN_GONDERIM, GonderimDurumu.ODENDI, GonderimDurumu.BELIRSIZ)
        for g in odeme.gonderimler.all()
    )
    try:
        if durumlar == {GonderimDurumu.ODENDI}:
            odendi_isaretle(odeme)
        elif (
            durumlar == {GonderimDurumu.IPTAL}
            and not odenmis_olabilir
            and not any(son[no].mesaj for no in odeme.fatura_nolari)
        ):
            iptal_et(odeme, sebep="Kurum ödemeyi kabul etmedi.")
    except KararVerilemez:
        pass  # aynı anda başka yoldan sonuçlandı


def bekleyenleri_isle():
    """İşçinin fatura turu: takılanı gönderir, yarım kalanı belirsize alır, sonucu sorar.

    Sonuç her gönderim için `SONUC_ARALIGI`'nda (10 dk) bir sorulur.

    Dönüş: dokunulan gönderim/ödeme sayısı.
    """
    simdi = timezone.now()
    Gonderim.objects.filter(
        durum=GonderimDurumu.GONDERILIYOR, olusturma_tarihi__lt=simdi - YARIM_GONDERIM
    ).update(
        durum=GonderimDurumu.BELIRSIZ,
        gonderim_cevabi="Gönderim sırasında süreç kesildi; sağlayıcının cevabı alınamadı.",
        guncelleme_tarihi=simdi,
    )

    gonderilmemis = list(
        Odeme.objects.filter(
            otomatik=True,
            durum=OdemeDurumu.BEKLIYOR,
            olusturma_tarihi__lt=simdi - GONDERIM_BEKLEMESI,
            olusturma_tarihi__gte=simdi - OTOMATIK_GONDERIM_SURESI,
        )
        # Elle gönderimi olan da atlanır: yönetim o ödemeyi devraldı.
        .exclude(Exists(Gonderim.objects.filter(odeme=OuterRef("pk"))))
        .values_list("pk", flat=True)[:50]
    )
    for pk in gonderilmemis:
        try:
            odemeyi_gonder(pk)
        except Exception:
            logger.exception("Fatura ödemesi gönderilemedi (%s)", pk)

    sorulacak = list(
        Gonderim.objects.filter(durum=GonderimDurumu.ISLEMDE)
        .filter(
            Q(son_sorgu__isnull=True, olusturma_tarihi__lt=simdi - SONUC_ARALIGI)
            | Q(son_sorgu__lt=simdi - SONUC_ARALIGI)
        )
        .select_related("saglayici")
        # Hiç sorulmamış önce: PostgreSQL boş değeri artan sırada sona koyar.
        .order_by(F("son_sorgu").asc(nulls_first=True), "pk")[:200]
    )
    for pk in _sonuclari_sor(sorulacak, simdi, sure=SORGU_TURU_SURESI):
        _sonuclandir(pk)
    return len(gonderilmemis) + len(sorulacak)


def sonucu_sorgula(odeme):
    """Yönetimin "Sonucu sorgula"sı: süren ve belirsiz gönderimleri sağlayıcıya sorar.

    Salt okumadır, hiçbir şey göndermez. Belirsiz gönderim sağlayıcıda
    bulunursa (bekliyor/ödendi/iptal) o duruma geçer. Dönüş: sorulan sayısı.
    """
    son = Odeme.objects.prefetch_related("gonderimler__saglayici").get(pk=odeme.pk).son_gonderimler()
    sorulacak = [
        g for g in son.values() if g.durum in (GonderimDurumu.ISLEMDE, GonderimDurumu.BELIRSIZ)
    ]
    if not sorulacak:
        raise KararVerilemez("Sorulacak gönderim yok: sağlayıcıda süren ya da cevabı belirsiz fatura bulunmuyor.")
    _sonuclari_sor(sorulacak, timezone.now())
    _sonuclandir(odeme.pk)
    return len(sorulacak)


def yonetim_bekleyenler(qs=None):
    """Yönetimin elinde olan ödemeler: sonuçlanmamış ve sağlayıcıda sürmeyen.

    Elle ödenecekler (sağlayıcıya gitmeyen) ile gönderilemeyen, cevabı
    belirsiz ya da karışık sonuçlananlar. Rozet ve liste süzgeci bunu sayar.
    """
    qs = Odeme.objects.all() if qs is None else qs
    return qs.filter(durum=OdemeDurumu.BEKLIYOR).exclude(
        Exists(Gonderim.objects.filter(odeme=OuterRef("pk"), durum__in=SUREN_GONDERIM))
    )


def kurumlari_eslestir():
    """Sağlayıcının kurum listesini çekip kurumların sağlayıcıdaki numarasını doldurur.

    Eşleşme addandır: kurumun kodu robotun gördüğü kurum adından türetilir
    (`turkce_slug`), API'nin listesindeki ad da aynı sitenin adıdır. Aynı
    adda birden çok kayıt varsa (Bağ-kur iki kez) eşleştirilmez. Dolu ve
    listede bulunan numaraya dokunulmaz — robotun kataloğundan gelen numara
    kesindir; yalnızca boş ya da listede artık olmayan numara yazılır.
    Dönüş: (listedeki kurum, güncellenen, eşleşmeyen kurum adları).
    """
    from apps.katalog.utils import turkce_slug

    saglayici = Saglayici.fatura_saglayicisi()
    if saglayici is None:
        raise FaturaHatasi(SAGLAYICI_YOK)
    try:
        liste = saglayici.adaptor().fatura_kurumlari()
    except SaglayiciHatasi as hata:
        raise FaturaHatasi(f"{saglayici}: {hata}") from hata
    adla = defaultdict(set)
    for kayit in liste:
        adla[turkce_slug(kayit.ad)].add(kayit.kod)
    gecerli = {kayit.kod for kayit in liste}
    guncellenen, eslesmeyen = 0, []
    for kurum in Kurum.objects.order_by("sira", "ad"):
        if kurum.uzak_id and kurum.uzak_id in gecerli:
            continue
        adaylar = adla.get(kurum.kod) or adla.get(turkce_slug(kurum.ad)) or set()
        if len(adaylar) != 1:
            eslesmeyen.append(kurum.ad)
            continue
        kurum.uzak_id = next(iter(adaylar))
        kurum.save(update_fields=["uzak_id", "guncelleme_tarihi"])
        guncellenen += 1
    return len(liste), guncellenen, eslesmeyen
