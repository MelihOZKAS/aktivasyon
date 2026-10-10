"""Fiyat grubunun sayfasındaki Fatura tablosu (Kontör → Fiyat Grupları → grup).

Kontördeki paket fiyatlarının aynısı, aynı sayfada ve aynı formda: satırda
kurum, satırda tek rakam, boş = kurum bu gruba satılmaz. Kontörün grup
sayfası (`kontor.admin.FiyatGrubuAdmin.paket_fiyatlari`) bu modülü çağırır;
fatura kuralları fatura uygulamasında kalır.

Hesap aracı kontörün aracıdır (işaretli satırlara alış + % / + ₺, operatör
fiyatı aynen / + % / + ₺). Fatura satırı aracı iki veriyle besler:
  · alış: sorgusuz kalemde alışımız; sorgulu kurumda 0 (fatura tutarı aynen
    geçer, kutudaki hizmet bedeli tamamen kârdır),
  · operatör (müşteri) fiyatı: kurumun "Müşteriye" rakamı.
"""

from decimal import Decimal, InvalidOperation

from apps.fatura.models import GrupFiyati, Kurum

SIFIR = Decimal("0.00")


def _ondalik(metin):
    """Kutudan gelen "5,50" / "1.250,00" / "5.50" → Decimal; boşsa None, bozuksa hata."""
    metin = (metin or "").strip().replace(" ", "")
    if not metin:
        return None
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    deger = Decimal(metin)  # bozuksa InvalidOperation
    if deger < 0:
        raise InvalidOperation
    return deger.quantize(Decimal("0.01"))


def kurumlar(pasif=False):
    sorgu = Kurum.objects.select_related("kategori").order_by("kategori__sira", "kategori__ad", "sira", "ad")
    return list(sorgu if pasif else sorgu.filter(aktif=True))


def ayikla(liste, post):
    """Formdan gelen rakamları süzer. Dönüş: ([(kurum, tutar|None)], {kurum_id: hata}).

    Yalnızca formda kutusu olan kurum yazılır (süzgeçte gizlenen pasif
    kurumun rakamına dokunulmaz). Sorgusuz kalemde 0 yazılamaz: net fiyat
    olmaz, satılmayacaksa kutu boş bırakılır.
    """
    yazilacak, hatalar = [], {}
    for kurum in liste:
        ad = f"fatura_{kurum.pk}"
        if ad not in post:
            continue
        try:
            tutar = _ondalik(post.get(ad))
        except (InvalidOperation, ValueError):
            hatalar[kurum.pk] = "Rakam anlaşılamadı."
            continue
        if not kurum.sorgulu and tutar == 0:
            hatalar[kurum.pk] = "Net fiyat 0 olamaz; satılmayacaksa boş bırak."
            continue
        yazilacak.append((kurum, tutar))
    return yazilacak, hatalar


def kaydet(grup, yazilacak):
    """Rakamları gruba yazar; boş = satırı siler (bu gruba satılmaz). Dönüş: değişen sayısı."""
    mevcut = {g.kurum_id: g for g in GrupFiyati.objects.filter(grup=grup, kurum__in=[k for k, _ in yazilacak])}
    degisen = 0
    for kurum, tutar in yazilacak:
        kayit = mevcut.get(kurum.pk)
        if tutar is None:
            if kayit:
                kayit.delete()
                degisen += 1
        elif kayit is None:
            GrupFiyati.objects.create(kurum=kurum, grup=grup, tutar=tutar)
            degisen += 1
        elif kayit.tutar != tutar:
            kayit.tutar = tutar
            kayit.save(update_fields=["tutar"])
            degisen += 1
    return degisen


def hepsine_yaz(grup, liste, tutar):
    """Listedeki bütün **sorgulu** kurumlara aynı fatura başı bedeli yazar.

    Grubun sayfasının üstündeki tek kutu: "10 ₺ yaz, bu gruptakilerin hepsi
    10 ₺ olsun." Sorgusuz kaleme (HGS 100 TL) dokunulmaz — onun rakamı bedel
    değil net satış fiyatıdır; 10 yazılsaydı 100 TL'lik yükleme 10 ₺'ye
    satılırdı. Dönüş: (yazılan kurum sayısı, değişen sayısı).
    """
    sorgulular = [k for k in liste if k.sorgulu]
    return len(sorgulular), kaydet(grup, [(k, tutar) for k in sorgulular])


def satirlar(grup, liste, post=None, hatalar=None):
    """Tablonun satırları; POST hatalıysa yazılan değer kutuda kalır."""
    mevcut = {g.kurum_id: g.tutar for g in GrupFiyati.objects.filter(grup=grup, kurum__in=liste)}
    sonuc = []
    for kurum in liste:
        tutar = mevcut.get(kurum.pk)
        alis = SIFIR if kurum.sorgulu else kurum.alis_fiyati
        if post is not None and f"fatura_{kurum.pk}" in post:
            deger = post.get(f"fatura_{kurum.pk}", "")
        else:
            deger = "" if tutar is None else str(tutar).replace(".", ",")
        sonuc.append({
            "kurum": kurum,
            "alis": alis,
            "musteri": kurum.tavsiye,
            "deger": deger,
            "kar": (tutar - alis) if tutar is not None and alis is not None else None,
            "hata": (hatalar or {}).get(kurum.pk, ""),
        })
    return sonuc
