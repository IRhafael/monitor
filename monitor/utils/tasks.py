from celery import chain, shared_task
from datetime import datetime, timedelta, date
import logging
from django.utils import timezone
from django.db import transaction
import traceback
from django.db.models import Q, Case, When, Value, CharField
from .diario_scraper import DiarioOficialScraper
from .pdf_processor import PDFProcessor
from monitor.models import Documento, LogExecucao, NormaVigente
from .sefaz_integracao import IntegradorSEFAZ
from celery.schedules import crontab
from diario_oficial.celery import app

logger = logging.getLogger(__name__)

app.conf.beat_schedule = {
    'coleta-automatica-3dias': {
        'task': 'monitor.utils.tasks.pipeline_coleta_e_processamento',
        'schedule': crontab(day_of_month='*/3'),
        'args': (
            (date.today() - timedelta(days=3)).strftime('%Y-%m-%d'),
            date.today().strftime('%Y-%m-%d')
        ),
    },
    'verificacao-normas-diaria': {
        'task': 'monitor.utils.tasks.verificar_normas_sefaz_task',
        'schedule': crontab(hour=3, minute=30),  # Executa diariamente às 3:30 AM
    },
}

@shared_task(bind=True)
def coletar_diario_oficial_task(self, data_inicio_str=None, data_fim_str=None):
    task_id = self.request.id
    logger.info(f"Tarefa Celery 'coletar_diario_oficial_task' [{task_id}] iniciada.")

    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else date.today() - timedelta(days=3)
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else date.today()

        scraper = DiarioOficialScraper()
        documentos_coletados = scraper.coletar_e_salvar_documentos(data_inicio, data_fim)

        LogExecucao.objects.create(
            tipo_execucao='COLETA',
            status='SUCESSO',
            detalhes={
                'documentos_coletados': len(documentos_coletados),
                'periodo': f"{data_inicio} a {data_fim}"
            }
        )
        
        logger.info(f"[{task_id}] Coleta concluída com {len(documentos_coletados)} documentos.")
        return {'status': 'SUCESSO', 'documentos_coletados': len(documentos_coletados)}

    except Exception as e:
        logger.error(f"[{task_id}] Erro na coleta: {str(e)}", exc_info=True)
        LogExecucao.objects.create(
            tipo_execucao='COLETA',
            status='ERRO',
            detalhes={'erro': str(e), 'traceback': traceback.format_exc()}
        )
        raise self.retry(exc=e, countdown=300, max_retries=3)

@shared_task(bind=True)
def processar_documentos_pendentes_task(self, previous_task_result=None):
    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando processamento de documentos pendentes.")

    try:
        processor = PDFProcessor()
        docs_pendentes = Documento.objects.filter(processado=False).order_by('data_publicacao')
        
        if not docs_pendentes.exists():
            logger.info(f"[{task_id}] Nenhum documento pendente para processar.")
            return {'status': 'SEM_PENDENTES'}

        resultados = {
            'sucesso': 0,
            'irrelevantes': 0,
            'erros': 0,
            'normas_identificadas': 0
        }

        for doc in docs_pendentes:
            try:
                resultado = processor.process_document(doc)
                if resultado['status'] == 'SUCESSO':
                    resultados['sucesso'] += 1
                    resultados['normas_identificadas'] += len(resultado.get('normas_extraidas', []))
                elif resultado['status'] == 'IGNORADO_IRRELEVANTE':
                    resultados['irrelevantes'] += 1
                else:
                    resultados['erros'] += 1
            except Exception as e:
                resultados['erros'] += 1
                logger.error(f"[{task_id}] Erro ao processar documento {doc.id}: {str(e)}")

        LogExecucao.objects.create(
            tipo_execucao='PROCESSAMENTO',
            status='SUCESSO',
            detalhes=resultados
        )
        
        logger.info(f"[{task_id}] Processamento concluído: {resultados}")
        return {'status': 'SUCESSO', 'resultados': resultados}

    except Exception as e:
        logger.error(f"[{task_id}] Erro no processamento: {str(e)}", exc_info=True)
        LogExecucao.objects.create(
            tipo_execucao='PROCESSAMENTO',
            status='ERRO',
            detalhes={'erro': str(e)}
        )
        raise self.retry(exc=e, countdown=600, max_retries=3)

