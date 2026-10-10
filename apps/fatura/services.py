"""Fatura iş kuralları: sorgu kuyruğu, robot sözleşmesi, ödeme ve karar.

Para yalnızca `finans.services` üzerinden hareket eder (`siparis_odemesini_isle`
/ `siparis_odemesini_geri_al`); burada bakiyeye doğrudan dokunulmaz.
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.fatura.models import (
    CEVRIMICI_SURESI,
    GrupFiyati,
    Kurum,
    Odeme,
    OdemeDurumu,
    Robot,
    Sorgu,
    SorguDurumu,
)
from apps.finans.services import (
    SiparisVerilemez,
    _cuzdani_getir,
    siparis_odemesini_geri_al,
    siparis_odemesini_isle,
)
from apps.magaza.models import Siparis, SiparisDurumu

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

ROBOT_YOK_MESAJI = "Fatura sorgusu şu an yapılamıyor; biraz sonra yeniden dene."
ZAMAN_ASIMI_MESAJI = "Sorgu yanıt vermedi; yeniden dene."


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


def robot_cevrimici_mi():
    return Robot.objects.filter(aktif=True, son_nabiz__gte=timezone.now() - CEVRIMICI_SURESI).exists()


def kapali_mesaji(ne="Fatura sorgusu", robotlar=None):
    """Robot yokken bayiye ne denir: mesai dışıysa saatler, değilse genel mesaj.

    Robot çalışma saatleri dışında bilerek susar; bayi "sistem bağlı değil"
    görüp yöneticiyi aramasın, ne zaman sorgulayabileceğini görsün. Kontörün
    paket sorgusu da aynı robotlardan birini bekler; `ne` ve `robotlar` onun
    için verilir.
    """
    robotlar = Robot.objects.filter(aktif=True) if robotlar is None else robotlar
    saatli = [r for r in robotlar if r.mesai_metni]
    simdi = timezone.localtime().time()
    if saatli and not any(r.mesai_icinde(simdi) for r in saatli):
        araliklar = " / ".join(sorted({r.mesai_metni for r in saatli}))
        return f"{ne} {araliklar} arasında yapılır."
    return f"{ne} şu an yapılamıyor; biraz sonra yeniden dene."


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
        raise FaturaHatasi("Bu kurumda sorgu yok; tutarı seçip doğrudan ödenir.")
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
    """Robota bekleyen bir sorgu verir; yoksa `None`.

    **Aynı sorgu iki robota gitmez:** satır `SELECT … FOR UPDATE SKIP
    LOCKED` ile alınır. Beş robot aynı anda sorsa da her biri kilitlenmemiş
    başka bir satırı kapar, kilitli olanı atlar.
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
        sorgu.durum = SorguDurumu.SORGULANIYOR
        sorgu.robot = robot
        sorgu.alinma_tarihi = simdi
        sorgu.save(update_fields=["durum", "robot", "alinma_tarihi", "guncelleme_tarihi"])
    return Sorgu.objects.select_related("kurum").get(pk=sorgu.pk)


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
    """
    if paket:
        from apps.kontor.sorgu import kontorbizde

        kontorbizde.suresi_dolanlari_kapat()
        suresi_dolanlari_kapat()
        paket_ilk, fatura_ilk = kontorbizde.ilk_bekleyen(), _ilk_bekleyen()
        if paket_ilk is not None and (fatura_ilk is None or paket_ilk <= fatura_ilk):
            is_ = kontorbizde.is_ver(robot)
            if is_ is not None:
                return "paket", is_
    sorgu = is_ver(robot)
    if sorgu is not None:
        return "fatura", sorgu
    if paket:
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
    elif durum not in ("borc_yok", "hata"):
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
        sorgu.robot = robot
        sorgu.sonuc_tarihi = timezone.now()
        if hata or veri is None:
            # Robotun iç hatası (oturum düştü, zaman aşımı) bayiye ham
            # gösterilmez; yönetim sonuçta görür.
            sorgu.durum = SorguDurumu.HATA
            sorgu.mesaj = "Sorgu şu an yapılamadı; biraz sonra yeniden dene."
            sorgu.sonuc = {"robot_hatasi": str(hata or "sonuç yok")[:500]}
        else:
            temiz = _veriyi_temizle(veri)
            sorgu.sonuc = temiz
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


def katalog_yaz(kurumlar, *, yeni_aktif=False, var_olani_guncelle=True, kategoriler=None, operatorler=None):
    """Kurum listesini kod anahtarıyla işler. Dönüş: (eklenen, güncellenen).

    Sağlayıcının verisi (numara kuralı) güncellenir, yönetimin kararı (ad,
    kategori, fiyat, aktif, sorgulu) **korunur** — eSIM eşitlemesindeki
    kuralın aynısı. Robotun getirdiği yeni kurum kapalı açılır
    (`yeni_aktif=False`): yönetim bakmadan bayiye çıkmasın.
    `kategoriler`/`operatorler` yalnızca yeni kayıtta kullanılır: kod → kayıt.
    Kurulumun tohumu `var_olani_guncelle=False` verir: her açılışta çalışır
    ve panelde düzeltilmiş bir kuralı geri almamalı.
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
                **kural,
            )
            eklenen += 1
            continue
        if not var_olani_guncelle:
            continue
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
            raise FaturaHatasi("Sorgu eskidi; tutar değişmiş olabilir. Yeniden sorgula.")
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
            toplam = Decimal(f["toplam_tutar"])
            bayi_tutari = kurum.bayi_tutari(toplam, hizmet)
            kalemler.append({**f, "bayi_tutari": str(bayi_tutari)})
            saglayici += toplam
            bayi_toplam += bayi_tutari
            musteri += kurum.musteri_tutari(toplam)

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
            tavsiye_fiyati=musteri,
        )
        siparis_odemesini_isle(siparis, olusturan=bayi)
    return odeme


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
