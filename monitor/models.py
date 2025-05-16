# monitor/models.py
from django.db import models
from django.utils import timezone
import os

class Documento(models.Model):
    """
    Modelo para armazenar informações sobre documentos do Diário Oficial
    """
    titulo = models.CharField(max_length=255, verbose_name="Título")
    data_publicacao = models.DateField(verbose_name="Data de Publicação")
    url_original = models.URLField(verbose_name="URL Original")
    arquivo_pdf = models.FileField(upload_to='pdfs/', verbose_name="Arquivo PDF", null=True, blank=True)
    resumo = models.TextField(verbose_name="Resumo", blank=True)
    texto_completo = models.TextField(verbose_name="Texto Completo", blank=True)
    data_coleta = models.DateTimeField(default=timezone.now, verbose_name="Data da Coleta")
    processado = models.BooleanField(default=False, verbose_name="Processado")
    relevante_contabil = models.BooleanField(default=False, verbose_name="Relevante para Contabilidade")
    normas_relacionadas = models.ManyToManyField('NormaVigente', blank=True, related_name='documentos')
    assunto = models.CharField(max_length=255, verbose_name="Assunto", blank=True, null=True)
    
    class Meta:
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        ordering = ['-data_publicacao']
        indexes = [
            models.Index(fields=['data_publicacao']),
            models.Index(fields=['processado']),
            models.Index(fields=['relevante_contabil']),
        ]

    def __str__(self):
        return f"{self.titulo} ({self.data_publicacao.strftime('%d/%m/%Y')})"
    
    def delete(self, *args, **kwargs):
        """Remove o arquivo PDF associado ao deletar o documento"""
        if self.arquivo_pdf and os.path.isfile(self.arquivo_pdf.path):
            os.remove(self.arquivo_pdf.path)
        super().delete(*args, **kwargs)


class NormaVigente(models.Model):
    """
    Modelo para armazenar informações sobre normas vigentes
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
        ('ALTERADA', 'Alterada'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    numero = models.CharField(max_length=50)
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES, default='VIGENTE')
    data_verificacao = models.DateTimeField(null=True, blank=True)
    url = models.URLField(blank=True)
    descricao = models.TextField(blank=True)
    data_coleta = models.DateTimeField(default=timezone.now)
    fonte = models.CharField(max_length=50, default='SEFAZ', choices=[('SEFAZ', 'SEFAZ'), ('DIARIO', 'Diário Oficial')])

    class Meta:
        verbose_name = "Norma Vigente"
        verbose_name_plural = "Normas Vigentes"
        ordering = ['tipo', 'numero']
        unique_together = ['tipo', 'numero']
        indexes = [
            models.Index(fields=['tipo', 'numero']),
            models.Index(fields=['situacao']),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero}"


class ConfiguracaoColeta(models.Model):
    """
    Configurações para a coleta automática
    """
    ativa = models.BooleanField(default=True)
    intervalo_horas = models.PositiveIntegerField(default=24)
    max_documentos = models.PositiveIntegerField(default=10)
    ultima_execucao = models.DateTimeField(null=True, blank=True)
    proxima_execucao = models.DateTimeField(null=True, blank=True)
    email_notificacao = models.EmailField(blank=True)

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
        ('DIARIO', 'Diário Oficial'),
        ('SEFAZ', 'SEFAZ'),
        ('COMPLETO', 'Fluxo Completo'),
    ]
    
    STATUS_CHOICES = [
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Sucesso Parcial'),
    ]
    
    data_inicio = models.DateTimeField(auto_now_add=True)
    data_fim = models.DateTimeField(null=True, blank=True)
    tipo_execucao = models.CharField(max_length=10, choices=TIPO_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    documentos_coletados = models.PositiveIntegerField(default=0)
    normas_coletadas = models.PositiveIntegerField(default=0)
    mensagem = models.TextField(blank=True)

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
        return f"{self.get_tipo_execucao_display()} - {self.data_inicio.strftime('%d/%m/%Y %H:%M')}"


class TermoMonitorado(models.Model):
    """
    Termos específicos para monitoramento no conteúdo dos documentos
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
    variacoes = models.TextField(blank=True, null=True, help_text="Variações do termo, separadas por vírgula")

    class Meta:
        verbose_name = "Termo Monitorado"
        verbose_name_plural = "Termos Monitorados"
        ordering = ['termo']

    def __str__(self):
        return f"{self.termo} ({self.get_tipo_display()})"