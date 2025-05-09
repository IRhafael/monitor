from django.shortcuts import render
from django.http import HttpResponse, FileResponse
from django.contrib.auth.decorators import login_required
import os
from django.conf import settings
from .models import Documento, NormaVigente, LogExecucao
from .tasks import executar_coleta_completa, gerar_relatorio_excel
from django.shortcuts import render, redirect
from django.contrib import messages

@login_required
def dashboard(request):
    # Dados básicos para o dashboard
    context = {
        'total_documentos': Documento.objects.count(),
        'documentos_recentes': Documento.objects.order_by('-data_publicacao')[:5],
        'total_normas': NormaVigente.objects.count(),
        'ultima_execucao': LogExecucao.objects.last(),
    }
    return render(request, 'monitor/dashboard.html', context)

@login_required
def documentos_list(request):
    documentos = Documento.objects.order_by('-data_publicacao')
    return render(request, 'monitor/documentos_list.html', {'documentos': documentos})

@login_required
def normas_list(request):
    normas = NormaVigente.objects.order_by('-data')
    return render(request, 'monitor/normas_list.html', {'normas': normas})



@login_required
def executar_coleta_view(request):
    if request.method == 'POST':
        resultado = executar_coleta_completa()  # Esta é a chamada importante
        
        if resultado['status'] == 'success':
            messages.success(request, f"Coleta concluída! Documentos: {resultado['documentos']}, Normas: {resultado['normas']}")
        else:
            messages.error(request, f"Erro: {resultado['message']}")
        
        return redirect('dashboard')
    
    return render(request, 'monitor/confirmar_coleta.html')

@login_required
def gerar_relatorio(request):
    if request.method == 'POST':
        resultado = gerar_relatorio_excel.delay()
        return render(request, 'monitor/relatorio_sucesso.html')
    return render(request, 'monitor/confirmar_relatorio.html')

@login_required
def download_relatorio(request):
    relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
    arquivos = sorted(
        [f for f in os.listdir(relatorios_dir) if f.endswith('.xlsx')],
        key=lambda x: os.path.getmtime(os.path.join(relatorios_dir, x)),
        reverse=True
    )
    
    if arquivos:
        latest = arquivos[0]
        file_path = os.path.join(relatorios_dir, latest)
        return FileResponse(open(file_path, 'rb'), as_attachment=True)
    
    return HttpResponse("Nenhum relatório disponível")
