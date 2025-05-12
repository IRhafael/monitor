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
    normas_relacionadas = models.ManyToManyField('NormaVigente', blank=True)
    verificado_sefaz = models.BooleanField(default=False, verbose_name="Verificado na SEFAZ")
    relevante_contabil = models.BooleanField(default=False)
    

    class Meta:
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        ordering = ['-data_publicacao']

    def __str__(self):
        return f"{self.titulo} ({self.data_publicacao})"
    
    def delete(self, *args, **kwargs):
        # Remover o arquivo PDF quando o documento for excluído
        if self.arquivo_pdf:
            if os.path.isfile(self.arquivo_pdf.path):
                os.remove(self.arquivo_pdf.path)
        super().delete(*args, **kwargs)


class NormaVigente(models.Model):
    """
    Modelo para armazenar informações sobre normas vigentes da SEFAZ
    """
    TIPO_CHOICES = [
        ('LEI', 'Lei'),
        ('DECRETO', 'Decreto'),
        ('PORTARIA', 'Portaria'),
        ('RESOLUCAO', 'Resolução'),
        ('INSTRUCAO', 'Instrução Normativa'),
        ('OUTROS', 'Outros'),
    ]
    
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name="Tipo")
    numero = models.CharField(max_length=50, verbose_name="Número")
    data = models.DateField(verbose_name="Data", null=True, blank=True)
    situacao = models.CharField(max_length=50, default="Vigente", verbose_name="Situação")
    url = models.URLField(verbose_name="URL", blank=True)
    descricao = models.TextField(verbose_name="Descrição", blank=True)
    data_coleta = models.DateTimeField(default=timezone.now, verbose_name="Data da Coleta")
    
    class Meta:
        verbose_name = "Norma Vigente"
        verbose_name_plural = "Normas Vigentes"
        ordering = ['-data', 'tipo', 'numero']
        unique_together = ['tipo', 'numero']  # Evitar duplicações
        
    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero} ({self.data})"


class ConfiguracaoColeta(models.Model):
    """
    Modelo para armazenar configurações da coleta automática
    """
    ativa = models.BooleanField(default=True, verbose_name="Coleta Ativa")
    intervalo_horas = models.PositiveIntegerField(default=24, verbose_name="Intervalo (horas)")
    max_documentos = models.PositiveIntegerField(default=5, verbose_name="Máximo de Documentos")
    ultima_execucao = models.DateTimeField(null=True, blank=True, verbose_name="Última Execução")
    proxima_execucao = models.DateTimeField(null=True, blank=True, verbose_name="Próxima Execução")
    
    email_notificacao = models.EmailField(blank=True, verbose_name="Email para Notificação")
    notificar_erros = models.BooleanField(default=True, verbose_name="Notificar Erros")
    
    class Meta:
        verbose_name = "Configuração de Coleta"
        verbose_name_plural = "Configurações de Coleta"
    
    def __str__(self):
        return f"Configuração - Intervalo: {self.intervalo_horas}h"
    
    def save(self, *args, **kwargs):
        # Garantir que só exista uma instância de configuração
        if not self.pk and ConfiguracaoColeta.objects.exists():
            return
        super().save(*args, **kwargs)


class LogExecucao(models.Model):
    """
    Modelo para armazenar logs de execução das coletas
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
    
    data_inicio = models.DateTimeField(auto_now_add=True, verbose_name="Data de Início")
    data_fim = models.DateTimeField(null=True, blank=True, verbose_name="Data de Conclusão")
    tipo_execucao = models.CharField(max_length=10, choices=TIPO_CHOICES, verbose_name="Tipo de Execução")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, verbose_name="Status")
    documentos_coletados = models.IntegerField(default=0, verbose_name="Documentos Coletados")
    normas_coletadas = models.IntegerField(default=0, verbose_name="Normas Coletadas")
    mensagem = models.TextField(blank=True, verbose_name="Mensagem")
    erro_detalhado = models.TextField(blank=True, verbose_name="Erro Detalhado")
    normas_salvas = models.IntegerField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Log de Execução"
        verbose_name_plural = "Logs de Execução"
        ordering = ['-data_inicio']
    
    def __str__(self):
        return f"{self.get_tipo_execucao_display()} - {self.data_inicio.strftime('%d/%m/%Y %H:%M')} - {self.get_status_display()}"


    data_fim = models.DateTimeField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.data_fim:
            self.data_fim = timezone.now()
        super().save(*args, **kwargs)


class Norma(models.Model):
    TIPOS_NORMA = [
        ('LEI', 'Lei'),
        ('PORTARIA', 'Portaria'),
        ('DECRETO', 'Decreto'),
    ]
    
    tipo = models.CharField(max_length=20, choices=TIPOS_NORMA)
    numero = models.CharField(max_length=50)
    data = models.DateField()
    conteudo = models.TextField(blank=True, null=True)
    arquivo = models.FileField(upload_to='normas/', blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['tipo', 'numero']  # Evita duplicatas

    def __str__(self):
        return f"{self.tipo} {self.numero}"