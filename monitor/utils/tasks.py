# monitor/utils/tasks.py

from celery import shared_task
from datetime import datetime, timedelta, date # Adicione 'date' aqui
import logging
from django.utils import timezone
from django.db import transaction
import traceback
from django.db.models import Q 
from .diario_scraper import DiarioOficialScraper
from .pdf_processor import PDFProcessor
from monitor.models import Documento, LogExecucao, NormaVigente
from .sefaz_integracao import IntegradorSEFAZ

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def coletar_diario_oficial_task(self, data_inicio_str=None, data_fim_str=None):
    task_id = self.request.id
    logger.info(f"Tarefa Celery 'coletar_diario_oficial_task' [{task_id}] iniciada.")

    data_inicio = None
    data_fim = None
    log_status = 'ERRO'
    log_detalhes = {}
    documentos_coletados_raw = []
    documentos_salvos_count = 0

    try:
        if data_inicio_str:
            data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        if data_fim_str:
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()

        if not data_inicio or not data_fim:
            data_fim = date.today() # Use 'date' aqui
            data_inicio = data_fim - timedelta(days=3)
            logger.info(f"[{task_id}] Datas não fornecidas. Usando os últimos 3 dias: de {data_inicio} a {data_fim}")

        scraper = DiarioOficialScraper()
        logger.info(f"[{task_id}] Iniciando coleta de documentos do Diário Oficial de {data_inicio} a {data_fim}.")

        documentos_coletados_raw = scraper.coletar_e_salvar_documentos(data_inicio, data_fim)
        documentos_salvos_count = len(documentos_coletados_raw)

        log_status = 'SUCESSO'
        log_detalhes = {
            'documentos_coletados': documentos_salvos_count,
            'datas_coletadas': f"{data_inicio} a {data_fim}"
        }

    except Exception as e:
        logger.error(f"[{task_id}] Erro na tarefa de coleta do Diário Oficial: {e}", exc_info=True)
        log_status = 'ERRO'
        log_detalhes = {'erro': str(e), 'traceback': traceback.format_exc()}
        raise self.retry(exc=e, countdown=60, max_retries=3) # Adicionado retry para falhas de rede/scraper

    finally:
        LogExecucao.objects.create(
            tipo_execucao='COLETA',
            status=log_status,
            detalhes=log_detalhes
        )
        logger.info(f"[{task_id}] Tarefa Celery 'coletar_diario_oficial_task' concluída com status: {log_status}.")

    return {'status': log_status, 'documentos_coletados': documentos_salvos_count}


@shared_task(bind=True)
def processar_documentos_pendentes_task(self, previous_task_result=None):
    task_id = self.request.id
    logger.info(f"[{task_id}] Tarefa Celery 'processar_documentos_pendentes_task' iniciada.")
    log_status = 'ERRO'
    log_detalhes = {}

    sucesso_count = 0
    irrelevantes_count = 0
    falhas_count = 0

    try:
        processor = PDFProcessor()
        documentos_pendentes = Documento.objects.filter(processado=False).order_by('data_publicacao')
        total_a_processar = documentos_pendentes.count()
        
        logger.info(f"[{task_id}] Iniciando processamento em lote de {total_a_processar} documentos pendentes.")

        if total_a_processar == 0:
            log_status = 'NENHUM_PROCESSADO'
            log_detalhes = {'message': 'Nenhum documento pendente para processar.'}
            logger.info(f"[{task_id}] {log_detalhes['message']}")
            return {'status': log_status, 'results': log_detalhes}

        # Itera sobre cada documento pendente e chama process_document
        with transaction.atomic(): # Garante que todas as atualizações sejam atômicas
            for documento in documentos_pendentes:
                try:
                    # process_document retorna um dicionário com 'status', 'message', etc.
                    # e já atualiza o documento no DB
                    process_result = processor.process_document(documento)
                    
                    if process_result.get('status') == 'SUCESSO':
                        sucesso_count += 1
                    elif process_result.get('status') == 'IGNORADO_IRRELEVANTE':
                        irrelevantes_count += 1
                    else: # status == 'ERRO' ou outro
                        falhas_count += 1
                        logger.error(f"[{task_id}] Falha ao processar documento ID {documento.id}: {process_result.get('message', 'Erro desconhecido')}")
                except Exception as doc_e:
                    falhas_count += 1
                    logger.error(f"[{task_id}] Erro inesperado ao processar documento ID {documento.id}: {doc_e}", exc_info=True)
        
        log_status = 'SUCESSO' # Assume sucesso se a iteração não lançar erro fatal
        log_detalhes = {
            'processados_com_sucesso': sucesso_count,
            'documentos_irrelevantes': irrelevantes_count,
            'erros': falhas_count,
            'total_analisados': total_a_processar
        }
        
    except Exception as e:
        logger.error(f"[{task_id}] Erro fatal no processamento de PDFs: {e}", exc_info=True)
        log_status = 'ERRO'
        log_detalhes = {'erro': str(e), 'traceback': traceback.format_exc()}
        raise # Relaça a exceção para que Celery marque a tarefa como falha

    finally:
        LogExecucao.objects.create(
            tipo_execucao='PROCESSAMENTO_PDF',
            status=log_status,
            detalhes=log_detalhes
        )
        logger.info(f"[{task_id}] Tarefa Celery 'processar_documentos_pendentes_task' concluída com status: {log_status}.")
        
    return {'status': log_status, 'results': log_detalhes}


