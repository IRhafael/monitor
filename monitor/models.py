from django.utils import timezone
from django.db import models
from django.core.validators import MinValueValidator
import os
from datetime import datetime  # Adicione esta linha no início do arquivo
from django.core.exceptions import ValidationError
import re

class TermoMonitorado(models.Model):
    """
    Termos para identificar documentos relevantes
    """
    TIPO_CHOICES = [
        ('TEXTO', 'Texto Exato'),
        ('NORMA', 'Norma Específica'),
        ('REGEX', 'Expressão Regular'),
    ]

    termo = models.CharField(max_length=255, unique=True)
    tipo = models.CharField(max_length=5, choices=TIPO_CHOICES)
    ativo = models.BooleanField(default=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)
    variacoes = models.TextField(blank=True, null=True, 
                               help_text="Variações do termo, separadas por vírgula")
    prioridade = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Prioridade na análise (1-5)"
    )

    class Meta:
        verbose_name = "Termo Monitorado"
        verbose_name_plural = "Termos Monitorados"
        ordering = ['-prioridade', 'termo']
        indexes = [
            models.Index(fields=['ativo']),
            models.Index(fields=['tipo']),
        ]

    def __str__(self):
        return f"{self.termo} ({self.get_tipo_display()})"


from django.db import models
from django.utils import timezone # Importar timezone se for usar no save, etc.
from datetime import datetime # Importar datetime para o _preprocessar_detalhes
from django.db import models
from django.utils import timezone # Importar timezone se for usar no save, etc.
from datetime import datetime # Importar datetime para o _preprocessar_detalhes
from django.core.exceptions import ValidationError # Para o método clean
# Suas outras importações e modelos (TermoMonitorado, etc.) devem estar aqui