@shared_task(bind=True)
def verificar_normas_sefaz_task(self, *_args, **_kwargs):
    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando verificação de normas na SEFAZ.")

    try:
        integrador = IntegradorSEFAZ()
        
        # Query para normas nunca verificadas ou verificadas há mais de 15 dias
        normas = NormaVigente.objects.filter(
            Q(data_verificacao__isnull=True) |
            Q(data_verificacao__lt=timezone.now() - timedelta(days=15))
        ).annotate(
            status_anterior=Case(
                When(situacao='VIGENTE', then=Value('VIGENTE')),
                When(situacao='REVOGADA', then=Value('REVOGADA')),
                default=Value('NAO_VERIFICADO'),
                output_field=CharField()
            )
        ).order_by('data_verificacao')  # Ordena para priorizar as mais antigas

        total_normas = normas.count()
        logger.info(f"[{task_id}] Total de normas para verificar: {total_normas}")

        if not normas.exists():
            logger.info(f"[{task_id}] Nenhuma norma para verificar.")
            return {'status': 'SEM_NORMAS_PENDENTES'}

        # Processa todas as normas de uma vez, mas com tratamento robusto
        mudancas = {
            'novas_vigentes': 0,
            'novas_revogadas': 0,
            'mantidas': 0,
            'erros': 0
        }

        normas_atualizadas = []
        
        with transaction.atomic():
            for norma in normas:
                try:
                    # Verifica a norma individualmente
                    resultado = integrador.buscar_norma_especifica(norma.tipo, norma.numero)
                    
                    # Determina o novo status
                    novo_status = 'VIGENTE' if resultado.get('vigente', False) else 'REVOGADA'
                    
                    # Atualiza a norma
                    norma.situacao = novo_status
                    norma.data_verificacao = timezone.now()
                    norma.detalhes = resultado
                    norma.save()
                    
                    # Contabiliza mudanças
                    if novo_status == 'VIGENTE' and norma.status_anterior != 'VIGENTE':
                        mudancas['novas_vigentes'] += 1
                    elif novo_status == 'REVOGADA' and norma.status_anterior != 'REVOGADA':
                        mudancas['novas_revogadas'] += 1
                    elif novo_status == norma.status_anterior:
                        mudancas['mantidas'] += 1
                    
                    normas_atualizadas.append(norma.id)
                    
                except Exception as e:
                    mudancas['erros'] += 1
                    logger.error(f"[{task_id}] Erro ao verificar norma {norma.id}: {str(e)}")
                    continue

        LogExecucao.objects.create(
            tipo_execucao='VERIFICACAO_SEFAZ',
            status='SUCESSO' if mudancas['erros'] == 0 else 'PARCIAL',
            detalhes={
                'normas_verificadas': len(normas_atualizadas),
                'mudancas': mudancas,
                'normas_com_erro': mudancas['erros']
            }
        )
        
        logger.info(f"[{task_id}] Verificação concluída. Normas verificadas: {len(normas_atualizadas)}")
        logger.info(f"[{task_id}] Mudanças: {mudancas}")
        return {
            'status': 'SUCESSO',
            'normas_verificadas': len(normas_atualizadas),
            'mudancas': mudancas
        }

    except Exception as e:
        logger.error(f"[{task_id}] Erro na verificação: {str(e)}", exc_info=True)
        LogExecucao.objects.create(
            tipo_execucao='VERIFICACAO_SEFAZ',
            status='ERRO',
            detalhes={'erro': str(e), 'traceback': traceback.format_exc()}
        )
        raise self.retry(exc=e, countdown=900, max_retries=2)

@shared_task(bind=True)
def pipeline_coleta_e_processamento(self, data_inicio_str=None, data_fim_str=None):
    task_id = self.request.id
    logger.info(f"[{task_id}] Iniciando pipeline completo.")

    try:
        # Encadeamento das tarefas
        chain(
            coletar_diario_oficial_task.s(data_inicio_str, data_fim_str),
            processar_documentos_pendentes_task.s(),
            verificar_normas_sefaz_task.si()  
        ).apply_async()

        logger.info(f"[{task_id}] Pipeline disparado com sucesso.")
        return {'status': 'PIPELINE_INICIADO'}

    except Exception as e:
        logger.error(f"[{task_id}] Erro ao iniciar pipeline: {str(e)}")
        raise

# Tarefa adicional para verificar apenas normas específicas (útil para debug)
@shared_task(bind=True)
def verificar_normas_especificas_task(self, limite=None):
    """
    Tarefa para verificar um número limitado de normas (útil para testes)
    """
    task_id = self.request.id
    limite = limite or 10
    logger.info(f"[{task_id}] Iniciando verificação de {limite} normas específicas.")

    try:
        normas = NormaVigente.objects.all()[:limite]
        total_normas = normas.count()
        
        logger.info(f"[{task_id}] Verificando {total_normas} normas: IDs {[n.id for n in normas]}")
        
        integrador = IntegradorSEFAZ()
        resultados = integrador.verificar_normas_em_lote(normas)
        
        logger.info(f"[{task_id}] Verificação específica concluída: {len(resultados)} normas verificadas.")
        return {'status': 'SUCESSO', 'normas_verificadas': len(resultados)}

    except Exception as e:
        logger.error(f"[{task_id}] Erro na verificação específica: {str(e)}", exc_info=True)
        raise