"""Bildirim davranışı: işin önüne asla geçmemeli."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.basvurular.models import Basvuru, BasvuruDurumu
from apps.bildirim import telegram
from apps.finans.models import Cuzdan
from apps.katalog.models import BasvuruKategorisi, Operator

AYARLAR = {
    "TELEGRAM_BOT_TOKEN": "deneme:anahtar",
    "TELEGRAM_SOHBET_ID": "@grup",
    # Testte gönderim eşzamanlı olsun ki sonucu ölçebilelim.
    "TELEGRAM_ARKA_PLAN": False,
}


class TelegramTestleri(TestCase):
    def setUp(self):
        self.beklemede = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        self.aktif = BasvuruDurumu.objects.create(
            ad="Aktif", slug="aktif", hakedis_tetikler=True, bildirim_gonder=True
        )
        self.islemde = BasvuruDurumu.objects.create(
            ad="İşlemde", slug="islemde", bildirim_gonder=False
        )
        self.bayi = User.objects.create_user("bayi", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.operator = Operator.objects.create(ad="Vodafone")
        self.kategori = BasvuruKategorisi.objects.create(ad="Faturalı Yeni Hat")

    def _basvuru(self, durum=None):
        return Basvuru.objects.create(
            bayi=self.bayi, kategori=self.kategori, operator=self.operator,
            isim="Ayşe", soyisim="Demir", kimlik_no="12345678901",
            irtibat="5551112233", durum=durum or self.beklemede,
        )

    def test_yapilandirilmamissa_sessizce_atlanir(self):
        with override_settings(
            TELEGRAM_BOT_TOKEN="", TELEGRAM_SOHBET_ID="", TELEGRAM_ARKA_PLAN=False
        ):
            with patch.object(telegram, "_gonder") as sahte:
                with self.captureOnCommitCallbacks(execute=True):
                    self._basvuru()
            sahte.assert_not_called()

    @override_settings(**AYARLAR)
    def test_yeni_basvuruda_bildirim_gider(self):
        with patch.object(telegram, "_gonder") as sahte:
            with self.captureOnCommitCallbacks(execute=True):
                basvuru = self._basvuru()
        sahte.assert_called_once()
        metin = sahte.call_args[0][0]
        self.assertIn("Yeni başvuru", metin)
        self.assertIn(basvuru.referans_no, metin)
        self.assertIn("Ayşe Demir", metin)

    @override_settings(**AYARLAR)
    def test_yalnizca_isaretli_durumlar_bildirir(self):
        basvuru = self._basvuru()

        with patch.object(telegram, "_gonder") as sahte:
            with self.captureOnCommitCallbacks(execute=True):
                basvuru.durum = self.islemde
                basvuru.save()
        sahte.assert_not_called()

        with patch.object(telegram, "_gonder") as sahte:
            with self.captureOnCommitCallbacks(execute=True):
                basvuru.durum = self.aktif
                basvuru.save()
        sahte.assert_called_once()
        self.assertIn("Aktif", sahte.call_args[0][0])

    @override_settings(**AYARLAR)
    def test_telegram_cokse_bile_basvuru_kaydedilir(self):
        """Eski sistemde Telegram hatası başvuruyu 500'e düşürüyordu."""
        with patch.object(telegram, "_gonder", side_effect=OSError("bağlanılamadı")):
            with self.captureOnCommitCallbacks(execute=True):
                basvuru = self._basvuru()

        self.assertTrue(Basvuru.objects.filter(pk=basvuru.pk).exists())

    @override_settings(**AYARLAR)
    def test_geri_alinan_kaydin_bildirimi_gitmez(self):
        from django.db import transaction

        with patch.object(telegram, "_gonder") as sahte:
            try:
                with transaction.atomic():
                    self._basvuru()
                    raise RuntimeError("iptal")
            except RuntimeError:
                pass
        sahte.assert_not_called()

    @override_settings(**AYARLAR)
    def test_musteri_adi_kacislanir(self):
        """Mesaja giren kullanıcı verisi işaretlemeyi bozmamalı."""
        with patch.object(telegram, "_gonder") as sahte:
            with self.captureOnCommitCallbacks(execute=True):
                Basvuru.objects.create(
                    bayi=self.bayi, kategori=self.kategori, operator=self.operator,
                    isim="<b>Ali", soyisim="Veli</b>", kimlik_no="1",
                    irtibat="5551112233", durum=self.beklemede,
                )
        metin = sahte.call_args[0][0]
        self.assertIn("&lt;b&gt;Ali", metin)
        self.assertNotIn("<b>Ali", metin)