class NormaVigente(models.Model):
    """
    Normas legais monitoradas pelo sistema
    """
    TIPO_CHOICES = [
        ('LEI', 'Lei'),
        ('DECRETO', 'Decreto'),
        ('PORTARIA', 'Portaria'),
        ('RESOLUCAO', 'Resolução'),
        ('INSTRUCAO', 'Instrução Normativa'),
        ('OUTROS', 'Outros'),
    ]

    SITUACAO_CHOICES = [
        ('VIGENTE', 'Vigente'),
        ('REVOGADA', 'Revogada'),
        ('IRREGULAR', 'Irregular'),
        ('A_VERIFICAR', 'A verificar'),
        ('ALTERADA', 'Alterada'),
        ('DESCONHECIDA', 'Desconhecida')
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, db_index=True)
    numero = models.CharField(max_length=50, db_index=True)
    ano = models.IntegerField(null=True, blank=True, db_index=True)
    fonte_confirmacao = models.CharField(
        max_length=10,
        choices=[('SEFAZ', 'SEFAZ'), ('BING', 'Bing')],
        null=True,
        blank=True
    )
    resumo_ia = models.TextField(
        'Resumo da IA',
        null=True,
        blank=True
    )
    url_consulta = models.URLField(
        'URL de consulta',
        null=True,
        blank=True
    )
    data_verificacao = models.DateTimeField(
        'Data da última verificação',
        null=True,
        blank=True
    )
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES, default='A_VERIFICAR')
    url = models.URLField(blank=True, verbose_name="URL da Norma")
    descricao = models.TextField(blank=True, verbose_name="Descrição/Objeto")
    detalhes = models.JSONField(blank=True, null=True, help_text="Detalhes da consulta na SEFAZ")
    data_cadastro = models.DateTimeField(auto_now_add=True)
    fonte = models.CharField(
        max_length=50,
        default='SEFAZ',
        choices=[('SEFAZ', 'SEFAZ'), ('DIARIO', 'Diário Oficial')]
    )
    observacoes = models.TextField(blank=True)
    data_ultima_mencao = models.DateField(null=True, blank=True)
    irregular = models.BooleanField(default=False, verbose_name="Norma Irregular")

    # --- NOVOS CAMPOS ADICIONADOS À NORMAVIGENTE ---
    ementa = models.TextField(
        blank=True,
        null=True,
        verbose_name="Ementa da Norma"
    )
    data_vigencia = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Início da Vigência"
    )
   

    class Meta:
        verbose_name = "Norma Vigente"
        verbose_name_plural = "Normas Vigentes"
        ordering = ['tipo', '-ano', 'numero']
        unique_together = [['tipo', 'numero', 'ano']]
        indexes = [
            models.Index(fields=['tipo', 'numero', 'ano']),
            models.Index(fields=['situacao']),
            models.Index(fields=['data_verificacao']),
            models.Index(fields=['data_vigencia']), 
        ]

    def __str__(self):
        if self.ano:
            return f"{self.get_tipo_display()} {self.numero}/{self.ano}"
        return f"{self.get_tipo_display()} {self.numero}"

    def status_style(self):
        if self.situacao == 'VIGENTE':
            return 'success'
        elif self.situacao == 'REVOGADA':
            return 'danger'
        elif self.situacao == 'ALTERADA':
            return 'warning'
        elif self.situacao == 'IRREGULAR':
            return 'warning'
        return 'secondary'


    def _preprocessar_detalhes(self, detalhes):
        if not detalhes:
            return detalhes
        for key, value in detalhes.items():
            if isinstance(value, datetime): 
                detalhes[key] = value.isoformat()
            elif isinstance(value, dict):
                detalhes[key] = self._preprocessar_detalhes(value)
        return detalhes

    def clean(self):
        if not hasattr(self, 'descricao') or not self.descricao.startswith('[TESTE]'):
            if not self.tipo or not self.numero:
                raise ValidationError("Tipo e número são obrigatórios")
            if len(str(self.numero)) < 3:
                raise ValidationError("Número da norma muito curto")

    def save(self, *args, **kwargs):
        if hasattr(self, 'descricao') and self.descricao.startswith('[TESTE]'):
            if 'force_insert' not in kwargs:
                kwargs['force_insert'] = True
            super().save(*args, **kwargs)
        else:
            self.full_clean()
            super().save(*args, **kwargs)

    @property
    def get_status_badge_class(self):
        status_map = {
            'VIGENTE': 'bg-success',
            'REVOGADA': 'bg-danger',
            'NÃO ENCONTRADA': 'bg-warning text-dark', 
            'IRREGULAR': 'bg-warning text-dark',
            'A_VERIFICAR': 'bg-secondary',
            'ALTERADA': 'bg-info',
            'DESCONHECIDA': 'bg-light text-dark',
             None: 'bg-secondary'
        }
        return status_map.get(self.situacao, 'bg-secondary')

    @property
    def documentos_count(self):
        # Assumindo que o related_name de Documento.normas_relacionadas é 'documentos'
        return self.documentos.count()



