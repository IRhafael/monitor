# monitor/utils/tasks.py

import time
from celery import chain, shared_task, group # group não está sendo usado, pode remover se não planeja
from datetime import datetime, timedelta, date
import logging
from django.utils import timezone
from django.db import transaction
import traceback
from django.db.models import Q, F # F não está sendo usado, pode remover
from django.db.models.functions import Length
from .utils.diario_scraper import DiarioOficialScraper
from .utils.pdf_processor import PDFProcessor
from monitor.models import Documento, LogExecucao, NormaVigente
from .utils.sefaz_integracao import IntegradorSEFAZ
from celery.schedules import crontab
from diario_oficial.celery import app
from typing import List, Optional, Dict, Any # Any não está sendo usado, pode remover se não planeja
import os # <--- ADICIONAR ESTA LINHA

logger = logging.getLogger(__name__)

# --- Configuração do Celery Beat (agendador) ---
# ... (seu beat_schedule)
app.conf.beat_schedule = { #
    'pipeline-coleta-processamento-diario': { #
        'task': 'monitor.utils.tasks.pipeline_coleta_e_processamento_automatica', #
        'schedule': crontab(hour=3, minute=0),  # Ex: Todo dia às 03:00 AM #
        # 'schedule': crontab(minute='*/30'), # Para testes: a cada 30 minutos
        'args': (3,), # Coleta dos últimos 3 dias #
        'options': {'expires': 3600 * 2} # Tarefa expira se não iniciar em 2h
    }, #
    'verificacao-sefaz-semanal': { #
        'task': 'monitor.utils.tasks.verificar_normas_sefaz_task', #
        'schedule': crontab(day_of_week='sunday', hour=5, minute=0), # Todo domingo às 05:00 AM #
        'options': {'expires': 3600 * 4} #
    } #
} #


# --- Tarefa de Coleta do Diário Oficial ---
# ... (coletar_diario_oficial_task como na sua última versão ou na minha sugestão anterior)
@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60) # Retry a cada 5 min #
def coletar_diario_oficial_task(self, data_inicio_str: Optional[str] = None, data_fim_str: Optional[str] = None, dias_retroativos: Optional[int] = None): #
    task_id = self.request.id #
    log_entry = LogExecucao.objects.create(tipo_execucao='COLETA', status='INICIADA', detalhes={'task_id': task_id}) #
    logger.info(f"Tarefa Celery 'coletar_diario_oficial_task' [{task_id}] iniciada.") #

    documentos_salvos_count = 0 #
    erros_coleta = [] #

    try: #
        if dias_retroativos is not None: #
            data_fim = timezone.now().date() #
            data_inicio = data_fim - timedelta(days=dias_retroativos) #
            logger.info(f"[{task_id}] Coletando por {dias_retroativos} dias retroativos: de {data_inicio} a {data_fim}") #
        elif data_inicio_str and data_fim_str: #
            data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date() #
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date() #
        else: # Fallback para 3 dias se nada for especificado #
            data_fim = timezone.now().date() #
            data_inicio = data_fim - timedelta(days=3) #
            logger.info(f"[{task_id}] Datas não fornecidas nem dias_retroativos. Usando os últimos 3 dias: de {data_inicio} a {data_fim}") #

        scraper = DiarioOficialScraper() #
        resultados_coleta = scraper.coletar_e_salvar_documentos(data_inicio, data_fim) #
        documentos_salvos_count = len(resultados_coleta) #

        log_entry.status = 'SUCESSO' #
        log_entry.detalhes.update({ #
            'documentos_processados_pelo_scraper': documentos_salvos_count, #
            'datas_coletadas': f"{data_inicio.strftime('%Y-%m-%d')} a {data_fim.strftime('%Y-%m-%d')}", #
            'erros': erros_coleta #
        }) #

    except Exception as e: #
        logger.error(f"[{task_id}] Erro na tarefa de coleta do Diário Oficial: {e}", exc_info=True) #
        log_entry.status = 'ERRO' #
        log_entry.detalhes.update({'erro_principal': str(e), 'traceback': traceback.format_exc()}) #
        raise #
    finally: #
        log_entry.data_fim = timezone.now() #
        log_entry.duracao = log_entry.data_fim - log_entry.data_inicio #
        log_entry.documentos_coletados = documentos_salvos_count #
        log_entry.save() #
        logger.info(f"[{task_id}] Tarefa Celery 'coletar_diario_oficial_task' concluída. Status: {log_entry.status}. Detalhes: {log_entry.detalhes}") #

    return {'status': log_entry.status, 'detalhes': log_entry.detalhes} #


