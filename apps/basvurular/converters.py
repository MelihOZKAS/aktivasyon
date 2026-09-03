"""URL yol dönüştürücüleri."""


class ReferansDonusturucu:
    """Başvuru referans numarası: 10 karakter, karışması olası harfler yok.

    Deseni dar tuttuğumuz için `/basvuru/yeni/` gibi sabit yollarla
    çakışması mümkün değildir; sıralama kazasına bağlı kalmayız.
    """

    regex = "[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{10}"

    def to_python(self, deger):
        return deger

    def to_url(self, deger):
        return str(deger)
