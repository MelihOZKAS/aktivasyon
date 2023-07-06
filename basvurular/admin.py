from django.contrib import admin
from .models import Evrak, EvrakPass,TurkTarife,YabanciTarife,YeniTurkTarife,YeniYabanciTarife,KontorluYeniHat,FaturaliYeniHat,YeniFaturaliYabanciTarife,YeniFaturaliTurkTarife,Sebekeici,SebekeiciTurkTarife,SebekeiciYabanciTarife,Duyuru,OperatorTarifeleri,Operatorleri


class EvrakAdmin(admin.ModelAdmin):
    list_display = ('id', 'isim', 'soyisim', 'tc', 'numara', 'irtibat', 'operatoru', 'gececegi_operator', 'aks')
    list_filter = ('operatoru', 'gececegi_operator')
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')

class YeniKontorluAdmin(admin.ModelAdmin):
    list_display = ('id', 'isim', 'soyisim', 'tc',  'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru', )
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')

class YeniFaturaliAdmin(admin.ModelAdmin):
    list_display = ('id', 'isim', 'soyisim', 'tc',  'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru', )
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')

class SebekeiciAdmin(admin.ModelAdmin):
    list_display = ('id', 'isim', 'soyisim', 'tc', 'numara', 'irtibat', 'operatoru', 'aks')
    list_filter = ('operatoru',)
    search_fields = ('isim', 'soyisim', 'tc', 'numara', 'irtibat')

class EvrakPassAdmin(admin.ModelAdmin):
    list_display = ('id', 'isim', 'soyisim','pasaportno','numara','operator','gececegi_operator','irtibat')
    list_filter = ('operator', 'gececegi_operator')
    search_fields = ('isim', 'soyisim', 'numara', 'irtibat')

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






class YeniFaturaliTurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')
class YeniFaturaliYabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


class SebekeiciTurkTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')
class SebekeiciYabanciTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')





class AdslTarifeAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad','operatoru')
class ADSLOperatorAdmin(admin.ModelAdmin):
    list_display = ('id', 'ad')


admin.site.register(Evrak, EvrakAdmin)
admin.site.register(EvrakPass, EvrakPassAdmin)
admin.site.register(KontorluYeniHat, YeniKontorluAdmin)
admin.site.register(FaturaliYeniHat, YeniFaturaliAdmin)
admin.site.register(Sebekeici, SebekeiciAdmin)




admin.site.register(TurkTarife, TurkTarifeAdmin)
admin.site.register(YabanciTarife, YabanciTarifeAdmin)

admin.site.register(YeniTurkTarife, YeniTurkTarifeAdmin)
admin.site.register(YeniYabanciTarife, YeniYabanciTarifeAdmin)

admin.site.register(YeniFaturaliTurkTarife,YeniFaturaliTurkTarifeAdmin)
admin.site.register(YeniFaturaliYabanciTarife,YeniFaturaliYabanciTarifeAdmin)

admin.site.register(SebekeiciTurkTarife,SebekeiciTurkTarifeAdmin)
admin.site.register(SebekeiciYabanciTarife,SebekeiciYabanciTarifeAdmin)


admin.site.register(OperatorTarifeleri,AdslTarifeAdmin)
admin.site.register(Operatorleri,ADSLOperatorAdmin)