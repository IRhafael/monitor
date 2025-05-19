# forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import TermoMonitorado, Documento, ConfiguracaoColeta
from django.core.validators import MinValueValidator, MaxValueValidator
import re
from .models import NormaVigente


class DocumentoUploadForm(forms.ModelForm):
    title = forms.CharField(
        label='Título',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    publication_date = forms.DateField(
        label='Data de Publicação',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        initial=timezone.now().date
    )
    pdf_file = forms.FileField(
        label='Arquivo PDF',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text='Envie um arquivo PDF do Diário Oficial'
    )

    class Meta:
        model = Documento
        fields = ['title', 'publication_date', 'pdf_file']

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if pdf_file:
            if not pdf_file.name.lower().endswith('.pdf'):
                raise ValidationError('O arquivo deve ser um PDF')
            if pdf_file.size > 10 * 1024 * 1024:  # 10MB
                raise ValidationError('O arquivo não pode exceder 10MB')
        return pdf_file

class TermoMonitoradoForm(forms.ModelForm):
    variacoes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'form-control',
            'placeholder': 'Variações do termo, separadas por vírgula'
        }),
        help_text='Variações ou sinônimos do termo principal'
    )
    prioridade = forms.IntegerField(
        initial=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1,
            'max': 5
        }),
        help_text='Prioridade na análise (1-5)'
    )

    class Meta:
        model = TermoMonitorado
        fields = ['termo', 'tipo', 'prioridade', 'variacoes', 'ativo']
        widgets = {
            'termo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

    def clean_termo(self):
        termo = self.cleaned_data.get('termo')
        if termo and len(termo) < 3:
            raise ValidationError('O termo deve ter pelo menos 3 caracteres')
        return termo

    def clean_variacoes(self):
        variacoes = self.cleaned_data.get('variacoes', '')
        if variacoes:
            # Remove espaços extras e divide por vírgula
            variacoes = [v.strip() for v in variacoes.split(',') if v.strip()]
            return ', '.join(variacoes)
        return variacoes

class ConfiguracaoColetaForm(forms.ModelForm):
    intervalo_horas = forms.IntegerField(
        label='Intervalo entre Coletas (horas)',
        validators=[MinValueValidator(1)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1
        })
    )
    max_documentos = forms.IntegerField(
        label='Máximo de Documentos por Coleta',
        validators=[MinValueValidator(1)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1
        })
    )
    dias_retroativos = forms.IntegerField(
        label='Dias Retroativos para Análise',
        validators=[MinValueValidator(1)],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1
        })
    )
    email_notificacao = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = ConfiguracaoColeta
        fields = [
            'ativa', 
            'intervalo_horas', 
            'max_documentos', 
            'verificar_vigencias',
            'dias_retroativos',
            'email_notificacao'
        ]
        widgets = {
            'ativa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'verificar_vigencias': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

class FiltroDocumentosForm(forms.Form):
    STATUS_CHOICES = [
        ('todos', 'Todos'),
        ('processados', 'Processados'),
        ('pendentes', 'Pendentes')
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='todos'
    )
    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Data Inicial'
    )
    data_fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Data Final'
    )

    def clean(self):
        cleaned_data = super().clean()
        data_inicio = cleaned_data.get('data_inicio')
        data_fim = cleaned_data.get('data_fim')
        
        if data_inicio and data_fim and data_inicio > data_fim:
            raise ValidationError('A data inicial não pode ser posterior à data final')
        
        return cleaned_data

class FiltroNormasForm(forms.Form):
    STATUS_CHOICES = [
        ('todos', 'Todos'),
        ('vigentes', 'Vigentes'),
        ('revogadas', 'Revogadas')
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='todos'
    )
    tipo = forms.ChoiceField(
        choices=[('', 'Todos')] + NormaVigente.TIPO_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

class RelatorioForm(forms.Form):
    TIPO_RELATORIO_CHOICES = [
        ('CONTABIL', 'Contábil Completo'),
        ('MUDANCAS', 'Mudanças nas Normas')
    ]
    
    FORMATO_CHOICES = [
        ('XLSX', 'Excel (.xlsx)'),
        ('PDF', 'PDF (.pdf)'),
        ('HTML', 'HTML (.html)')
    ]
    
    tipo_relatorio = forms.ChoiceField(
        choices=TIPO_RELATORIO_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Tipo de Relatório'
    )
    formato = forms.ChoiceField(
        choices=FORMATO_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Formato',
        initial='XLSX'
    )
    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Data Inicial'
    )
    data_fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label='Data Final'
    )
    dias_retroativos = forms.IntegerField(
        required=False,
        initial=30,
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Dias Retroativos (apenas para relatório de mudanças)'
    )

    def clean(self):
        cleaned_data = super().clean()
        tipo_relatorio = cleaned_data.get('tipo_relatorio')
        data_inicio = cleaned_data.get('data_inicio')
        data_fim = cleaned_data.get('data_fim')
        
        if tipo_relatorio == 'CONTABIL':
            if not data_inicio or not data_fim:
                raise ValidationError('Para relatório contábil, datas inicial e final são obrigatórias')
            if data_inicio > data_fim:
                raise ValidationError('Data inicial não pode ser posterior à data final')
        
        return cleaned_data