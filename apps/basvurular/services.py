"""Başvuru yan işlemleri."""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def belgeleri_sil(basvuru):
    """Başvurunun kimlik görüntülerini kayıttan ve diskten siler.

    Kimlik ve pasaport görüntüleri kişisel veridir; başvurunun işi bittiği
    anda (bakiye yüklendi ya da iptal edilip geri alındı) saklanmaları için
    sebep kalmaz. Başvuru kaydı, para geçmişi ve hakediş bilgisi durur;
    yalnızca görüntüler gider.

    Dosyalar veritabanı değişikliği **commit edildikten sonra** silinir.
    Aksi hâlde transaction geri alınırsa dosya çoktan gitmiş, satır geri
    gelmiş olur; kayıt olmayan bir dosyayı işaret eder.
    """
    belgeler = list(basvuru.belgeler.all())
    model = type(basvuru)

    if not belgeler:
        # Kayıt yoksa bile bayrağı işaretle: bir daha aranmasın.
        model.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
        basvuru.belgeler_silindi = True
        return 0

    yollar = [b.dosya for b in belgeler if b.dosya]
    basvuru.belgeler.all().delete()
    model.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
    basvuru.belgeler_silindi = True

    def diskten_sil():
        for dosya in yollar:
            try:
                dosya.delete(save=False)
            except OSError as hata:
                # Kayıt gitti ama dosya kaldı: sahipsiz dosya olarak günlüğe
                # düşer, `sahipsiz_belgeler` komutuyla temizlenebilir.
                logger.error(
                    "Belge dosyası silinemedi (%s): %s", dosya.name, hata
                )

    transaction.on_commit(diskten_sil)

    logger.info(
        "Başvuru %s sonuçlandı, %s belge silindi.", basvuru.referans_no, len(belgeler)
    )
    return len(belgeler)