class Documento(models.Model):
    """
    Documentos coletados do Diário Oficial
    """
    titulo = models.CharField(max_length=255, verbose_name="Título")
    data_publicacao = models.DateField(verbose_name="Data de Publicação")
    url_original = models.URLField(
        verbose_name="URL Original",
        max_length=500,
        unique=True,
        db_index=True
    )
    arquivo_pdf = models.FileField(
        upload_to='pdfs/',
        verbose_name="Arquivo PDF",
        null=True,
        blank=True,
        max_length=500
    )
    resumo = models.TextField(verbose_name="Resumo", blank=True)
    texto_completo = models.TextField(verbose_name="Texto Completo", blank=True)
    data_coleta = models.DateTimeField(default=timezone.now)
    processado = models.BooleanField(default=False, verbose_name="Processado?")
    relevante_contabil = models.BooleanField(
        default=False,
        verbose_name="Relevante para Contabilidade?"
    )
    normas_relacionadas = models.ManyToManyField(
        'NormaVigente', # Coloquei entre aspas se NormaVigente for definida depois no arquivo
        blank=True,
        related_name='documentos',
        verbose_name="Normas Relacionadas"
    )
    assunto = models.CharField(max_length=255, blank=True, null=True)

    # --- NOVOS CAMPOS ADICIONADOS AO DOCUMENTO ---
    TIPO_DOC_CHOICES = [
        ('DIARIO_OFICIAL', 'Diário Oficial'),
        ('PORTARIA_DOC', 'Portaria do Documento'), # Nomeado para diferenciar de NormaVigente.tipo='PORTARIA'
        ('EDITAL', 'Edital'),
        ('COMUNICADO', 'Comunicado'),
        ('ATO_NORMATIVO_DOC', 'Ato Normativo do Documento'), # Nomeado para diferenciar
        ('LEI_DOC', 'Lei do Documento'), # Nomeado para diferenciar
        ('DECRETO_DOC', 'Decreto do Documento'), # Nomeado para diferenciar
        ('RESOLUCAO_DOC', 'Resolução do Documento'), # Nomeado para diferenciar
        ('INSTRUCAO_NORMATIVA_DOC', 'Instrução Normativa do Documento'), # Nomeado para diferenciar
        ('OUTRO', 'Outro'),
    ]
    tipo_documento = models.CharField(
        max_length=50, # Aumentado para acomodar 'INSTRUCAO_NORMATIVA_DOC'
        choices=TIPO_DOC_CHOICES,
        blank=True,
        null=True,
        verbose_name="Tipo do Documento"
    )
    fonte_documento = models.CharField(
        max_length=250, # Aumentado um pouco por precaução
        blank=True,
        null=True,
        verbose_name="Fonte do Documento" # Ex: "Diário Oficial do Estado do Piauí", "Site da SEFAZ-PI", etc.
    )
    # --- FIM DOS NOVOS CAMPOS ---

    metadata = models.JSONField(
        blank=True,
        null=True,
        help_text="Metadados adicionais do documento"
    )
    arquivo_removido = models.BooleanField(
        default=False,
        help_text="Indica se o arquivo PDF foi removido por não ser relevante"
    )

    class Meta:
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        ordering = ['-data_publicacao']
        indexes = [
            models.Index(fields=['data_publicacao']),
            models.Index(fields=['processado']),
            models.Index(fields=['relevante_contabil']),
            models.Index(fields=['arquivo_removido']),
            models.Index(fields=['tipo_documento']), # Index para o novo campo
            # Adicione um índice para fonte_documento se você for filtrar muito por ele
            # models.Index(fields=['fonte_documento']),
        ]

    def __str__(self):
        return f"{self.titulo} ({self.data_publicacao.strftime('%d/%m/%Y')})"

    def delete(self, *args, **kwargs):
        """Remove o arquivo PDF associado ao deletar o documento"""
        if self.arquivo_pdf and hasattr(self.arquivo_pdf, 'path') and os.path.isfile(self.arquivo_pdf.path):
            os.remove(self.arquivo_pdf.path)
        super().delete(*args, **kwargs)

    def process_status_style(self):
        if self.processado:
            return 'success' if self.relevante_contabil else 'info'
        return 'warning'


