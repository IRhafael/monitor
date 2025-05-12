from django.shortcuts import render
from django.http import HttpResponse, FileResponse, JsonResponse
from django.contrib.auth.decorators import login_required
import os
from django.conf import settings
from .models import Documento, NormaVigente, LogExecucao
from .tasks import executar_coleta_completa, gerar_relatorio_excel
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


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
        from monitor.utils.pdf_processor import PDFProcessor
        from monitor.utils.sefaz_integracao import IntegradorSEFAZ
        from monitor.utils.relatorio import RelatorioGenerator
        
        try:
            logger.info("=== INÍCIO DA COLETA ===")
            
            # 1. Coleta do Diário Oficial
            logger.info("Iniciando coleta do Diário Oficial...")
            diario_scraper = DiarioOficialScraper()
            documentos_baixados = diario_scraper.iniciar_coleta()
            logger.info(f"Documentos baixados: {len(documentos_baixados)}")
            
            # 2. Processamento dos PDFs
            logger.info("Iniciando processamento dos PDFs...")
            processor = PDFProcessor()
            docs_processados = processor.processar_todos_documentos()
            logger.info(f"Documentos processados: {docs_processados}")
            
            # 3. Verificação na SEFAZ
            logger.info("Iniciando verificação na SEFAZ...")
            integrador = IntegradorSEFAZ()
            normas_verificadas = integrador.verificar_documentos_nao_verificados()
            logger.info(f"Normas verificadas: {len(normas_verificadas)}")
            
            # 4. Geração de relatórios
            logger.info("Gerando relatórios...")
            relatorio_contabil = RelatorioGenerator.gerar_relatorio_contabil()
            relatorio_mudancas = RelatorioGenerator.gerar_relatorio_mudancas()
            logger.info(f"Relatórios gerados: {relatorio_contabil}, {relatorio_mudancas}")
            
            messages.success(request, 
                f"Coleta concluída! Documentos: {len(documentos_baixados)}, "
                f"Normas: {len(normas_verificadas)}"
            )
            logger.info("=== COLETA CONCLUÍDA COM SUCESSO ===")
            
        except Exception as e:
            logger.error(f"=== ERRO NA COLETA: {str(e)} ===", exc_info=True)
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
