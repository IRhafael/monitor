# monitor/utils/tasks.py

from celery import chain, shared_task
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
from celery.schedules import crontab
from diario_oficial.celery import app  
from .sefaz_scraper import SEFAZScraper 


logger = logging.getLogger(__name__)



app.conf.beat_schedule = {
    'coleta-automatica-3dias': {
        'task': 'monitor.utils.tasks.pipeline_coleta_e_processamento',
        'schedule': crontab(day_of_month='*/3'),  # A cada 3 dias
        'args': (
            (date.today() - timedelta(days=3)).strftime('%Y-%m-%d'),
            date.today().strftime('%Y-%m-%d')
        ),
    },
}


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


# Modifique a tarefa verificar_normas_sefaz_task:
@shared_task(bind=True, max_retries=3, time_limit=1800, soft_time_limit=1500)
def verificar_normas_sefaz_task(self):
    logger.info("Iniciando verificação otimizada para Windows")
    
    try:
        # Verificação de conexão mais robusta
        try:
            scraper = SEFAZScraper()
            if not scraper.test_connection():
                logger.error("Falha na conexão com o portal SEFAZ")
                raise ConnectionError("Não foi possível conectar ao portal SEFAZ")
        except Exception as e:
            logger.error(f"Erro ao testar conexão: {str(e)}")
            raise self.retry(exc=e, countdown=60)
        
        # Limita a quantidade e adiciona filtros mais específicos
        normas = NormaVigente.objects.filter(
            Q(data_verificacao__isnull=True) |
            Q(data_verificacao__lt=timezone.now() - timedelta(days=30)),
            Q(tipo__in=['DECRETO', 'LEI', 'ATO NORMATIVO'])
        ).order_by('data_verificacao')[:5]  # Número reduzido para evitar timeout
        
        # Usa conexão persistente
        with IntegradorSEFAZ() as integrador:
            resultados = integrador.verificar_normas_em_lote(normas)
            
        # Processa resultados
        stats = {
            'total': len(resultados),
            'vigentes': sum(1 for r in resultados if r and r.get('status') == 'VIGENTE'),
            'revogadas': sum(1 for r in resultados if r and r.get('status') == 'REVOGADA'),
            'erros': sum(1 for r in resultados if not r or r.get('status') == 'ERRO')
        }
        
        logger.info(f"Verificação concluída: {stats}")
        return stats
        
    except TimeoutError:
        logger.warning("Timeout global - reiniciando task")
        raise self.retry(countdown=120)
    except Exception as e:
        logger.error(f"Erro fatal: {str(e)}", exc_info=True)
        raise

# Pipeline completo: Coleta -> Processamento -> Verificação SEFAZ
@shared_task(bind=True)
def pipeline_coleta_e_processamento(self, data_inicio_str=None, data_fim_str=None):
    """
    Tarefa Celery que executa a coleta, em seguida o processamento de PDFs,
    e por fim a verificação de normas na SEFAZ.
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando pipeline completo de coleta, processamento e verificação SEFAZ.")
    
    # Encadeamento: Coleta -> Processamento -> Verificação SEFAZ
    # Use chain() para garantir que a ordem seja mantida
    workflow = chain(
        coletar_diario_oficial_task.s(data_inicio_str, data_fim_str),
        processar_documentos_pendentes_task.s(),
        verificar_normas_sefaz_task.si()
    )
    
    # Dispara o pipeline encadeado
    workflow.apply_async() # apply_async é melhor para iniciar chains
    
    logger.info(f"[{task_id}] Pipeline completo disparado: Coleta -> Processamento -> Verificação SEFAZ.")
    return {'status': 'PIPELINE_DISPARADO', 'pipeline_task_id': task_id}