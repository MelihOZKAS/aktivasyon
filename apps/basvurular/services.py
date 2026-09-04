"""Başvuru yan işlemleri."""

import logging

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

    # Kayıtları silmek yeterli: post_delete sinyali dosyaları da commit
    # sonrasında diskten siliyor (apps/dosya.py).
    basvuru.belgeler.all().delete()
    model.objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
    basvuru.belgeler_silindi = True

    logger.info(
        "Başvuru %s sonuçlandı, %s belge silindi.", basvuru.referans_no, len(belgeler)
    )
    return len(belgeler)
