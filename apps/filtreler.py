"""Yönetim panelinde kullanılan ortak liste filtreleri."""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import EMPTY_VALUES
from django.utils import timezone
from django.utils.dateparse import parse_date
from unfold.contrib.filters.admin import RangeDateFilter


class GunAraligiFiltresi(RangeDateFilter):
    """Tarih aralığı filtresi; bitiş günü aralığa **dahildir**.

    unfold'un hazır aralık filtresi seçilen tarihi olduğu gibi `__lte` ile
    karşılaştırıyor. Alan `DateTimeField` olduğunda "5 Eylül" gece yarısı
    demek oluyor ve o günün bütün hareketleri dışarıda kalıyor: yönetici
    "1–5 Eylül" seçip 5 Eylül'ün tahsilatını göremiyordu.

    Burada bitiş, ertesi günün başlangıcından **önce** olarak kurulur; ayrıca
    tarihler zaman dilimine bağlanır, yoksa Django saf tarihi karşılaştırırken
    uyarı verir ve sınırlar bir gün kayabilir.
    """

    def _gun_baslangici(self, deger):
        gun = parse_date(deger)
        if gun is None:
            return None
        an = datetime.combine(gun, time.min)
        return timezone.make_aware(an) if timezone.is_naive(an) else an

    def queryset(self, request, queryset):
        filtreler = {}

        baslangic = self.used_parameters.get(f"{self.parameter_name}_from")
        if baslangic not in EMPTY_VALUES and isinstance(baslangic, str):
            an = self._gun_baslangici(baslangic)
            if an is not None:
                filtreler[f"{self.parameter_name}__gte"] = an

        bitis = self.used_parameters.get(f"{self.parameter_name}_to")
        if bitis not in EMPTY_VALUES and isinstance(bitis, str):
            an = self._gun_baslangici(bitis)
            if an is not None:
                filtreler[f"{self.parameter_name}__lt"] = an + timedelta(days=1)

        try:
            return queryset.filter(**filtreler)
        except (ValueError, ValidationError):
            return None