@shared_task(bind=True)
def verificar_normas_sefaz_task(self):
    task_id = self.request.id
    logger.info(f"[{task_id}] Tarefa Celery 'verificar_normas_sefaz_task' iniciada.")
    log_status = 'ERRO'
    log_detalhes = {}

    try:
        integrador_sefaz = IntegradorSEFAZ()
        # Filtra normas que nunca foram verificadas ou que estão desatualizadas (mais de 30 dias)
        normas_para_verificar = NormaVigente.objects.filter(
            Q(data_verificacao__isnull=True) |
            Q(data_verificacao__lt=timezone.now() - timedelta(days=30))
        ).order_by('data_verificacao') # Verifica as mais antigas primeiro

        if not normas_para_verificar.exists():
            log_status = 'NENHUM_ENCONTRADA'
            log_detalhes = {'message': 'Nenhuma norma encontrada para verificação.'}
            logger.info(f"[{task_id}] Nenhuma norma para verificar.")
            return {'status': log_status, 'normas_verificadas': 0}

        logger.info(f"[{task_id}] Encontradas {normas_para_verificar.count()} normas para verificar.")
        
        # O método verificar_normas_em_lote já atualiza as normas no DB
        # Convertendo o QuerySet para lista para evitar problemas com iteração durante o Selenium
        resultados_lote = integrador_sefaz.verificar_normas_em_lote(list(normas_para_verificar))
        normas_verificadas_count = len(resultados_lote)

        log_status = 'SUCESSO'
        log_detalhes = {
            'total_normas_analisadas': normas_verificadas_count,
            # Se você quiser detalhes de quantas vigentes/revogadas, o método de lote precisa retornar isso
        }

    except Exception as e:
        logger.error(f"[{task_id}] Erro fatal na verificação de normas SEFAZ: {e}", exc_info=True)
        log_status = 'ERRO'
        log_detalhes = {'erro': str(e), 'traceback': traceback.format_exc()}
        raise self.retry(exc=e, countdown=60, max_retries=3)

    finally:
        LogExecucao.objects.create(
            tipo_execucao='VERIFICACAO_SEFAZ', # Tipo de log específico
            status=log_status,
            detalhes=log_detalhes
        )
        logger.info(f"[{task_id}] Tarefa Celery 'verificar_normas_sefaz_task' concluída com status: {log_status}.")
        
    return {'status': log_status, 'results': log_detalhes}


# Pipeline completo: Coleta -> Processamento -> Verificação SEFAZ
@shared_task(bind=True)
def pipeline_coleta_e_processamento(self, data_inicio_str=None, data_fim_str=None):
    """
    Tarefa Celery que executa a coleta, em seguida o processamento de PDFs,
    e por fim a verificação de normas na SEFAZ.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando pipeline completo de coleta, processamento e verificação SEFAZ.")
    
    # 1. Tarefa de Coleta
    coleta_signature = coletar_diario_oficial_task.s(data_inicio_str, data_fim_str)
    
    # 2. Tarefa de Processamento (roda após a coleta)
    processamento_signature = processar_documentos_pendentes_task.s()
    
    # 3. Tarefa de Verificação SEFAZ (roda após o processamento)
    sefaz_check_signature = verificar_normas_sefaz_task.s()

    # Encadeamento: Coleta -> Processamento -> Verificação SEFAZ
    # Use chain() para garantir que a ordem seja mantida
    workflow = (coleta_signature | processamento_signature | sefaz_check_signature)
    
    # Dispara o pipeline encadeado
    workflow.apply_async() # apply_async é melhor para iniciar chains
    
    logger.info(f"[{task_id}] Pipeline completo disparado: Coleta -> Processamento -> Verificação SEFAZ.")
    return {'status': 'PIPELINE_DISPARADO', 'pipeline_task_id': task_id}