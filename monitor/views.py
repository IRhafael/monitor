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
    return render(request, 'base.html', {'documentos': documentos})

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
    return render(request, 'templates/coletar.html')