# --- Tarefa de Processamento de Documentos Pendentes ---
@shared_task(bind=True, max_retries=2, default_retry_delay=10*60)
def processar_documentos_pendentes_task(self, previous_task_result: Optional[Dict] = None, document_ids: Optional[List[int]] = None): #
    task_id = self.request.id #
    log_entry = LogExecucao.objects.create(tipo_execucao='PROCESSAMENTO_PDF', status='INICIADA', detalhes={'task_id': task_id}) #
    logger.info(f"[{task_id}] Tarefa Celery 'processar_documentos_pendentes_task' iniciada.") #

    sucesso_count = 0 #
    irrelevantes_count = 0 #
    falhas_processamento_count = 0 #
    ids_falha = [] #
    
    DELAY_ENTRE_DOCUMENTOS = int(os.environ.get("PDF_PROCESS_DELAY", 5)) #

    try: #
        processor = PDFProcessor() #
        if document_ids: #
            documentos_a_processar = Documento.objects.filter(id__in=document_ids, processado=False).order_by('data_publicacao') #
            log_entry.detalhes['tipo_selecao'] = 'IDs específicos' #
            log_entry.detalhes['ids_solicitados'] = document_ids #
        elif previous_task_result and previous_task_result.get('status') == 'SUCESSO': #
            documentos_a_processar = Documento.objects.filter(processado=False).order_by('data_publicacao') #
            log_entry.detalhes['tipo_selecao'] = 'Todos os pendentes (pós-coleta)' #
        else: #
            documentos_a_processar = Documento.objects.filter(processado=False).order_by('data_publicacao') #
            log_entry.detalhes['tipo_selecao'] = 'Todos os pendentes (geral)' #
        
        total_a_processar = documentos_a_processar.count() #
        log_entry.detalhes['total_documentos_para_processar'] = total_a_processar #
        logger.info(f"[{task_id}] Encontrados {total_a_processar} documentos para processar.") #

        if total_a_processar == 0: #
            log_entry.status = 'SUCESSO' #
            log_entry.detalhes['message'] = 'Nenhum documento pendente para processar.' #
        else: #
            for i, documento in enumerate(documentos_a_processar): #
                logger.info(f"[{task_id}] Processando documento {i+1}/{total_a_processar} (ID: {documento.id})") #
                try: #
                    with transaction.atomic(): # Atomicidade por documento #
                        process_result = processor.process_document(documento) #
                    
                    if process_result.get('status') == 'SUCESSO': #
                        sucesso_count += 1 #
                    elif process_result.get('status') == 'IGNORADO_IRRELEVANTE': #
                        irrelevantes_count += 1 #
                    else: # status == 'ERRO' #
                        falhas_processamento_count += 1 #
                        ids_falha.append(documento.id) #
                        logger.error(f"[{task_id}] Falha ao processar documento ID {documento.id}: {process_result.get('message', 'Erro desconhecido no process_document')}") #
                except Exception as doc_e: # Erro mais sério, fora do process_document ou no save #
                    falhas_processamento_count += 1 #
                    ids_falha.append(documento.id) #
                    logger.error(f"[{task_id}] Exceção crítica ao processar documento ID {documento.id}: {doc_e}", exc_info=True) #
                    documento.processado = True #
                    documento.resumo_ia = f"Erro crítico no processamento: {str(doc_e)}" #
                    documento.save(update_fields=['processado', 'resumo_ia']) #
                
                if i < total_a_processar - 1: #
                    logger.info(f"[{task_id}] Aguardando {DELAY_ENTRE_DOCUMENTOS}s antes do próximo documento...") #
                    time.sleep(DELAY_ENTRE_DOCUMENTOS) #
            
            if falhas_processamento_count == total_a_processar and total_a_processar > 0 : #
                 log_entry.status = 'ERRO' #
            elif falhas_processamento_count > 0: #
                log_entry.status = 'PARCIAL' #
            else: #
                log_entry.status = 'SUCESSO' #

            log_entry.detalhes.update({ #
                'processados_com_sucesso': sucesso_count, #
                'documentos_irrelevantes': irrelevantes_count, #
                'falhas_no_processamento': falhas_processamento_count, #
                'ids_com_falha': ids_falha, #
                'total_analisados_nesta_execucao': total_a_processar #
            }) #
        
    except Exception as e: # Erro fatal na própria tarefa (ex: consulta ao DB falhou) #
        logger.error(f"[{task_id}] Erro fatal na tarefa de processamento de PDFs: {e}", exc_info=True) #
        log_entry.status = 'ERRO' #
        log_entry.detalhes.update({'erro_principal': str(e), 'traceback': traceback.format_exc()}) #
        raise # Relança para Celery #
    finally: #
        log_entry.data_fim = timezone.now() #
        log_entry.duracao = log_entry.data_fim - log_entry.data_inicio #
        log_entry.documentos_processados = sucesso_count + irrelevantes_count #
        log_entry.save() #
        logger.info(f"[{task_id}] Tarefa Celery 'processar_documentos_pendentes_task' concluída. Status: {log_entry.status}. Detalhes: {log_entry.detalhes}") #
        
    if log_entry.status == 'ERRO' and total_a_processar > 0 and (sucesso_count + irrelevantes_count + falhas_processamento_count == 0) : #
        pass #

    return {'status': log_entry.status, 'results': log_entry.detalhes} #


