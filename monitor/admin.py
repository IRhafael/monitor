from django.contrib import admin
from .models import (Documento, Norma, NormaVigente, 
                    ConfiguracaoColeta, LogExecucao)

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'data_publicacao', 'processado']
    search_fields = ['titulo']
    list_filter = ['processado', 'data_publicacao']

@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'numero', 'data']  
    search_fields = ['numero']
    list_filter = ['tipo']  


# Registrar outros modelos...
admin.site.register(NormaVigente)
admin.site.register(ConfiguracaoColeta)
admin.site.register(LogExecucao)