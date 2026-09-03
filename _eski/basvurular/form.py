from django import forms
from .models import Evrak,EvrakPass,EvrakPassYeni,TurkTarife,YabanciTarife,KontorluYeniHat,YeniTurkTarife,YeniYabanciTarife,FaturaliYeniHat,YeniFaturaliTurkTarife,YeniFaturaliYabanciTarife,Sebekeici,SebekeiciYabanciTarife,SebekeiciTurkTarife,internet,OperatorTarifeleri,Operatorleri,Modemlimi,Telefon


class GecisNormal(forms.ModelForm):
    class Meta:
        model = Evrak
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarifeTurk'].queryset = TurkTarife.objects.all()
        self.fields['tarifeYabanci'].queryset = YabanciTarife.objects.all()




class KontorluYeniform(forms.ModelForm):
    class Meta:
        model = KontorluYeniHat
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarifeTurk'].queryset = YeniTurkTarife.objects.all()
        self.fields['tarifeYabanci'].queryset = YeniYabanciTarife.objects.all()

class FaturaliYeniform(forms.ModelForm):
    class Meta:
        model = FaturaliYeniHat
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarifeTurk'].queryset = YeniFaturaliTurkTarife.objects.all()
        self.fields['tarifeYabanci'].queryset = YeniFaturaliYabanciTarife.objects.all()

class Sebekeiciform(forms.ModelForm):
    class Meta:
        model = Sebekeici
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarifeTurk'].queryset = SebekeiciTurkTarife.objects.all()
        self.fields['tarifeYabanci'].queryset = SebekeiciYabanciTarife.objects.all()

class internetform(forms.ModelForm):
    class Meta:
        model = internet
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['operatortarife'].queryset = OperatorTarifeleri.objects.all()
        self.fields['Operatorler'].queryset = Operatorleri.objects.all()
        self.fields['sabithat'].queryset = Telefon.objects.all()
        self.fields['modemolsunmu'].queryset = Modemlimi.objects.all()

class GecisPass(forms.ModelForm):
    class Meta:
        model = EvrakPassYeni
        fields = ['user','isim', 'soyisim', 'pasaportno',  'operator', 'simimei','irtibat', 'adres','pass1', 'pass2', 'ikametgah']