# --- Tarefa de Verificação de Normas na SEFAZ ---
# ... (verificar_normas_sefaz_task como na sua última versão ou na minha sugestão anterior)
@shared_task(bind=True, max_retries=2, default_retry_delay=15*60) #
def verificar_normas_sefaz_task(self, norma_ids: Optional[List[int]] = None): #
    task_id = self.request.id #
    log_entry = LogExecucao.objects.create(tipo_execucao='VERIFICACAO_SEFAZ', status='INICIADA', detalhes={'task_id': task_id}) #
    logger.info(f"[{task_id}] Tarefa Celery 'verificar_normas_sefaz_task' iniciada.") #

    normas_verificadas_pelo_integrador = 0 #
    normas_com_status_alterado = 0 #
    erros_verificacao = [] #

    try: #
        integrador_sefaz = IntegradorSEFAZ() #
        
        if norma_ids:
            # Filtra apenas IDs numéricos válidos
            norma_ids_filtrados = [int(i) for i in norma_ids if str(i).isdigit()]
            normas_para_verificar_qs = NormaVigente.objects.filter(id__in=norma_ids_filtrados).annotate( #
                numero_len=Length('numero') #
            ).exclude( #
                Q(tipo__isnull=True) | Q(tipo='') | #
                Q(numero__isnull=True) | Q(numero='') | #
                Q(numero_len__lt=3)  #
            ).order_by('data_verificacao') #
            log_entry.detalhes['tipo_selecao'] = 'IDs específicos' #
            log_entry.detalhes['ids_solicitados'] = norma_ids_filtrados #
        else: # Verifica normas que precisam de atualização (não verificadas ou verificadas há muito tempo) #
            trinta_dias_atras = timezone.now() - timedelta(days=30) #
            normas_para_verificar_qs = NormaVigente.objects.annotate( #
                numero_len=Length('numero') #
            ).filter( #
                Q(data_verificacao__isnull=True) | Q(data_verificacao__lt=trinta_dias_atras) #
            ).exclude( #
                Q(tipo__isnull=True) | Q(tipo__exact='') | #
                Q(numero__isnull=True) | Q(numero__exact='') | #
                Q(numero_len__lt=3) #
            ).order_by('data_verificacao') # Mais antigas primeiro #
            log_entry.detalhes['tipo_selecao'] = 'Automática (desatualizadas ou não verificadas)' #
        
        total_a_verificar = normas_para_verificar_qs.count() #
        log_entry.detalhes['total_normas_para_verificar'] = total_a_verificar #
        logger.info(f"[{task_id}] Encontradas {total_a_verificar} normas para verificar na SEFAZ.") #

        if total_a_verificar == 0: #
            log_entry.status = 'SUCESSO' #
            log_entry.detalhes['message'] = 'Nenhuma norma necessitando de verificação encontrada.' #
        else: #
            resultados_lote = integrador_sefaz.verificar_normas_em_lote(list(normas_para_verificar_qs)) #
            normas_verificadas_pelo_integrador = resultados_lote.get('processadas', 0) #
            normas_com_status_alterado = resultados_lote.get('alteradas', 0) #
            erros_verificacao = resultados_lote.get('erros_detalhados', []) #

            if erros_verificacao and normas_verificadas_pelo_integrador < total_a_verificar : #
                log_entry.status = 'PARCIAL' if normas_verificadas_pelo_integrador > 0 else 'ERRO' #
            else: #
                log_entry.status = 'SUCESSO' #
            
            log_entry.detalhes.update({ #
                'normas_processadas_pelo_integrador': normas_verificadas_pelo_integrador, #
                'normas_com_status_alterado': normas_com_status_alterado, #
                'erros_na_verificacao_sefaz': erros_verificacao, #
            }) #

    except Exception as e: #
        logger.error(f"[{task_id}] Erro fatal na tarefa de verificação de normas SEFAZ: {e}", exc_info=True) #
        log_entry.status = 'ERRO' #
        log_entry.detalhes.update({'erro_principal': str(e), 'traceback': traceback.format_exc()}) #
        raise # Relança para Celery #
    finally: #
        log_entry.data_fim = timezone.now() #
        log_entry.duracao = log_entry.data_fim - log_entry.data_inicio #
        log_entry.normas_verificadas = normas_verificadas_pelo_integrador #
        log_entry.save() #
        logger.info(f"[{task_id}] Tarefa Celery 'verificar_normas_sefaz_task' concluída. Status: {log_entry.status}. Detalhes: {log_entry.detalhes}") #
        
    if log_entry.status == 'ERRO' and normas_verificadas_pelo_integrador == 0 and total_a_verificar > 0: #
        pass #

    return {'status': log_entry.status, 'results': log_entry.detalhes} #


