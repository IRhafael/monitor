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
        from monitor.utils.diario_scraper import DiarioOficialScraper
        from monitor.utils.sefaz_scraper import SEFAZScraper
        from monitor.utils.pdf_processor import PDFProcessor
        from monitor.utils.sefaz_integracao import IntegradorSEFAZ
        
        try:
            # 1. Coleta do Diário Oficial
            diario_scraper = DiarioOficialScraper()
            documentos = diario_scraper.iniciar_coleta()
            
            # 2. Processamento dos PDFs
            processor = PDFProcessor()
            processor.processar_todos_documentos()
            
            # 3. Coleta da SEFAZ
            sefaz_scraper = SEFAZScraper()
            normas = sefaz_scraper.iniciar_coleta()
            
            # 4. Integração SEFAZ-Diário
            integrador = IntegradorSEFAZ()
            integrador.verificar_documentos_nao_verificados()
            
            messages.success(request, 
                f"Coleta concluída! Documentos: {len(documentos)}, Normas: {normas['normas_coletadas']}"
            )
            
        except Exception as e:
            messages.error(request, f"Erro na coleta: {str(e)}")
        
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
