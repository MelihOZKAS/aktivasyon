from django.contrib import admin
from .models import Evrak, EvrakPass, TurkTarife, YabanciTarife, YeniTurkTarife, YeniYabanciTarife, KontorluYeniHat, \
    FaturaliYeniHat, YeniFaturaliYabanciTarife, YeniFaturaliTurkTarife, Sebekeici, SebekeiciTurkTarife, \
    SebekeiciYabanciTarife, Duyuru, OperatorTarifeleri, Operatorleri, internet, Modemlimi, Telefon
from django.utils.html import format_html


class EvrakAdmin(admin.ModelAdmin):
    list_display = ('id' , 'resim' ,  'isim','soyisim', 'tc', 'numara', 'irtibat', 'operatoru', 'gececegi_operator', 'aks')
    list_filter = ('operatoru', 'gececegi_operator')
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'



class YeniKontorluAdmin(admin.ModelAdmin):
    list_display = ('id', 'resim' , 'isim', 'soyisim', 'tc', 'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru',)
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'


class YeniFaturaliAdmin(admin.ModelAdmin):
    list_display = ('id', 'resim' , 'isim', 'soyisim', 'tc', 'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru',)
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'


class SebekeiciAdmin(admin.ModelAdmin):
    list_display = ('id', 'resim','isim', 'soyisim', 'tc', 'numara', 'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru',)
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'


class internetAdmin(admin.ModelAdmin):
    list_display = ('id', 'resim', 'isim', 'soyisim', 'tc', 'irtibat', 'Operatorler', 'aks',)
    list_filter = ('Operatorler','aktivasyon_durumu','odeme_durumu','user__username',)
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat',)
    list_display_links = ('id','resim','isim')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'


class EvrakPassAdmin(admin.ModelAdmin):
    list_display = ('id','resim',  'isim', 'soyisim', 'pasaportno', 'numara', 'operator', 'gececegi_operator', 'irtibat')
    list_filter = ('operator', 'gececegi_operator')
    search_fields = ('isim', 'soyisim', 'numara', 'irtibat')
    list_display_links = ('id','resim','isim',)
    readonly_fields = ('user',)
    def resim(self, obj):
        if obj.aktivasyon_durumu == 'Beklemede':
            return format_html('<img src="/static/panel/img/Durumlar/new.png" width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Aktif':
            return format_html('<img src="/static/panel/img/Durumlar/basarili.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Hatalı':
            return format_html('<img src="/static/panel/img/Durumlar/false.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'İşlemde':
            return format_html('<img src="/static/panel/img/Durumlar/islemde.png"width="32" height="32" />')
        elif obj.aktivasyon_durumu == 'Eksik Evrak':
            return format_html('<img src="/static/panel/img/Durumlar/eksik.png"width="32" height="32" />')

    resim.short_description = 'Durum'




class TurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class YabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class DuyuruAdmin(admin.ModelAdmin):
    list_display = ('baslik', 'tarih')
    search_fields = ('baslik', 'tarih')
    ordering = ('-tarih',)
    fields = ('baslik', 'icerik')


admin.site.register(Duyuru, DuyuruAdmin)


class YeniTurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class YeniYabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class TelefonAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class ModemTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class YeniFaturaliTurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class YeniFaturaliYabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class SebekeiciTurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class SebekeiciYabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class AdslTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad', 'operatoru')


class ADSLOperatorAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


admin.site.register(Evrak, EvrakAdmin)
admin.site.register(EvrakPass, EvrakPassAdmin)
admin.site.register(KontorluYeniHat, YeniKontorluAdmin)
admin.site.register(FaturaliYeniHat, YeniFaturaliAdmin)
admin.site.register(Sebekeici, SebekeiciAdmin)
admin.site.register(internet, internetAdmin)

admin.site.register(Telefon, TelefonAdmin)
admin.site.register(Modemlimi, ModemTarifeAdmin)

admin.site.register(TurkTarife, TurkTarifeAdmin)
admin.site.register(YabanciTarife, YabanciTarifeAdmin)

admin.site.register(YeniTurkTarife, YeniTurkTarifeAdmin)
admin.site.register(YeniYabanciTarife, YeniYabanciTarifeAdmin)

admin.site.register(YeniFaturaliTurkTarife, YeniFaturaliTurkTarifeAdmin)
admin.site.register(YeniFaturaliYabanciTarife, YeniFaturaliYabanciTarifeAdmin)

admin.site.register(SebekeiciTurkTarife, SebekeiciTurkTarifeAdmin)
admin.site.register(SebekeiciYabanciTarife, SebekeiciYabanciTarifeAdmin)

admin.site.register(OperatorTarifeleri, AdslTarifeAdmin)
admin.site.register(Operatorleri, ADSLOperatorAdmin)
