"""Numarayı sesli okuyan ses birimlerini Gemini'nin sesiyle üretir.

Çıktı depoya girer (`static/ses/rakamlar.mp3` ve `.json`). Sunucuda
çalışmaz: ffmpeg ister ve anahtar yalnızca ortam değişkeninden okunur,
hiçbir dosyaya yazılmaz.

    GEMINI_API_KEY=... manage.py rakam_sesleri                 # hepsi
    GEMINI_API_KEY=... manage.py rakam_sesleri --birim "yüz"   # yalnız biri
    GEMINI_API_KEY=... manage.py rakam_sesleri --ses Charon

Birimler (sıfır, 1..99, yüz..dokuz yüz) partiler hâlinde tek kayıtta
okutulur, kayıt sessiz yerlerinden bölünür ve her parça Gemini'ye yeniden
dinletilir: hangi birim olduğu ve sonunda cızırtı olup olmadığı sorulur.
Birimler dökümde sırayla aranır (fazladan söz ya da tık atlanır), cızırtılı
çıkan birim en çok iki kez yeniden okutulur.

Birimlerin kayıpsız ana kopyası `tmp/rakam_sesleri/`'nde durur (depoya
girmez). `--birim` yalnız o birimi yeniden üretir, öbürlerini ana kopyadan
alır: MP3'ü açıp yeniden sıkıştırmak her seferinde sesi biraz daha bozardı.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import unicodedata
import urllib.error
import urllib.request
import wave
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.kontor import rakam_sesleri as rs

ADRES = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DENEME = 3


def _istek(model, govde, anahtar):
    istek = urllib.request.Request(
        ADRES.format(model=model),
        data=json.dumps(govde).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": anahtar},
    )
    try:
        with urllib.request.urlopen(istek, timeout=300) as cevap:
            return json.load(cevap)
    except urllib.error.HTTPError as hata:
        # Gemini'nin hata metni anahtarı içermez; kotayı ve model adını söyler.
        raise CommandError(f"Gemini {hata.code}: {hata.read().decode(errors='replace')[:600]}")


def _sade(metin):
    metin = unicodedata.normalize("NFC", metin).casefold().replace("i̇", "i")
    return re.sub(r"[^\wçğıöşü]", "", metin)


def _satir(birim):
    """Modele giden satır: yalnızca birim ve nokta.

    Yönerge yazılmaz, ilk denemede onu da sesli okudu. Yüzlükler bir süre
    "Beş yüz…" diye okutuldu (devam tonu için): model sondaki z'yi uzatıyor,
    "yüz" vızıldıyordu. Virgülle de cızırtılı çıktı, nokta temiz.
    """
    return birim.capitalize() + "."


class Command(BaseCommand):
    help = "Numarayı sesli okuyan ses birimlerini Gemini'nin sesiyle üretir."

    def add_arguments(self, parser):
        parser.add_argument("--ses", default="Kore", help="Gemini'nin hazır seslerinden biri.")
        parser.add_argument("--model", default="gemini-3.8-flash-tts")
        parser.add_argument("--dogrulama-modeli", default="gemini-flash-latest")
        parser.add_argument("--parti", type=int, default=40, help="Bir kayıtta okutulan birim sayısı.")
        parser.add_argument(
            "--birim", action="append", default=[],
            help='Yalnız bu birimi yeniden üret ("yüz", "kırk beş"). Birden çok verilebilir.',
        )

    def handle(self, ses, model, dogrulama_modeli, parti, birim, **_):
        self.anahtar = os.environ.get("GEMINI_API_KEY", "").strip()
        if not self.anahtar:
            raise CommandError("GEMINI_API_KEY ortam değişkeni boş.")
        if not shutil.which("ffmpeg"):
            raise CommandError("ffmpeg bulunamadı. Bu komut sunucuda değil, bilgisayarda çalışır.")
        self.ses, self.model, self.dogrulama_modeli = ses, model, dogrulama_modeli
        ana = Path(settings.BASE_DIR) / "tmp" / "rakam_sesleri"

        bilinmeyen = [b for b in birim if b not in rs.SOZLER]
        if bilinmeyen:
            raise CommandError(f"Bilinmeyen birim: {', '.join(bilinmeyen)}")
        uretilecek = birim or list(rs.SOZLER)
        eldeki = {}
        if birim:
            eldeki = self._ana_kopyayi_oku(ana)
            eksik = [b for b in rs.SOZLER if b not in eldeki and b not in birim]
            if eksik:
                raise CommandError(
                    f"Ana kopyada {len(eksik)} birim yok ({eksik[0]}…). Önce --birim olmadan hepsini üretin."
                )

        sonuc, oran = self._uret(uretilecek, parti)
        eldeki.update(sonuc)
        self._ana_kopyaya_yaz(ana, eldeki, oran)

        pcm, konumlar = rs.birlestir([(b, eldeki[b]) for b in rs.SOZLER], oran)
        hedef = Path(settings.BASE_DIR) / "static" / "ses"
        hedef.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "s16le", "-ar", str(oran), "-ac", "1", "-i", "pipe:0",
             "-c:a", "libmp3lame", "-b:a", "40k", str(hedef / "rakamlar.mp3")],
            input=pcm, check=True,
        )
        (hedef / "rakamlar.json").write_text(
            json.dumps({"ses": ses, "model": model, "sozler": konumlar}, ensure_ascii=False, indent=1) + "\n"
        )
        boyut = (hedef / "rakamlar.mp3").stat().st_size // 1024
        self.stdout.write(self.style.SUCCESS(
            f"static/ses/rakamlar.mp3 ({boyut} KB, {len(konumlar)} birim) ve rakamlar.json yazıldı."
        ))

    def _uret(self, birimler, parti):
        """Birimleri okutur. Cızırtılı çıkanı en çok DENEME kez yeniden okutur."""
        sonuc, oran, kalan = {}, 24000, list(birimler)
        for deneme in range(1, DENEME + 1):
            cizirtili = []
            for bas in range(0, len(kalan), parti):
                grup = kalan[bas:bas + parti]
                self.stdout.write(f"Deneme {deneme}: {grup[0]} … {grup[-1]} ({len(grup)} birim)")
                parca_sonuc, oran = self._parti(grup)
                for b, (ses_dizisi, cizirti) in parca_sonuc.items():
                    # Temiz olan alınır. Hiç temizi çıkmazsa ilki kalır, rapora yazılır.
                    if not cizirti or b not in sonuc:
                        sonuc[b] = ses_dizisi
                    if cizirti:
                        cizirtili.append(b)
            if not cizirtili:
                break
            self.stdout.write(f"  Cızırtılı: {', '.join(cizirtili)}")
            kalan = cizirtili
        else:
            self.stdout.write(self.style.WARNING(f"Cızırtı kalan birimler: {', '.join(kalan)}"))
        return sonuc, oran

    def _parti(self, grup):
        cevap = _istek(self.model, {
            "contents": [{"parts": [{"text": "\n".join(_satir(b) for b in grup)}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.ses}}},
            },
        }, self.anahtar)
        try:
            veri = cevap["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm, oran = rs.ses_coz(base64.b64decode(veri["data"]), veri.get("mimeType"))
        except (KeyError, IndexError):
            raise CommandError(f"Ses gelmedi: {json.dumps(cevap)[:600]}")
        except ValueError as hata:
            raise CommandError(str(hata))
        dizi = rs.ornekler(pcm)

        ham_yol = Path(settings.BASE_DIR) / "tmp" / "rakam_sesleri_ham.wav"
        ham_yol.parent.mkdir(exist_ok=True)
        ham_yol.write_bytes(rs.wav(pcm, oran))
        try:
            parcalar = rs.parcalara_bol(dizi, oran)
        except ValueError as hata:
            raise CommandError(f"{hata}. Ham kayıt: {ham_yol}")
        sesler = [rs.kelime_sesi(dizi, b, s, oran) for b, s in parcalar]

        duyulanlar = self._dinlet(sesler, oran)
        try:
            secilen = rs.eslestir([d for d, _ in duyulanlar], grup, sade=_sade)
        except ValueError as hata:
            raise CommandError(f"{hata}. Ham kayıt: {ham_yol}")
        atlanan = len(sesler) - len(secilen)
        self.stdout.write(f"  {len(sesler)} parça, hepsi bulundu{f', {atlanan} fazla parça atlandı' if atlanan else ''}.")
        return {b: (sesler[i], duyulanlar[i][1]) for b, i in zip(grup, secilen)}, oran

    def _dinlet(self, sesler, oran):
        """Her parçayı dinletir: `[(duyulan_metin, cizirti_var_mi), ...]`."""
        parcalar = [{"text": (
            f"Sana sırayla {len(sesler)} kısa Türkçe ses kaydı veriyorum. Her kaydı duyduğun "
            "gibi yazıya dök, sayıları rakamla değil kelimeyle yaz (\"kırk beş\", \"beş yüz\"). "
            "Kayıtta konuşma yoksa boş metin yaz. Her kayıt için ayrıca sesin içinde ya da "
            "sonunda cızırtı, vızıltı, hırıltı, tık ya da uzatılmış ses olup olmadığını söyle. "
            "Kayıt sayısı kadar elemanı olan bir JSON dizi döndür, örnek: "
            '[{"duyulan": "kırk beş", "cizirti": false}].'
        )}]
        for ses_dizisi in sesler:
            dosya = base64.b64encode(rs.wav(rs.baytlar(ses_dizisi), oran)).decode()
            parcalar.append({"inlineData": {"mimeType": "audio/wav", "data": dosya}})
        cevap = _istek(self.dogrulama_modeli, {
            "contents": [{"parts": parcalar}],
            "generationConfig": {"responseMimeType": "application/json"},
        }, self.anahtar)
        try:
            duyulanlar = json.loads(cevap["candidates"][0]["content"]["parts"][0]["text"])
            sonuc = [(str(d.get("duyulan", "")), bool(d.get("cizirti"))) for d in duyulanlar]
        except (KeyError, IndexError, ValueError, AttributeError):
            raise CommandError(f"Dinleme cevabı okunamadı: {json.dumps(cevap)[:600]}")
        if len(sonuc) != len(sesler):
            raise CommandError(f"{len(sesler)} parça dinletildi, {len(sonuc)} cevap geldi: {sonuc}")
        return sonuc

    def _ana_kopyaya_yaz(self, ana, birimler, oran):
        ana.mkdir(parents=True, exist_ok=True)
        for b, ses_dizisi in birimler.items():
            (ana / f"{rs.SOZLER.index(b):03d}.wav").write_bytes(rs.wav(rs.baytlar(ses_dizisi), oran))

    def _ana_kopyayi_oku(self, ana):
        birimler = {}
        for i, b in enumerate(rs.SOZLER):
            yol = ana / f"{i:03d}.wav"
            if yol.exists():
                with wave.open(str(yol)) as dosya:
                    birimler[b] = rs.ornekler(dosya.readframes(dosya.getnframes()))
        return birimler
