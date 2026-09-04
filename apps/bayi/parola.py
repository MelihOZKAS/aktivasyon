"""Yöneticinin bayiye vereceği yeni parolayı üretir.

E-posta ile sıfırlama akışı yok: bayi parolasını unuttuğunda yönetici yeni
bir parola üretir ve telefonla ya da mesajla bildirir. Bu yüzden parola iki
şeyi birden tutturmalı — telefonda okunacak kadar açık, tahmin edilmeyecek
kadar geniş bir havuzdan. Rastgele karakter dizisi ("x7Qm#2vL") telefonda
yanlış yazılır; iki kelime ve dört hane hem söylenir hem yazılır.

Kelimelerde Türkçe'ye özgü harf yok: bayi telefon klavyesinde "ç" ya da "ğ"
ararken uğraşmasın, yanlış yazıp giremedim demesin.
"""

import secrets

KELIMELER = (
    "kiraz", "limon", "kavun", "elma", "armut", "erik", "incir", "ceviz",
    "badem", "zeytin", "biber", "domates", "patates", "karpuz", "portakal",
    "mandalina", "kestane", "nar", "ayva", "dut", "deniz", "dalga", "kumsal",
    "orman", "dere", "irmak", "bulut", "sabah", "yildiz", "toprak", "tepe",
    "vadi", "ada", "liman", "kaya", "balik", "kedi", "kumru", "kartal",
    "ceylan", "aslan", "kaplan", "fil", "tilki", "kunduz", "sincap",
    "kelebek", "ari", "bal", "ekmek", "peynir", "tuz", "kahve", "demir",
    "bakir", "altin", "tahta", "kalem", "defter", "kitap", "masa", "kapi",
    "pencere", "duvar", "merdiven", "anahtar", "saat", "ayna", "sepet",
    "kova", "tabak", "bardak", "ceket", "pantolon", "eldiven", "kemer",
    "halat", "tencere",
)


def uret():
    """`kavun-limon-7431` biçiminde yeni bir parola döndürür.

    `secrets` kullanılır: `random` tahmin edilebilir, parola üretmez.
    """
    ilk = secrets.choice(KELIMELER)
    ikinci = secrets.choice(KELIMELER)
    return f"{ilk}-{ikinci}-{secrets.randbelow(9000) + 1000}"
