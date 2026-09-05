"""Başvuru detayında gösterilecek satırlar.

Satırlar tek yerde üretilir: hem ekranda çizilen liste hem "neler görünsün"
ayar kutusundaki seçenekler buradan gelir. Böylece kategoriye yeni bir form
alanı eklendiğinde ikisi birden kendiliğinden büyür — ayar listesini elle
güncellemek gerekmez.

Anahtarlar kalıcıdır: bayinin kapattığı alanın anahtarı `gizli_alanlar`
listesinde saklanıyor. Var olan bir anahtarı yeniden adlandırırsan bayilerin
seçimi o alanda sıfırlanır.
"""


def _satir(anahtar, etiket, deger, genis=False, rakam=False):
    return {
        "anahtar": anahtar,
        "etiket": etiket,
        "deger": deger,
        "genis": genis,
        "rakam": rakam,
    }


def detay_satirlari(basvuru):
    """Başvurunun bütün bilgileri, ekrandaki sırayla.

    Değeri boş olan satır listeye girmez: bayi olmayan bir bilgiyi ne
    ekranda ne ayar kutusunda görmeli.
    """
    profil = getattr(basvuru.bayi, "bayi_profili", None)
    adaylar = [
        _satir("referans_no", "Referans no", basvuru.referans_no, rakam=True),
        _satir("kategori", "Kategori", basvuru.kategori.ad),
        _satir("durum", "Durum", basvuru.durum.ad),
        _satir("operator", "Operatör", basvuru.operator.ad if basvuru.operator_id else ""),
        _satir("tarife", "Tarife", basvuru.tarife.ad if basvuru.tarife_id else ""),
        _satir("kampanya", "Kampanya", basvuru.kampanya.ad if basvuru.kampanya_id else ""),
        _satir("musteri_tipi", "Müşteri tipi", basvuru.get_musteri_tipi_display()),
        _satir("kimlik_tipi", "Kimlik tipi", basvuru.get_kimlik_tipi_display()),
        _satir("isim", "İsim", basvuru.isim),
        _satir("soyisim", "Soyisim", basvuru.soyisim),
        _satir("kimlik_no", "Kimlik / pasaport no", basvuru.kimlik_no, rakam=True),
        _satir("irtibat", "İrtibat", basvuru.irtibat, rakam=True),
        _satir("numara", "İşlem numarası", basvuru.numara, rakam=True),
        _satir("bayi", "Bayi", basvuru.bayi.get_username(), rakam=True),
        _satir("bayi_unvani", "Bayi ünvanı", profil.unvan if profil else ""),
        _satir(
            "olusturma_tarihi",
            "Giriş tarihi",
            basvuru.olusturma_tarihi.strftime("%d.%m.%Y %H:%M"),
        ),
        _satir(
            "sonuclanma_tarihi",
            "Sonuçlanma tarihi",
            basvuru.sonuclanma_tarihi.strftime("%d.%m.%Y %H:%M")
            if basvuru.sonuclanma_tarihi
            else "",
        ),
    ]

    # Kategoriye özel alanlar. Etiketi kategori tanımından gelir; tanım
    # silinmişse ham anahtar yazılır ki veri kaybolmuş görünmesin.
    etiketler = {alan.kod: alan.etiket for alan in basvuru.kategori.alanlar.all()}
    for kod, deger in (basvuru.ek_bilgiler or {}).items():
        adaylar.append(_satir(f"ek:{kod}", etiketler.get(kod, kod), deger))

    adaylar.append(_satir("adres", "Adres", basvuru.adres, genis=True))
    adaylar.append(
        _satir("bayi_aciklamasi", "Bayi açıklaması", basvuru.bayi_aciklamasi, genis=True)
    )

    return [satir for satir in adaylar if satir["deger"] not in (None, "")]


def gizli_alanlar(kullanici):
    """Bayinin kapattığı alan anahtarları."""
    tercih = getattr(kullanici, "detay_tercihi", None)
    return set(tercih.gizli_alanlar or []) if tercih else set()


def admin_gizli_alanlar(kullanici):
    """Yönetim panelinde bu kullanıcıya gösterilmeyecek alanlar."""
    tercih = getattr(kullanici, "detay_tercihi", None)
    return set(tercih.admin_gizli_alanlar or []) if tercih else set()


def fieldset_alanlari(fieldsets):
    """Fieldset tanımındaki bütün alan adları, sırasıyla.

    `fields` içinde tek alan da olabiliyor, satır oluşturan demet de;
    ikisi de düzleştirilir.
    """
    adlar = []
    for _, ayar in fieldsets:
        for alan in ayar.get("fields", ()):
            if isinstance(alan, (list, tuple)):
                adlar.extend(alan)
            else:
                adlar.append(alan)
    return adlar


def fieldsetleri_suz(fieldsets, gizli):
    """Gizlenen alanları çıkarır; boşalan bölüm hiç çizilmez."""
    if not gizli:
        return fieldsets

    suzulmus = []
    for baslik, ayar in fieldsets:
        alanlar = []
        for alan in ayar.get("fields", ()):
            if isinstance(alan, (list, tuple)):
                satir = tuple(a for a in alan if a not in gizli)
                if satir:
                    alanlar.append(satir if len(satir) > 1 else satir[0])
            elif alan not in gizli:
                alanlar.append(alan)
        if alanlar:
            suzulmus.append((baslik, {**ayar, "fields": tuple(alanlar)}))
    return tuple(suzulmus)
