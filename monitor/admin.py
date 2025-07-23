from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count
from django.utils import timezone
from .models import (
    TermoMonitorado, NormaVigente, Documento,
    RelatorioGerado, ConfiguracaoColeta, LogExecucao
)
import json


class TermoMonitoradoAdmin(admin.ModelAdmin):
    list_display = ['termo', 'tipo', 'prioridade', 'ativo', 'data_cadastro']
    list_filter = ['tipo', 'ativo', 'prioridade']
    search_fields = ['termo', 'variacoes']
    list_editable = ['prioridade', 'ativo']
    ordering = ['-prioridade', 'termo']
    actions = ['ativar_termos', 'desativar_termos']

    def ativar_termos(self, request, queryset):
        updated = queryset.update(ativo=True)
        self.message_user(request, f"{updated} termos ativados com sucesso.")
    ativar_termos.short_description = "Ativar termos selecionados"

    def desativar_termos(self, request, queryset):
        updated = queryset.update(ativo=False)
        self.message_user(request, f"{updated} termos desativados com sucesso.")
    desativar_termos.short_description = "Desativar termos selecionados"

admin.site.register(TermoMonitorado, TermoMonitoradoAdmin)

class NormaVigenteAdmin(admin.ModelAdmin):
    list_display = [
        'tipo', 'numero', 'situacao_formatada', 
        'data_verificacao', 'documentos_count'
    ]
    list_filter = ['tipo', 'situacao', 'fonte']
    search_fields = ['numero', 'descricao']
    readonly_fields = ['data_cadastro']
    ordering = ['tipo', 'numero']
    actions = ['marcar_como_vigente', 'marcar_como_revogada']

    def situacao_formatada(self, obj):
        color = {
            'VIGENTE': 'green',
            'REVOGADA': 'red',
            'ALTERADA': 'orange',
            'A_VERIFICAR': 'gray'
        }.get(obj.situacao, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_situacao_display()
        )
    situacao_formatada.short_description = 'Situação'
    situacao_formatada.admin_order_field = 'situacao'

    def documentos_count(self, obj):
        count = obj.documentos.count()
        url = (
            reverse('admin:monitor_documento_changelist') 
            + f'?normas_relacionadas__id__exact={obj.id}'
        )
        return format_html('<a href="{}">{}</a>', url, count)
    documentos_count.short_description = 'Documentos'

    def marcar_como_vigente(self, request, queryset):
        updated = queryset.update(situacao='VIGENTE', data_verificacao=timezone.now())
        self.message_user(request, f"{updated} normas marcadas como vigentes.")
    marcar_como_vigente.short_description = "Marcar como vigentes"

    def marcar_como_revogada(self, request, queryset):
        updated = queryset.update(situacao='REVOGADA', data_verificacao=timezone.now())
        self.message_user(request, f"{updated} normas marcadas como revogadas.")
    marcar_como_revogada.short_description = "Marcar como revogadas"

admin.site.register(NormaVigente, NormaVigenteAdmin)

class DocumentoAdmin(admin.ModelAdmin):
    list_display = [
        'titulo', 'data_publicacao', 'processado_status', 
        'relevante_status', 'normas_count'
    ]
    list_filter = [
        'processado', 'relevante_contabil', 
        'data_publicacao', 'arquivo_removido'
    ]
    search_fields = ['titulo', 'resumo', 'texto_completo', 'assunto']
    filter_horizontal = ['normas_relacionadas']
    date_hierarchy = 'data_publicacao'
    ordering = ['-data_publicacao']
    readonly_fields = ['data_coleta', 'metadata_preview']
    actions = ['processar_documentos', 'marcar_como_relevante']

    def processado_status(self, obj):
        color = 'green' if obj.processado else 'red'
        text = 'Sim' if obj.processado else 'Não'
        return format_html('<span style="color: {};">{}</span>', color, text)
    processado_status.short_description = 'Processado'
    processado_status.admin_order_field = 'processado'

    def relevante_status(self, obj):
        if not obj.processado:
            return '-'
        color = 'green' if obj.relevante_contabil else 'red'
        text = 'Sim' if obj.relevante_contabil else 'Não'
        return format_html('<span style="color: {};">{}</span>', color, text)
    relevante_status.short_description = 'Relevante'
    relevante_status.admin_order_field = 'relevante_contabil'

    def normas_count(self, obj):
        count = obj.normas_relacionadas.count()
        url = reverse('admin:monitor_normavigente_changelist') + f'?documentos__id__exact={obj.id}'
        return format_html('<a href="{}">{}</a>', url, count)
    normas_count.short_description = 'Normas'

    def metadata_preview(self, obj):
        if obj.metadata:
            return format_html('<pre>{}</pre>', json.dumps(obj.metadata, indent=2))
        return '-'
    metadata_preview.short_description = 'Metadados'

    def processar_documentos(self, request, queryset):
        from .utils.pdf_processor import PDFProcessor
        processor = PDFProcessor()
        success = 0
        for doc in queryset:
            if processor.process_document(doc):
                success += 1
        self.message_user(
            request, 
            f"{success} de {queryset.count()} documentos processados com sucesso."
        )
    processar_documentos.short_description = "Processar documentos selecionados"

    def marcar_como_relevante(self, request, queryset):
        updated = queryset.update(relevante_contabil=True)
        self.message_user(request, f"{updated} documentos marcados como relevantes.")
    marcar_como_relevante.short_description = "Marcar como relevantes"

