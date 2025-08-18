import time
from celery import chain, shared_task, group # group não está sendo usado, pode remover se não planeja
from datetime import datetime, timedelta, date
import logging
from django.utils import timezone
from django.db import transaction
import traceback
from django.db.models import Q, F # F não está sendo usado, pode remover
from django.db.models.functions import Length
from .utils.scraper_geral import DiarioOficialScraper
from .utils.pdf_processor import PDFProcessor
## ATENÇÃO: Importações de modelos Django devem ser feitas dentro das funções das tasks para evitar AppRegistryNotReady
from celery.schedules import crontab
from diario_oficial.celery import app
from typing import List, Optional, Dict, Any # Any não está sendo usado, pode remover se não planeja
import os # <--- ADICIONAR ESTA LINHA

logger = logging.getLogger(__name__)

# --- Configuração do Celery Beat (agendador) ---
app.conf.beat_schedule = {
    'coleta-e-processamento-tudo': {
        'task': 'monitor.utils.tasks.coletar_e_processar_tudo',
        'schedule': crontab(minute=0, hour='*/3'),  # A cada 3 horas
        'options': {'expires': 3600 * 2}
    }
}





# --- Task única: executa todos os scrapers e processa os documentos ---
from celery import shared_task

@shared_task(bind=True, name="monitor.utils.tasks.coletar_e_processar_tudo")
def coletar_e_processar_tudo(self):
    """
    Executa todos os scrapers de coleta de documentos (Diário Oficial, SEFAZ, SEFAZ ICMS, etc) e processa os documentos coletados.
    """
    from monitor.models import LogExecucao, Documento
    from .utils.scraper_geral import DiarioOficialScraper, SEFAZScraper, SEFAZICMSScraper
    from .utils.pdf_processor import PDFProcessor
    task_id = self.request.id
    log_entry = LogExecucao.objects.create(tipo_execucao='COLETA_E_PROCESSAMENTO', status='INICIADA', detalhes={'task_id': task_id})
    logger.info(f"[{task_id}] Iniciando coleta e processamento de todos os scrapers.")
    resultados = {}
    erros = []
    try:
        documentos_coletados = []
        # Diário Oficial
        try:
            scraper_diario = DiarioOficialScraper()
            documentos_diario = scraper_diario.coletar_e_salvar_documentos()
            resultados['diario_oficial'] = len(documentos_diario)
            documentos_coletados.extend(documentos_diario)
        except Exception as e:
            logger.error(f"[{task_id}] Erro no scraper Diário Oficial: {e}", exc_info=True)
            erros.append({'scraper': 'diario_oficial', 'erro': str(e)})

        # SEFAZ
        try:
            scraper_sefaz = SEFAZScraper()
            documentos_sefaz = scraper_sefaz.coletar_documentos()
            resultados['sefaz'] = len(documentos_sefaz)
            documentos_coletados.extend(documentos_sefaz)
        except Exception as e:
            logger.error(f"[{task_id}] Erro no scraper SEFAZ: {e}", exc_info=True)
            erros.append({'scraper': 'sefaz', 'erro': str(e)})

        # SEFAZ ICMS
        try:
            scraper_icms = SEFAZICMSScraper()
            documentos_icms = scraper_icms.coletar_documentos()
            resultados['sefaz_icms'] = len(documentos_icms)
            documentos_coletados.extend(documentos_icms)
        except Exception as e:
            logger.error(f"[{task_id}] Erro no scraper SEFAZ ICMS: {e}", exc_info=True)
            erros.append({'scraper': 'sefaz_icms', 'erro': str(e)})

        # IDs de todos os documentos coletados
        ids_documentos = [doc.id for doc in documentos_coletados if hasattr(doc, 'id')]

        # Processa todos os documentos coletados
        try:
            logger.info(f"[{task_id}] Iniciando processamento dos documentos coletados.")
            processor = PDFProcessor()
            sucesso = 0
            falha = 0
            for i, documento in enumerate(Documento.objects.filter(id__in=ids_documentos)):
                try:
                    result = processor.process_document(documento)
                    if result.get('status') == 'SUCESSO':
                        sucesso += 1
                    else:
                        falha += 1
                except Exception as e:
                    falha += 1
                    logger.error(f"[{task_id}] Erro ao processar documento ID {documento.id}: {e}", exc_info=True)
            resultados['processamento_documentos'] = {'sucesso': sucesso, 'falha': falha}
        except Exception as e:
            logger.error(f"[{task_id}] Erro ao processar documentos coletados: {e}", exc_info=True)
            erros.append({'etapa': 'processamento_documentos', 'erro': str(e)})

        log_entry.status = 'SUCESSO' if not erros else 'PARCIAL'
        log_entry.detalhes.update({
            'resultados': resultados,
            'erros': erros
        })
    except Exception as e:
        logger.error(f"[{task_id}] Erro fatal na coleta e processamento: {e}", exc_info=True)
        log_entry.status = 'ERRO'
        log_entry.detalhes.update({'erro_principal': str(e), 'traceback': traceback.format_exc()})
        raise
    finally:
        log_entry.data_fim = timezone.now()
        log_entry.duracao = log_entry.data_fim - log_entry.data_inicio
        log_entry.save()
        logger.info(f"[{task_id}] Task 'coletar_e_processar_tudo' concluída. Status: {log_entry.status}. Detalhes: {log_entry.detalhes}")
    return {'status': log_entry.status, 'resultados': resultados, 'erros': erros}
# monitor/utils/tasks.py