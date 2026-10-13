"""Fatura sepeti: müşterinin birkaç kurumdaki faturası tek seferde ödenir.

Müşteri tezgâha Turkcell, doğalgaz, su ve elektrik faturasıyla geliyor; bayi
her kurumu sorgulayıp faturaları sepete atar, sonunda hepsini bir kerede
öder ve müşteriye tek dekont verir. Sepet **oturumda** durur: cihaza aittir
ve kısa ömürlüdür — sorgu zaten yarım saat geçerli (`ODEME_SURESI`), bir
veritabanı tablosu bayatlamış kalemleri biriktirirdi.

Sepet yalnızca **hangi sorgunun hangi faturası** olduğunu tutar; tutar her
zaman sorgunun kaydından okunur (`ozet`), ödeme de tek fatura ödemesiyle
aynı kapıdan geçer (`services.sepeti_ode` → `odeme_baslat`).
"""

from decimal import Decimal

from django.utils import timezone

from apps.fatura.models import Kurum, Sorgu, SorguDurumu
from apps.fatura.services import (
    ODEME_SURESI,
    FaturaHatasi,
    fatura_tutari,
    fiyat_grubu,
    hizmet_bedeli,
    odenmis_faturalar,
    vade_durumu,
)

OTURUM_ANAHTARI = "fatura_sepeti"
# Bir sepette en çok bu kadar fatura: Ödemelerim'deki tek dekontun sınırı.
SINIR = 30


def kalemler(request):
    """[(sorgu referansı, fatura no), …] — eklendiği sırayla."""
    ham = request.session.get(OTURUM_ANAHTARI) or []
    return [(str(k[0]), str(k[1])) for k in ham if isinstance(k, (list, tuple)) and len(k) == 2]


def _yaz(request, liste):
    request.session[OTURUM_ANAHTARI] = [list(k) for k in liste]


def ekle(request, sorgu, secilen):
    """Sorgudan seçilen faturaları sepete ekler; eklenen sayısını döndürür.

    Sepete giremeyen fatura (sorguda yok, eski sorgu, zaten ödenmiş) baştan
    geri çevrilir — sepette bekleyip ödeme anında patlamasın.
    """
    secilen = [str(n).strip() for n in (secilen or []) if str(n).strip()]
    if not secilen:
        raise FaturaHatasi("Sepete eklenecek faturayı seç.")
    if sorgu.durum != SorguDurumu.TAMAM or not sorgu.faturalar:
        raise FaturaHatasi("Bu sorguda ödenecek fatura yok.")
    if not sorgu.sonuc_tarihi or timezone.now() - sorgu.sonuc_tarihi > ODEME_SURESI:
        raise FaturaHatasi("Sorgu eskidi; tutar değişmiş olabilir. Yeniden sorgula.")
    nolar = {f["fatura_no"] for f in sorgu.faturalar}
    if any(no not in nolar for no in secilen):
        raise FaturaHatasi("Seçilen fatura bu sorguda yok.")
    odenmis = odenmis_faturalar(sorgu.kurum, sorgu.numara) & set(secilen)
    if odenmis:
        raise FaturaHatasi(f"{', '.join(sorted(odenmis))} numaralı fatura zaten ödendi ya da ödeniyor.")

    liste = kalemler(request)
    # Aynı fatura başka bir sorgudan da eklenmiş olabilir (numara yeniden sorgulandı):
    # eskisi çıkar, yenisi girer — tutar en son sorgudan okunsun.
    yeni = [k for k in liste if not (k[1] in secilen and _ayni_numara(k[0], sorgu))]
    eklenen = 0
    for no in secilen:
        if (sorgu.referans_no, no) not in yeni:
            yeni.append((sorgu.referans_no, no))
            eklenen += 1
    if len(yeni) > SINIR:
        raise FaturaHatasi(f"Sepete en çok {SINIR} fatura girer; önce sepettekileri öde.")
    _yaz(request, yeni)
    return eklenen


def _ayni_numara(referans, sorgu):
    if referans == sorgu.referans_no:
        return True
    return Sorgu.objects.filter(referans_no=referans, kurum_id=sorgu.kurum_id, numara=sorgu.numara).exists()