# --- Pipeline Completo de Coleta e Processamento ---
@shared_task(bind=True, name="monitor.utils.tasks.pipeline_coleta_e_processamento_automatica") #
def pipeline_coleta_e_processamento_automatica(self, dias_retroativos_coleta: int = 3): #
    pipeline_task_id = self.request.id #
    logger.info(f"[{pipeline_task_id}] Iniciando PIPELINE AUTOMÁTICO de coleta ({dias_retroativos_coleta} dias), processamento e verificação SEFAZ.") #
    
    log_pipeline = LogExecucao.objects.create( #
        tipo_execucao='PIPELINE_AUTOMATICO', #
        status='INICIADA', #
        detalhes={'pipeline_task_id': pipeline_task_id, 'dias_coleta': dias_retroativos_coleta} #
    ) #

    try: #
        workflow = chain( #
            coletar_diario_oficial_task.s(dias_retroativos=dias_retroativos_coleta), #
            processar_documentos_pendentes_task.s(), #
            verificar_normas_sefaz_task.s() #
        ) #
        
        async_result = workflow.apply_async() #
        
        log_pipeline.detalhes['celery_group_id'] = async_result.id #
        log_pipeline.status = 'EM_PROGRESSO' #
        logger.info(f"[{pipeline_task_id}] Pipeline disparado com ID de grupo Celery: {async_result.id}") #

    except Exception as e: #
        logger.error(f"[{pipeline_task_id}] Erro ao disparar o pipeline: {e}", exc_info=True) #
        log_pipeline.status = 'ERRO_DISPARO' #
        log_pipeline.detalhes.update({'erro_disparo': str(e), 'traceback_disparo': traceback.format_exc()}) #
    
    finally: #
        if log_pipeline.status != 'EM_PROGRESSO': #
            log_pipeline.data_fim = timezone.now() #
            log_pipeline.duracao = log_pipeline.data_fim - log_pipeline.data_inicio #
        log_pipeline.save() #

    return {'status': log_pipeline.status, 'pipeline_task_id': pipeline_task_id, 'celery_group_id': log_pipeline.detalhes.get('celery_group_id')} #

