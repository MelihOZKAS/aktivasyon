"""Paylaşılan Vodafone kodu (13239) ile açılmış eski kayıtlar.

5G Tam Senlik paketlerinin hepsi `reasonCode` 13239 taşıyordu; sorgu onları
tek pakete çökertiyordu ve o dönemde katalog/görülen listesine düz "13239"
koduyla girdiler. Kod artık `13239-paket-adi`; eski kayıtlar hiçbir sorguyla
eşleşmiyor, katalogda aynı paket iki kez görünüyordu.

· Görülen paketlerdeki düz kodlu satır silinir: o kod artık üretilmiyor.
· Katalogdaki düz kodlu paketin yeni kodlu eşi varsa: eskisinin yenisinde
  olmayan sağlayıcı satırları ve grup fiyatları yenisine taşınır; eskisinin
  işlemi yoksa silinir, varsa geçmiş bozulmasın diye pasif ve bayiden gizli
  kalır. Eşi yoksa eskisinin kodu yeni biçime çevrilir (fiyatı, sağlayıcısı
  korunur).
"""

from django.db import migrations

from apps.katalog.utils import turkce_slug

PAYLASILAN_KODLAR = ("13239",)


def temizle(apps, schema_editor):
    GorulenPaket = apps.get_model("kontor", "GorulenPaket")
    Paket = apps.get_model("kontor", "Paket")
    Rota = apps.get_model("kontor", "Rota")
    PaketFiyati = apps.get_model("kontor", "PaketFiyati")
    Islem = apps.get_model("kontor", "Islem")

    GorulenPaket.objects.filter(kod__in=PAYLASILAN_KODLAR).delete()

    for eski in Paket.objects.filter(kod__in=PAYLASILAN_KODLAR):
        if not eski.ad:
            continue
        yeni_kod = f"{eski.kod}-{turkce_slug(eski.ad)}"[:60]
        esi = Paket.objects.filter(kategori_id=eski.kategori_id, kod=yeni_kod).first()
        if esi is None:
            eski.kod = yeni_kod
            eski.save(update_fields=["kod"])
            continue
        olan_saglayicilar = set(Rota.objects.filter(paket=esi).values_list("saglayici_id", flat=True))
        for rota in Rota.objects.filter(paket=eski).exclude(saglayici_id__in=olan_saglayicilar):
            rota.paket = esi
            rota.save(update_fields=["paket"])
        olan_gruplar = set(PaketFiyati.objects.filter(paket=esi).values_list("grup_id", flat=True))
        for fiyat in PaketFiyati.objects.filter(paket=eski).exclude(grup_id__in=olan_gruplar):
            fiyat.paket = esi
            fiyat.save(update_fields=["paket"])
        if esi.tavsiye_fiyati is None and eski.tavsiye_fiyati is not None:
            esi.tavsiye_fiyati = eski.tavsiye_fiyati
            esi.save(update_fields=["tavsiye_fiyati"])
        if Islem.objects.filter(paket=eski).exists():
            eski.aktif = False
            eski.bayiye_gorunur = False
            eski.save(update_fields=["aktif", "bayiye_gorunur"])
        else:
            eski.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("kontor", "0019_bayi_rotasi"),
    ]

    operations = [
        migrations.RunPython(temizle, migrations.RunPython.noop),
    ]
