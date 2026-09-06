"""Destek talebi akışı: bayi yazar, yönetim yanıtlar, yazışma kayda geçer."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.destek.models import DestekTalebi, TalepDurumu
from apps.finans.models import Cuzdan


class DestekAkisi(TestCase):
    def setUp(self):
        self.bayi = User.objects.create_user("5551112233", password="parola12345")
        Cuzdan.objects.create(bayi=self.bayi)
        self.digeri = User.objects.create_user("5559998877", password="parola12345")
        Cuzdan.objects.create(bayi=self.digeri)
        self.yonetici = User.objects.create_superuser("yonetici", password="Panel-2026x")

    def _talep_ac(self, konu="Bakiyem yüklenmedi", icerik="Havaleyi dün yaptım."):
        self.client.force_login(self.bayi)
        self.client.post(
            reverse("destek:yeni"), {"konu": konu, "icerik": icerik, "basvuru": ""}
        )
        return DestekTalebi.objects.get()

    def test_bayi_talep_acar_ilk_mesaj_yazilir(self):
        talep = self._talep_ac()

        self.assertEqual(talep.konu, "Bakiyem yüklenmedi")
        self.assertEqual(talep.mesajlar.count(), 1)
        self.assertFalse(talep.mesajlar.get().personelden)
        self.assertEqual(talep.durum, TalepDurumu.ACIK)
        # Son sözü bayi söyledi: sıra yönetimde.
        self.assertTrue(talep.yanit_bekliyor)
        self.assertIsNotNone(talep.son_mesaj_tarihi)

    def test_bos_mesaj_kaydedilmez(self):
        self.client.force_login(self.bayi)
        self.client.post(
            reverse("destek:yeni"), {"konu": "Konu", "icerik": "   ", "basvuru": ""}
        )

        self.assertEqual(DestekTalebi.objects.count(), 0)

    def test_baskasinin_talebi_gorunmez(self):
        talep = self._talep_ac()

        self.client.force_login(self.digeri)
        yanit = self.client.get(talep.get_absolute_url())

        self.assertEqual(yanit.status_code, 404)

    def test_listede_yalnizca_kendi_talepleri(self):
        self._talep_ac(konu="Benim konum")

        self.client.force_login(self.digeri)
        icerik = self.client.get(reverse("destek:liste")).content.decode()

        self.assertNotIn("Benim konum", icerik)

    def test_bayi_yanit_yazinca_sira_yonetime_gecer(self):
        talep = self._talep_ac()
        from apps.destek.services import mesaj_ekle

        mesaj_ekle(talep, self.yonetici, "Kontrol ediyoruz.", personelden=True)
        talep.refresh_from_db()
        self.assertFalse(talep.yanit_bekliyor)

        self.client.force_login(self.bayi)
        self.client.post(talep.get_absolute_url(), {"icerik": "Teşekkürler."})

        talep.refresh_from_db()
        self.assertTrue(talep.yanit_bekliyor)
        self.assertEqual(talep.mesajlar.count(), 3)

    def test_bayi_talebi_kapatir(self):
        talep = self._talep_ac()

        self.client.force_login(self.bayi)
        self.client.post(reverse("destek:kapat", args=[talep.referans_no]))

        talep.refresh_from_db()
        self.assertEqual(talep.durum, TalepDurumu.KAPALI)

    def test_kapali_talebe_yazmak_yeniden_acar(self):
        """Konuşma devam ediyorsa kayıt kapalı görünmemeli."""
        from apps.destek.services import mesaj_ekle

        talep = self._talep_ac()
        talep.durum = TalepDurumu.KAPALI
        talep.save(update_fields=["durum"])

        mesaj_ekle(talep, self.yonetici, "Bir sorum var.", personelden=True)

        talep.refresh_from_db()
        self.assertEqual(talep.durum, TalepDurumu.ACIK)

    def test_giris_yapmayan_giremez(self):
        yanit = self.client.get(reverse("destek:liste"))

        self.assertEqual(yanit.status_code, 302)
        self.assertIn("/giris-yap/", yanit["Location"])

    def test_ilgili_basvuru_yalnizca_kendi_kayitlarindan_secilir(self):
        """Başkasının referansı elle gönderilse de bağlanmaz."""
        from apps.basvurular.models import Basvuru, BasvuruDurumu
        from apps.katalog.models import BasvuruKategorisi

        durum = BasvuruDurumu.objects.create(
            ad="Beklemede", slug="beklemede", baslangic_durumu=True
        )
        kategori = BasvuruKategorisi.objects.create(ad="MNT")
        baskasinin = Basvuru.objects.create(
            bayi=self.digeri, kategori=kategori, isim="Gizli", soyisim="Kayıt",
            kimlik_no="9", irtibat="5559998877", durum=durum,
        )

        self.client.force_login(self.bayi)
        self.client.post(
            reverse("destek:yeni"),
            {"konu": "Konu", "icerik": "Mesaj", "basvuru": baskasinin.pk},
        )

        self.assertEqual(DestekTalebi.objects.count(), 0)

    def test_rozet_yanit_bekleyenleri_sayar(self):
        from apps import rozetler
        from apps.destek.services import mesaj_ekle

        talep = self._talep_ac()
        self.assertEqual(rozetler.yanit_bekleyen_talepler(None), "1")

        mesaj_ekle(talep, self.yonetici, "Yanıt.", personelden=True)
        self.assertEqual(rozetler.yanit_bekleyen_talepler(None), "")

    def test_yonetim_panelinden_yanit_yazilir(self):
        """Yanıt servisten geçmeli: talebin özet alanları güncellensin."""
        talep = self._talep_ac()
        mesaj = talep.mesajlar.get()

        self.client.force_login(self.yonetici)
        self.client.post(
            reverse("admin:destek_destektalebi_change", args=[talep.pk]),
            {
                "bayi": self.bayi.pk, "konu": talep.konu, "basvuru": "",
                "durum": TalepDurumu.ACIK,
                "mesajlar-TOTAL_FORMS": "2",
                "mesajlar-INITIAL_FORMS": "1",
                "mesajlar-MIN_NUM_FORMS": "0",
                "mesajlar-MAX_NUM_FORMS": "1000",
                "mesajlar-0-id": mesaj.pk,
                "mesajlar-0-talep": talep.pk,
                "mesajlar-0-icerik": mesaj.icerik,
                "mesajlar-1-id": "",
                "mesajlar-1-talep": talep.pk,
                "mesajlar-1-icerik": "Bakiyeniz yüklendi.",
            },
            follow=True,
        )

        talep.refresh_from_db()
        self.assertEqual(talep.mesajlar.count(), 2)
        yeni = talep.mesajlar.order_by("tarih").last()
        self.assertTrue(yeni.personelden)
        self.assertEqual(yeni.gonderen, self.yonetici)
        # Sıra bayiye geçti: rozetten düşmeli.
        self.assertFalse(talep.yanit_bekliyor)

    def test_talep_acilinca_bildirim_gonderilir(self):
        from unittest.mock import patch

        with patch("apps.bildirim.telegram.mesaj_gonder") as bildirim:
            self._talep_ac(konu="Telegram konusu")

        self.assertTrue(bildirim.called)
        self.assertIn("Telegram konusu", bildirim.call_args.args[0])
