from django.contrib import admin
from .models import (
    Documento, NormaVigente, ConfiguracaoColeta, 
    LogExecucao, TermoMonitorado
)

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'data_publicacao', 'processado', 'relevante_contabil']
    search_fields = ['titulo', 'resumo', 'texto_completo']
    list_filter = ['processado', 'relevante_contabil', 'data_publicacao']
    filter_horizontal = ['normas_relacionadas']
    date_hierarchy = 'data_publicacao'
    ordering = ['-data_publicacao']

@admin.register(NormaVigente)
class NormaVigenteAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'numero', 'situacao', 'data_verificacao']
    search_fields = ['numero', 'descricao']
    list_filter = ['tipo', 'situacao']
    ordering = ['tipo', 'numero']

@admin.register(ConfiguracaoColeta)
class ConfiguracaoColetaAdmin(admin.ModelAdmin):
    list_display = ['ativa', 'intervalo_horas', 'max_documentos', 'ultima_execucao', 'proxima_execucao']
    list_filter = ['ativa']
    search_fields = ['email_notificacao']

@admin.register(LogExecucao)
class LogExecucaoAdmin(admin.ModelAdmin):
    list_display = ['tipo_execucao', 'status', 'data_inicio', 'data_fim', 'documentos_coletados', 'normas_coletadas']
    list_filter = ['tipo_execucao', 'status']
    date_hierarchy = 'data_inicio'
    ordering = ['-data_inicio']

@admin.register(TermoMonitorado)
class TermoMonitoradoAdmin(admin.ModelAdmin):
    list_display = ['termo', 'tipo', 'ativo', 'data_cadastro']
    list_filter = ['tipo', 'ativo']
    search_fields = ['termo']
    actions = ['ativar_termos', 'desativar_termos']

    def ativar_termos(self, request, queryset):
        queryset.update(ativo=True)
    ativar_termos.short_description = "Ativar termos selecionados"

    def desativar_termos(self, request, queryset):
        queryset.update(ativo=False)
    desativar_termos.short_description = "Desativar termos selecionados"