admin.site.register(Documento, DocumentoAdmin)

class RelatorioGeradoAdmin(admin.ModelAdmin):
    list_display = [
        'tipo_formatado', 'formato', 'data_criacao', 
        'gerado_por', 'downloads', 'download_link'
    ]
    list_filter = ['tipo', 'formato']
    search_fields = ['parametros']
    date_hierarchy = 'data_criacao'
    ordering = ['-data_criacao']
    readonly_fields = ['data_criacao', 'parametros_preview']

    def tipo_formatado(self, obj):
        return obj.get_tipo_display()
    tipo_formatado.short_description = 'Tipo'
    tipo_formatado.admin_order_field = 'tipo'

    def download_link(self, obj):
        url = reverse('admin:monitor_relatoriogerado_download', args=[obj.id])
        return format_html('<a href="{}">Download</a>', url)
    download_link.short_description = 'Ação'

    def parametros_preview(self, obj):
        if obj.parametros:
            return format_html('<pre>{}</pre>', json.dumps(obj.parametros, indent=2))
        return '-'
    parametros_preview.short_description = 'Parâmetros'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/download/',
                self.admin_site.admin_view(self.download_report),
                name='monitor_relatoriogerado_download',
            ),
        ]
        return custom_urls + urls

    def download_report(self, request, object_id, *args, **kwargs):
        from django.http import FileResponse
        report = self.get_object(request, object_id)
        response = FileResponse(report.caminho_arquivo.open('rb'))
        response['Content-Disposition'] = f'attachment; filename="{report.nome_arquivo()}"'
        
        # Atualiza contador
        report.downloads += 1
        report.save()
        
        return response

admin.site.register(RelatorioGerado, RelatorioGeradoAdmin)

class ConfiguracaoColetaAdmin(admin.ModelAdmin):
    list_display = [
        'ativa_status', 'intervalo_horas', 'max_documentos',
        'verificar_vigencias', 'dias_retroativos'
    ]
    list_editable = ['intervalo_horas', 'max_documentos', 'dias_retroativos']
    actions = ['ativar_coleta', 'desativar_coleta']

    def ativa_status(self, obj):
        color = 'green' if obj.ativa else 'red'
        text = 'Ativa' if obj.ativa else 'Inativa'
        return format_html('<span style="color: {};">{}</span>', color, text)
    ativa_status.short_description = 'Status'
    ativa_status.admin_order_field = 'ativa'

    def ativar_coleta(self, request, queryset):
        updated = queryset.update(ativa=True)
        self.message_user(request, f"{updated} configurações ativadas.")
    ativar_coleta.short_description = "Ativar coleta automática"

    def desativar_coleta(self, request, queryset):
        updated = queryset.update(ativa=False)
        self.message_user(request, f"{updated} configurações desativadas.")
    desativar_coleta.short_description = "Desativar coleta automática"

    def has_add_permission(self, request):
        return not ConfiguracaoColeta.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(ConfiguracaoColeta, ConfiguracaoColetaAdmin)

class LogExecucaoAdmin(admin.ModelAdmin):
    list_display = [
        'tipo_execucao_formatado', 'status_formatado',
        'data_inicio', 'duracao_formatada', 'usuario'
    ]
    list_filter = ['tipo_execucao', 'status']
    search_fields = ['mensagem', 'erro']
    date_hierarchy = 'data_inicio'
    ordering = ['-data_inicio']
    readonly_fields = ['data_inicio', 'data_fim', 'duracao', 'traceback_preview']

    def tipo_execucao_formatado(self, obj):
        return obj.get_tipo_execucao_display()
    tipo_execucao_formatado.short_description = 'Tipo'
    tipo_execucao_formatado.admin_order_field = 'tipo_execucao'

    def status_formatado(self, obj):
        color = {
            'SUCESSO': 'green',
            'ERRO': 'red',
            'PARCIAL': 'orange'
        }.get(obj.status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_status_display()
        )
    status_formatado.short_description = 'Status'
    status_formatado.admin_order_field = 'status'

    def duracao_formatada(self, obj):
        if obj.duracao:
            total_seconds = int(obj.duracao.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}h {minutes}m {seconds}s"
        return '-'
    duracao_formatada.short_description = 'Duração'
    duracao_formatada.admin_order_field = 'duracao'

    def traceback_preview(self, obj):
        if obj.traceback:
            return format_html('<pre>{}</pre>', obj.traceback)
        return '-'
    traceback_preview.short_description = 'Detalhes do Erro'

admin.site.register(LogExecucao, LogExecucaoAdmin)