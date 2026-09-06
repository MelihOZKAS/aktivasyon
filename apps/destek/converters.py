"""URL yol dönüştürücüsü."""


class TalepDonusturucu:
    """Talep referansı: 8 karakter, karışması olası harfler yok.

    Desen dar tutulduğu için `/destek/yeni/` gibi sabit yollarla çakışmaz;
    sıralamaya bağlı kalmayız.
    """

    regex = "[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}"

    def to_python(self, deger):
        return deger

    def to_url(self, deger):
        return str(deger)
