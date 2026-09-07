"""Bayiye özel başvuru tipi görünürlüğü.

Kapatma **negatif** listede durur (`BayiProfili.kapali_kategoriler`):
yönetici kapatacağını işaretler, boş liste "hepsi açık" demektir. Pozitif
liste (açık olanları işaretlemek) her yeni kategoriyi bayi bayi açmayı
gerektirirdi; unutulan bayide tip hiç görünmez, kimse de sebebini bilmezdi.
Kategori alanlarındaki kuralın aynısı: kapatmak eklemekten kolaydır.

Profili olmayan kullanıcının kapalı tipi de yoktur — eski kullanıcılar
bayi sayılır ve hepsini görür.
"""

from apps.katalog.models import BasvuruKategorisi


def acik_kategoriler(kullanici, sorgu=None):
    """Bu bayiye açık kategoriler. Verilen sorgu daraltılarak döner."""
    if sorgu is None:
        sorgu = BasvuruKategorisi.objects.filter(aktif=True)
    return sorgu.exclude(kapali_bayiler__kullanici=kullanici)


def kategori_acik_mi(kullanici, kategori):
    """Bayi bu kategoriden başvuru girebilir mi?"""
    return not kategori.kapali_bayiler.filter(kullanici=kullanici).exists()


def kapali_kategori_idleri(kullanici):
    """Kapalı kategorilerin id'leri; küme olarak süzmesi kolay olsun diye."""
    profil = getattr(kullanici, "bayi_profili", None)
    if profil is None:
        return set()
    return set(profil.kapali_kategoriler.values_list("pk", flat=True))
