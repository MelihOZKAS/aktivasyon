"""Başvuru yan işlemleri."""

import logging

logger = logging.getLogger(__name__)


def belgeleri_sil(basvuru):
    """Başvurunun kimlik görüntülerini diskten ve kayıttan siler.

    Kimlik ve pasaport görüntüleri kişisel veridir; başvurunun işi bittiği
    anda (bakiye yüklendi ya da iptal edilip geri alındı) saklanmaları için
    bir sebep kalmaz. Başvuru kaydı, para geçmişi ve hakediş bilgisi durur;
    yalnızca görüntüler gider.
    """
    belgeler = list(basvuru.belgeler.all())
    if not belgeler:
        # Kayıt yoksa bile bayrağı işaretle: bir daha aranmasın.
        type(basvuru).objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
        return 0

    for belge in belgeler:
        if belge.dosya:
            belge.dosya.delete(save=False)
    basvuru.belgeler.all().delete()
    type(basvuru).objects.filter(pk=basvuru.pk).update(belgeler_silindi=True)
    basvuru.belgeler_silindi = True

    logger.info(
        "Başvuru %s sonuçlandı, %s belge silindi.", basvuru.referans_no, len(belgeler)
    )
    return len(belgeler)
