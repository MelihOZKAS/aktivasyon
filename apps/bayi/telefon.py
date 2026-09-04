"""Telefon numarasını tek biçime indirir.

Bayi kullanıcı adı telefon numarasıdır. Aynı numara "0532 123 45 67",
"+90 532 123 45 67" ve "532-123-45-67" diye yazılırsa üç ayrı hesap açılır
ve bayi hangisiyle gireceğini bilemez. Bu yüzden numara her yerde aynı
biçime indirilir: **başında sıfır ve ülke kodu olmadan 10 hane**.

Tek doğru biçim: `5321234567`
"""

import re

# Türkiye cep numarası: 5 ile başlayan 10 hane.
TELEFON_DESENI = re.compile(r"^5\d{9}$")

# Yalnızca rakam ve ayraçlardan oluşan metin telefon sayılır; "fadil" gibi
# gerçek bir kullanıcı adı bozulmasın diye harf görünce dokunulmaz.
AYRAC_DESENI = re.compile(r"^[\d\s+()\-./]+$")


def normalize(ham):
    """Telefon gibi görünen metni `5321234567` biçimine indirir.

    Boşluk, tire, parantez ve nokta atılır; `+90` / `90` ülke kodu ve
    baştaki sıfırlar düşer. Metin telefon gibi görünmüyorsa (harf içeriyorsa)
    olduğu gibi döner.
    """
    if not ham:
        return ham

    metin = str(ham).strip()
    if not AYRAC_DESENI.match(metin):
        return metin

    rakamlar = re.sub(r"\D", "", metin)
    if len(rakamlar) == 12 and rakamlar.startswith("90"):
        rakamlar = rakamlar[2:]
    # Sadece ayraçtan ibaret bir metin rakamsız kalır; onu da bozmayalım.
    return rakamlar.lstrip("0") or metin


def gecerli_mi(deger):
    """Normalleştirilmiş numara geçerli bir cep numarası mı?"""
    return bool(TELEFON_DESENI.match(deger or ""))
