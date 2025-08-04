# monitor/views.py
import logging
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .forms import DocumentoUploadForm
from .models import Documento, NormaVigente
from monitor.utils.api import coletar_dados_receita
from django.utils import timezone
from datetime import timedelta



logger = logging.getLogger(__name__)




# --- SISTEMA SIMPLIFICADO ---

@login_required
def home(request):
    """Página inicial simples, mostra os documentos coletados."""
    documentos = Documento.objects.all().order_by('-id')
    return render(request, 'home.html', {'documentos': documentos})

@login_required
def upload_documento(request):
    """Upload de documento simples."""
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = DocumentoUploadForm()
    return render(request, 'upload.html', {'form': form})

@login_required
def coletar_dados_receita_view(request):
    """Dispara o scrapper e retorna resultado simples."""
    if request.method == 'POST':
        data = request.POST.get('data_receita')
        sucesso = coletar_dados_receita(data)
        return JsonResponse({'sucesso': bool(sucesso)})
    return render(request, 'coletar.html')


# --- VIEWS UTILITÁRIAS ---
from django.shortcuts import render

@login_required
def coletar_diario_oficial_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com DiarioOficialScraper
        resultado = {'msg': 'Coleta simulada.'}
    return render(request, 'coletar_diario.html', {'resultado': resultado})

@login_required
def processar_documentos_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com PDFProcessor
        resultado = {'msg': 'Processamento simulado.'}
    return render(request, 'processar_documentos.html', {'resultado': resultado})

@login_required
def verificar_normas_sefaz_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com IntegradorSEFAZ
        resultado = {'msg': 'Verificação simulada.'}
    return render(request, 'verificar_normas.html', {'resultado': resultado})

@login_required
def gerar_relatorio_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com ClaudeProcessor
        resultado = {'msg': 'Relatório simulado.'}
    return render(request, 'gerar_relatorio.html', {'resultado': resultado})

@login_required
def pipeline_manual_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com pipeline_manual_completo
        resultado = {'msg': 'Pipeline manual simulado.'}
    return render(request, 'pipeline_manual.html', {'resultado': resultado})


# --- MONITORAMENTO DE TASKS CELERY ---
from django_celery_results.models import TaskResult

@login_required
def monitoramento_tasks(request):
    tasks = TaskResult.objects.order_by('-date_done')[:20]
    return render(request, 'monitoramento_tasks.html', {'tasks': tasks})