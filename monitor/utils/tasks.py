# monitor/utils/tasks.py
import time
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


def verificar_normas_sefaz_task(self, *args, **kwargs):
    logger.info("Iniciando verificação para SEFAZ")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = None
    try:
        logger.info("Inicializando WebDriver...")
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("WebDriver inicializado.")

        url_sefaz = "https://portaldalegislacao.sefaz.pi.gov.br" # Substitua pela URL da página de busca real
        logger.info(f"Acessando URL: {url_sefaz}")
        driver.get(url_sefaz)
        logger.info(f"Página atual: {driver.current_url}")
        logger.info(f"Título da página: {driver.title}")

        try:

            logger.info("Página de busca carregada (elemento esperado encontrado).")
        except Exception as e:
            logger.error(f"Elemento de página de busca não encontrado: {e}")
            driver.save_screenshot("/tmp/sefaz_pagina_busca_nao_carregada.png")
            return {'total': 0, 'vigentes': 0, 'revogadas': 0, 'erros': 1, 'detalhes': f"Página de busca não carregada: {e}"}


        total = 0 # Sua lógica para preencher estes valores
        vigentes = 0
        revogadas = 0
        erros_logica = 0

        # Seus prints de depuração podem se tornar logs aqui para ver o que está acontecendo
        logger.info(f"Dados extraídos: Total={total}, Vigentes={vigentes}, Revogadas={revogadas}, ErrosLógica={erros_logica}")

        # --- FIM DA LÓGICA DE INTERAÇÃO COM A PÁGINA ---

        logger.info("Verificação concluída")
        return {'total': total, 'vigentes': vigentes, 'revogadas': revogadas, 'erros': erros_logica}

    except Exception as e:
        logger.error(f"Erro fatal na tarefa verificar_normas_sefaz_task: {e}", exc_info=True)
        if driver:
            try:
                driver.save_screenshot(f"/tmp/sefaz_erro_fatal_{self.request.id}.png")
                logger.info(f"Screenshot salvo em /tmp/sefaz_erro_fatal_{self.request.id}.png")
            except Exception as se:
                logger.error(f"Não foi possível salvar screenshot: {se}")
        return {'total': 0, 'vigentes': 0, 'revogadas': 0, 'erros': 1, 'detalhes': f"Erro fatal: {e}"}
    finally:
        if driver:
            driver.quit()
# Pipeline completo: Coleta -> Processamento -> Verificação SEFAZ
@shared_task(bind=True)
def pipeline_coleta_e_processamento(self, data_inicio_str=None, data_fim_str=None):

    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando pipeline completo de coleta, processamento e verificação SEFAZ.")

    workflow = chain(
        coletar_diario_oficial_task.s(data_inicio_str, data_fim_str),
        processar_documentos_pendentes_task.s(),
        verificar_normas_sefaz_task.si()
    )
    
    # Dispara o pipeline encadeado
    workflow.apply_async() # apply_async é melhor para iniciar chains
    
    logger.info(f"[{task_id}] Pipeline completo disparado: Coleta -> Processamento -> Verificação SEFAZ.")
    return {'status': 'PIPELINE_DISPARADO', 'pipeline_task_id': task_id}