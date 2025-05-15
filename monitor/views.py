from datetime import timedelta
from django.forms import DurationField
from django.http import Http404, HttpResponse, FileResponse, JsonResponse
from django.contrib.auth.decorators import login_required
import os
from django.conf import settings

from monitor.utils import PDFProcessor
from monitor.utils.diario_scraper import DiarioOficialScraper
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from .models import Documento, NormaVigente, LogExecucao
from .tasks import executar_coleta_completa, gerar_relatorio_excel
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
import logging
import os
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from .utils.relatorio import RelatorioGenerator
from celery import shared_task



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






def gerar_relatorio(request):
    if request.method == 'POST':
        try:
            caminho = RelatorioGenerator.gerar_relatorio_contabil()
            if caminho:
                return render(request, 'relatorio_sucesso.html', {'caminho': caminho})
            else:
                return render(request, 'monitor/relatorio_sucesso.html')
        except Exception as e:
            print(f"Erro ao gerar relatório: {e}")
            return render(request, 'monitor/confirmar_relatorio.html')
    
    return render(request, 'monitor/confirmar_relatorio.html')


def download_relatorio(request):
    # Obtém o caminho do último relatório gerado (simplificado)
    relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
    arquivos = sorted(os.listdir(relatorios_dir), reverse=True)
    
    if arquivos:
        caminho = os.path.join(relatorios_dir, arquivos[0])
        if os.path.exists(caminho):
            response = FileResponse(open(caminho, 'rb'))
            response['Content-Disposition'] = f'attachment; filename="{arquivos[0]}"'
            return response
    
    from django.http import Http404
    raise Http404("Relatório não encontrado")

@shared_task
def pipeline_completo():
    # 1. Coleta
    scraper = DiarioOficialScraper()
    docs = scraper.iniciar_coleta()
    
    # 2. Processamento
    processor = PDFProcessor()
    for doc in docs:
        processor.processar_documento(doc)
    
    # 3. Verificação SEFAZ
    integrador = IntegradorSEFAZ()
    integrador.verificar_vigencia_automatica()
    
    # 4. Atualiza status
    Documento.objects.filter(id__in=[d.id for d in docs]).update(processado=True)


@login_required
def dashboard_vigencia(request):
    normas = NormaVigente.objects.annotate(
        dias_desde_verificacao=ExpressionWrapper(
            timezone.now() - F('data_verificacao'),
            output_field=DurationField()
        )
    ).order_by('dias_desde_verificacao')
    
    context = {
        'normas_vigentes': normas.filter(situacao="VIGENTE"),
        'normas_vencidas': normas.filter(situacao="REVOGADA"),
        'alertas': normas.filter(dias_desde_verificacao__gt=timedelta(days=90))
    }
    return render(request, 'monitor/vigencia.html', context)


@login_required
def verificar_norma(request, tipo, numero):
    integrador = IntegradorSEFAZ()
    vigente, detalhes = integrador.verificar_vigencia_com_detalhes(tipo, numero)
    
    # Atualiza ou cria a norma no banco de dados
    norma, created = NormaVigente.objects.update_or_create(
        tipo=tipo,
        numero=numero,
        defaults={
            'situacao': 'VIGENTE' if vigente else 'REVOGADA',
            'detalhes_completos': detalhes,
            'data_detalhes': timezone.now(),
            'data_verificacao': timezone.now()
        }
    )
    
    return JsonResponse({
        'vigente': vigente,
        'detalhes': detalhes,
        'norma_id': norma.id
    })