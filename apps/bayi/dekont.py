"""Müşteriye verilen dekont: kontör yüklemesi ve fatura ödemesi.

Dekont bayinin kendi fişidir: üstte bayinin firması yazar, sağlayıcının
adı hiç geçmez. Rakam müşteriye dönüktür — kontörde tavsiye satış,
faturada müşteri fiyatı (fatura bedeli + hizmet bedeli). Bayinin alışı
dekonta girmez; tavsiye tanımlı değilse bayinin ödediği yazılır, çünkü
başka bilinen bir rakam yoktur.

Üç biçim vardır: 58 mm ve 80 mm termal rulo, A5. Biçim cihaza aittir
(yazıcı o cihaza bağlı), tarayıcıda saklanır, sunucuya gitmez
(`templates/dekont/sayfa.html`).
"""

from apps.bayi.etiket import gorunen_ad


def firma(kullanici):
    """Dekontun başlığı: firma adı, adres, telefon. Boş alan çizilmez."""
    profil = getattr(kullanici, "bayi_profili", None)
    ad = ((profil.unvan if profil else "") or "").strip() or gorunen_ad(kullanici) or kullanici.get_username()
    adres = ""
    telefon = kullanici.get_username()
    if profil is not None:
        adres = " ".join(p.strip() for p in (profil.adres, profil.sehir) if p and p.strip())
        telefon = (profil.telefon or "").strip() or telefon
    # Kullanıcı adı telefon numarasıdır; harfli bir ad (personel) numara değildir.
    return {"ad": ad, "adres": adres, "telefon": telefon if any(c.isdigit() for c in telefon) else ""}