def cikar(request, referans, fatura_no):
    _yaz(request, [k for k in kalemler(request) if k != (referans, fatura_no)])


def bosalt(request):
    request.session.pop(OTURUM_ANAHTARI, None)


def ozet(bayi, liste):
    """Sepetin ekranı: sorgu sorgu faturalar, her birinin tutarı ve ödenememe sebebi.

    Dönüş: {"gruplar": [{sorgu, kurum, satirlar}], "bayi_toplam",
    "musteri_toplam", "adet", "sorunlu"}. Sorunlu kalem (eski sorgu,
    ödenmiş fatura, kapanan kurum) toplama girmez ve ödemeyi durdurur:
    müşteriye söylenen toplamla ödenen aynı kalsın.
    """
    grup = fiyat_grubu(bayi)
    sorgular = {
        s.referans_no: s
        for s in Sorgu.objects.filter(bayi=bayi, referans_no__in={r for r, _ in liste}).select_related(
            "kurum", "kurum__operator"
        )
    }
    acik = set(
        Kurum.objects.bayiye_acik(grup).filter(pk__in={s.kurum_id for s in sorgular.values()}).values_list("pk", flat=True)
    )
    simdi = timezone.now()
    gruplar, sirali = {}, []
    bayi_toplam = musteri_toplam = Decimal("0")
    sorunlu = False
    odenmisler = {}
    for referans, no in liste:
        sorgu = sorgular.get(referans)
        if sorgu is None:
            continue  # sorgu silinmiş ya da başkasının: sessizce düşer
        if referans not in gruplar:
            gruplar[referans] = {"sorgu": sorgu, "kurum": sorgu.kurum, "satirlar": []}
            sirali.append(gruplar[referans])
        fatura = next((f for f in sorgu.faturalar if f["fatura_no"] == no), None)
        satir = {"fatura_no": no, "referans": referans, "sorun": ""}
        hizmet = hizmet_bedeli(sorgu.kurum, grup)
        if fatura is None:
            satir["sorun"] = "Fatura sorguda yok."
        elif sorgu.kurum_id not in acik or hizmet is None:
            satir["sorun"] = "Kurum şu an satışta değil."
        elif not sorgu.sonuc_tarihi or simdi - sorgu.sonuc_tarihi > ODEME_SURESI:
            satir["sorun"] = "Sorgu eskidi; yeniden sorgula."
        else:
            anahtar = (sorgu.kurum_id, sorgu.numara)
            if anahtar not in odenmisler:
                odenmisler[anahtar] = odenmis_faturalar(sorgu.kurum, sorgu.numara)
            if no in odenmisler[anahtar]:
                satir["sorun"] = "Zaten ödendi ya da ödeniyor."
        if fatura is not None:
            bedel = fatura_tutari(fatura)
            satir.update(
                son_odeme_tarihi=fatura.get("son_odeme_tarihi", ""),
                vade=vade_durumu(fatura.get("son_odeme_tarihi"), timezone.localdate()),
                bayi_tutari=sorgu.kurum.bayi_tutari(bedel, hizmet) if hizmet is not None else None,
                musteri_tutari=musteri_tutari(sorgu.kurum, bedel, hizmet),
            )
        if satir["sorun"]:
            sorunlu = True
        else:
            bayi_toplam += satir["bayi_tutari"]
            musteri_toplam += satir["musteri_tutari"]
        gruplar[referans]["satirlar"].append(satir)
    return {
        "gruplar": sirali,
        "bayi_toplam": bayi_toplam,
        "musteri_toplam": musteri_toplam,
        "adet": sum(len(g["satirlar"]) for g in sirali),
        "sorunlu": sorunlu,
    }


def musteri_tutari(kurum, bedel, hizmet):
    """Müşteriye söylenecek: kurumun müşteri eki varsa fatura + ek, yoksa bayinin ödediği.

    Dekonttaki rakamla aynı kural (`Odeme.tavsiye_fiyati`): para üstü bu
    toplamdan hesaplanır, fişte yazanla tutmalı.
    """
    if kurum.tavsiye:
        return kurum.musteri_tutari(bedel)
    return kurum.bayi_tutari(bedel, hizmet) if hizmet is not None else None
