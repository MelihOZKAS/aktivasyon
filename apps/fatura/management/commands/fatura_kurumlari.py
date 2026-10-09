"""Fatura bölümlerini ve kurumlarını tohum dosyasından açar.

Dosya (`apps/fatura/veri/kurumlar.json`) robotun sağlayıcıdan çektiği
listedir (znetfaturasorgu/kurumlar.json), token'ları çıkarılmış ve bayi
ekranının bölümlerine (GSM, İnternet, Elektrik…) dağıtılmış hâlidir.

Kurulum her açılışta çalıştırır; var olan kayda **dokunulmaz** — panelde
yapılan düzenleme (ad, bölüm, fiyat, aktif) kurulumla geri alınmaz. Yalnızca
eksik olan açılır. Sorgulu kurumlar açık gelir (bayi sağlayıcının tutarını
aynen öder; hizmet bedelini yönetim ekler), sorgusuz kalemler fiyatı
yazılana kadar bayiye görünmez.
"""

import json
import pathlib

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.fatura.models import Kategori, Kurum
from apps.fatura.services import katalog_yaz
from apps.katalog.models import Operator
from apps.katalog.utils import turkce_slug

DOSYA = pathlib.Path(__file__).resolve().parents[2] / "veri" / "kurumlar.json"


class Command(BaseCommand):
    help = "Fatura bölümlerini ve kurumlarını tohum dosyasından açar (var olana dokunmaz)."

    def add_arguments(self, ayristirici):
        ayristirici.add_argument("--dosya", default=str(DOSYA), help="Tohum dosyası (varsayılan: uygulamadaki).")

    @transaction.atomic
    def handle(self, *args, dosya, **secenekler):
        veri = json.loads(pathlib.Path(dosya).read_text(encoding="utf-8"))

        bolumler = {}
        for bolum in veri.get("kategoriler", []):
            ad = bolum["ad"]
            kategori = (
                Kategori.objects.filter(ad=ad).first()
                or Kategori.objects.filter(slug=turkce_slug(ad)).first()
            )
            if kategori is None:
                kategori = Kategori.objects.create(ad=ad, sira=bolum.get("sira", 0))
            bolumler[ad] = kategori

        operatorler = {op.ad: op for op in Operator.objects.all()}
        kurumlar = veri.get("kurumlar", [])
        eklenen, _ = katalog_yaz(
            kurumlar,
            yeni_aktif=True,
            var_olani_guncelle=False,
            kategoriler={k["id"]: bolumler.get(k.get("kategori")) for k in kurumlar},
            operatorler={k["id"]: operatorler.get(k.get("operator")) for k in kurumlar if k.get("operator")},
        )
        self.stdout.write(
            f"Fatura: {len(bolumler)} bölüm, {Kurum.objects.count()} kurum ({eklenen} yeni açıldı)."
        )