class RelatorioGerado(models.Model):
    """
    Relatórios gerados pelo sistema
    """
    TIPO_CHOICES = [
        ('CONTABIL', 'Contábil Completo'),
        ('MUDANCAS', 'Mudanças nas Normas'),
        ('ESTATISTICAS', 'Estatísticas do Sistema'),
    ]

    FORMATO_CHOICES = [
        ('XLSX', 'Excel (.xlsx)'),
        ('PDF', 'PDF (.pdf)'),
        ('HTML', 'HTML (.html)'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    caminho_arquivo = models.FileField(
        upload_to='relatorios/',
        verbose_name="Arquivo do Relatório"
    )
    formato = models.CharField(max_length=10, choices=FORMATO_CHOICES, default='XLSX')
    parametros = models.JSONField(
        blank=True,
        null=True,
        help_text="Parâmetros usados para gerar o relatório"
    )
    data_criacao = models.DateTimeField(auto_now_add=True)
    gerado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    downloads = models.PositiveIntegerField(default=0, verbose_name="Número de Downloads")

    class Meta:
        verbose_name = "Relatório Gerado"
        verbose_name_plural = "Relatórios Gerados"
        ordering = ['-data_criacao']
        indexes = [
            models.Index(fields=['tipo']),
            models.Index(fields=['data_criacao']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.data_criacao.strftime('%d/%m/%Y %H:%M')}"

    def nome_arquivo(self):
        return os.path.basename(self.caminho_arquivo.name)


class ConfiguracaoColeta(models.Model):
    """
    Configurações para a coleta automática
    """
    ativa = models.BooleanField(
        default=True,
        verbose_name="Coleta Automática Ativa?"
    )
    intervalo_horas = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1)],
        verbose_name="Intervalo entre Coletas (horas)"
    )
    max_documentos = models.PositiveIntegerField(
        default=10,
        verbose_name="Máximo de Documentos por Coleta"
    )
    ultima_execucao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Última Execução"
    )
    proxima_execucao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Próxima Execução"
    )
    email_notificacao = models.EmailField(
        blank=True,
        verbose_name="E-mail para Notificações"
    )
    verificar_vigencias = models.BooleanField(
        default=True,
        verbose_name="Verificar Vigências Automaticamente?"
    )
    dias_retroativos = models.PositiveIntegerField(
        default=30,
        verbose_name="Dias Retroativos para Análise"
    )

    class Meta:
        verbose_name = "Configuração de Coleta"
        verbose_name_plural = "Configurações de Coleta"

    def __str__(self):
        return f"Configuração de Coleta (Intervalo: {self.intervalo_horas}h)"

    def save(self, *args, **kwargs):
        """Garante que só exista uma instância de configuração"""
        if not self.pk and ConfiguracaoColeta.objects.exists():
            return
        super().save(*args, **kwargs)


class LogExecucao(models.Model):
    """
    Registro de execuções do sistema
    """
    TIPO_CHOICES = [
        ('DIARIO', 'Coleta do Diário Oficial'),
        ('SEFAZ', 'Verificação na SEFAZ'),
        ('PROCESSAMENTO', 'Processamento de Documentos'),
        ('RELATORIO', 'Geração de Relatório'),
        ('COMPLETO', 'Fluxo Completo'),
    ]
    
    STATUS_CHOICES = [
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Sucesso Parcial'),
    ]
    
    tipo_execucao = models.CharField(max_length=20, choices=TIPO_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    data_inicio = models.DateTimeField(auto_now_add=True)
    data_fim = models.DateTimeField(null=True, blank=True)
    duracao = models.DurationField(null=True, blank=True)
    documentos_coletados = models.PositiveIntegerField(default=0)
    normas_verificadas = models.PositiveIntegerField(default=0)
    documentos_processados = models.PositiveIntegerField(default=0)
    mensagem = models.TextField(blank=True)
    erro = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    detalhes = models.JSONField(blank=True, null=True)
    usuario = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = "Log de Execução"
        verbose_name_plural = "Logs de Execução"
        ordering = ['-data_inicio']
        indexes = [
            models.Index(fields=['tipo_execucao']),
            models.Index(fields=['status']),
            models.Index(fields=['data_inicio']),
        ]

    def __str__(self):
        return f"{self.get_tipo_execucao_display()} - {self.status} ({self.data_inicio.strftime('%d/%m/%Y %H:%M')})"

    def save(self, *args, **kwargs):
        """Calcula a duração antes de salvar"""
        if self.data_fim and self.data_inicio:
            self.duracao = self.data_fim - self.data_inicio
        super().save(*args, **kwargs)