@shared_task(bind=True, name="monitor.utils.tasks.pipeline_manual_completo") #
def pipeline_manual_completo(self, data_inicio_str: str, data_fim_str: str): #
    pipeline_task_id = self.request.id #
    logger.info(f"[{pipeline_task_id}] Iniciando PIPELINE MANUAL de coleta (de {data_inicio_str} a {data_fim_str}), processamento e verificação SEFAZ.") #
    
    log_pipeline = LogExecucao.objects.create( #
        tipo_execucao='PIPELINE_MANUAL', #
        status='INICIADA', #
        detalhes={ #
            'pipeline_task_id': pipeline_task_id, #
            'data_inicio_coleta': data_inicio_str, #
            'data_fim_coleta': data_fim_str #
        } #
    ) #
    try: #
        workflow = chain( #
            coletar_diario_oficial_task.s(data_inicio_str=data_inicio_str, data_fim_str=data_fim_str), #
            processar_documentos_pendentes_task.s(), #
            verificar_normas_sefaz_task.s() #
        ) #
        async_result = workflow.apply_async() #
        log_pipeline.detalhes['celery_group_id'] = async_result.id #
        log_pipeline.status = 'EM_PROGRESSO' #
        logger.info(f"[{pipeline_task_id}] Pipeline manual disparado com ID de grupo Celery: {async_result.id}") #
    except Exception as e: #
        logger.error(f"[{pipeline_task_id}] Erro ao disparar o pipeline manual: {e}", exc_info=True) #
        log_pipeline.status = 'ERRO_DISPARO' #
        log_pipeline.detalhes.update({'erro_disparo': str(e), 'traceback_disparo': traceback.format_exc()}) #
    finally: #
        if log_pipeline.status != 'EM_PROGRESSO': #
            log_pipeline.data_fim = timezone.now() #
            log_pipeline.duracao = log_pipeline.data_fim - log_pipeline.data_inicio #
        log_pipeline.save() #

    return {'status': log_pipeline.status, 'pipeline_task_id': pipeline_task_id, 'celery_group_id': log_pipeline.detalhes.get('celery_group_id')} #


# --- Tarefas Individuais para Controle Mais Fino (se necessário pela UI) ---

@shared_task(bind=True) #
def processar_documentos_especificos_task(self, document_ids: List[int]): #
    if not document_ids: #
        logger.warning(f"[{self.request.id}] Chamada para processar documentos específicos sem IDs.") #
        return {'status': 'FALHA', 'message': 'Nenhum ID de documento fornecido.'} #
    
    logger.info(f"[{self.request.id}] Disparando processamento para IDs específicos: {document_ids}") #
    async_res = processar_documentos_pendentes_task.s(document_ids=document_ids).apply_async() #
    return {'status': 'DISPARADA', 'task_id': async_res.id}


@shared_task(bind=True) #
def verificar_normas_especificas_sefaz_task(self, norma_ids: List[int]): #
    if not norma_ids: #
        logger.warning(f"[{self.request.id}] Chamada para verificar normas específicas sem IDs.") #
        return {'status': 'FALHA', 'message': 'Nenhum ID de norma fornecido.'} #
        
    logger.info(f"[{self.request.id}] Disparando verificação SEFAZ para IDs de norma específicos: {norma_ids}") #
    async_res = verificar_normas_sefaz_task.s(norma_ids=norma_ids).apply_async() #
    return {'status': 'DISPARADA', 'task_id': async_res.id} #

