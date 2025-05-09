# monitor/tasks.py
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from monitor.models import ConfiguracaoColeta, LogExecucao, Documento, NormaVigente
from monitor.utils.diario_scraper import DiarioOficialScraper
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_scraper import SEFAZScraper

logger = logging.getLogger(__name__)

def executar_coleta_completa():
    """
    Executa o processo completo de coleta, processamento e geração de relatórios
    """
    logger.info("Iniciando execução do fluxo completo de coleta")
    
    # Verificar configuração
    try:
        config = ConfiguracaoColeta.objects.first()
        if not config:
            logger.warning("Configuração de coleta não encontrada. Criando configuração padrão.")
            config = ConfiguracaoColeta.objects.create()
    except Exception as e:
        logger.error(f"Erro ao obter configuração: {str(e)}")
        return False
    
    # Verificar se a coleta está ativa
    if not config.ativa:
        logger.info("Coleta desativada nas configurações")
        return False
    
    # Criar registro de log
    log_execucao = LogExecucao.objects.create(
        tipo_execucao='COMPLETO',
        status='SUCESSO',
        mensagem="Iniciando fluxo completo de coleta"
    )
    
    try:
        # 1. Coletar documentos do Diário Oficial
        logger.info("Iniciando coleta de documentos")
        scraper_diario = DiarioOficialScraper(max_docs=config.max_documentos)
        documentos_coletados = scraper_diario.iniciar_coleta()
        
        # 2. Processar documentos coletados
        logger.info("Iniciando processamento de documentos")
        processor = PDFProcessor()
        documentos_processados = processor.processar_todos_documentos()
        
        # 3. Coletar normas da SEFAZ
        logger.info("Iniciando coleta de normas da SEFAZ")
        scraper_sefaz = SEFAZScraper()
        normas_coletadas = scraper_sefaz.iniciar_coleta()
        
        # Atualizar log de execução
        log_execucao.documentos_coletados = len(documentos_coletados)
        log_execucao.normas_coletadas = len(normas_coletadas)
        log_execucao.data_fim = timezone.now()
        log_execucao.mensagem = f"Coleta concluída com sucesso. {len(documentos_coletados)} documentos e {len(normas_coletadas)} normas coletadas."
        log_execucao.save()
        
        # Atualizar configuração
        config.ultima_execucao = timezone.now()
        config.proxima_execucao = timezone.now() + timedelta(hours=config.intervalo_horas)
        config.save()
        
        # Enviar e-mail de notificação, se configurado
        if config.email_notificacao:
            enviar_email_notificacao(config.email_notificacao, log_execucao)
        
        return True
    
    except Exception as e:
        logger.error(f"Erro durante a execução do fluxo completo: {str(e)}")
        
        # Atualizar log de execução
        log_execucao.status = 'ERRO'
        log_execucao.data_fim = timezone.now()
        log_execucao.mensagem = "Erro durante o fluxo de coleta"
        log_execucao.erro_detalhado = str(e)
        log_execucao.save()
        
        # Enviar e-mail de notificação de erro, se configurado
        if config.email_notificacao and config.notificar_erros:
            enviar_email_erro(config.email_notificacao, log_execucao)
        
        return False

def verificar_coletas_programadas():
    """
    Verifica se há coletas programadas para execução
    """
    logger.info("Verificando coletas programadas")
    
    try:
        config = ConfiguracaoColeta.objects.first()
        
        if not config:
            logger.warning("Configuração de coleta não encontrada")
            return False
        
        if not config.ativa:
            logger.info("Coleta desativada nas configurações")
            return False
        
        agora = timezone.now()
        
        # Se não houver próxima execução definida ou se já passou o horário
        if not config.proxima_execucao or agora >= config.proxima_execucao:
            logger.info(f"Executando coleta programada. Última execução: {config.ultima_execucao}")
            return executar_coleta_completa()
        else:
            logger.info(f"Nenhuma coleta programada para agora. Próxima execução: {config.proxima_execucao}")
            return False
    
    except Exception as e:
        logger.error(f"Erro ao verificar coletas programadas: {str(e)}")
        return False

def gerar_relatorio_excel():
    """
    Gera relatórios Excel com os dados coletados
    """
    from openpyxl import Workbook
    from django.core.files.base import ContentFile
    import os
    
    logger.info("Gerando relatórios Excel")
    
    try:
        # Criar diretório para relatórios se não existir
        relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
        os.makedirs(relatorios_dir, exist_ok=True)
        
        # Data para o nome do arquivo
        data_atual = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. Gerar relatório de documentos do Diário Oficial
        wb_docs = Workbook()
        ws_docs = wb_docs.active
        ws_docs.title = "Documentos"
        
        # Adicionar cabeçalho
        ws_docs.append(["Título", "Data de Publicação", "URL", "Resumo", "Data da Coleta"])
        
        # Adicionar dados
        documentos = Documento.objects.all().order_by('-data_publicacao')
        for doc in documentos:
            ws_docs.append([
                doc.titulo,
                doc.data_publicacao.strftime("%d/%m/%Y") if doc.data_publicacao else "",
                doc.url_original,
                doc.resumo,
                doc.data_coleta.strftime("%d/%m/%Y %H:%M") if doc.data_coleta else ""
            ])
        
        # Ajustar largura das colunas
        for col in ws_docs.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = min(len(str(cell.value)), 100)
                except:
                    pass
            adjusted_width = max_length + 2
            ws_docs.column_dimensions[column].width = adjusted_width
        
        # Salvar arquivo
        arquivo_documentos = os.path.join(relatorios_dir, f"documentos_{data_atual}.xlsx")
        wb_docs.save(arquivo_documentos)
        
        # 2. Gerar relatório de normas vigentes
        wb_normas = Workbook()
        ws_normas = wb_normas.active
        ws_normas.title = "Normas Vigentes"
        
        # Adicionar cabeçalho
        ws_normas.append(["Tipo", "Número", "Data", "Situação", "URL", "Data da Coleta"])
        
        # Adicionar dados
        normas = NormaVigente.objects.all().order_by('tipo', 'numero')
        for norma in normas:
            ws_normas.append([
                norma.get_tipo_display(),
                norma.numero,
                norma.data.strftime("%d/%m/%Y") if norma.data else "",
                norma.situacao,
                norma.url,
                norma.data_coleta.strftime("%d/%m/%Y %H:%M") if norma.data_coleta else ""
            ])
        
        # Ajustar largura das colunas
        for col in ws_normas.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = min(len(str(cell.value)), 100)
                except:
                    pass
            adjusted_width = max_length + 2
            ws_normas.column_dimensions[column].width = adjusted_width
        
        # Salvar arquivo
        arquivo_normas = os.path.join(relatorios_dir, f"normas_vigentes_{data_atual}.xlsx")
        wb_normas.save(arquivo_normas)
        
        logger.info(f"Relatórios gerados com sucesso: {arquivo_documentos}, {arquivo_normas}")
        
        return {
            "documentos": arquivo_documentos,
            "normas": arquivo_normas
        }
    
    except Exception as e:
        logger.error(f"Erro ao gerar relatórios Excel: {str(e)}")
        return None

def enviar_email_notificacao(email, log_execucao):
    """
    Envia e-mail de notificação sobre a execução bem-sucedida
    """
    try:
        assunto = f"[Diário Oficial PI] Coleta concluída com sucesso - {timezone.now().strftime('%d/%m/%Y %H:%M')}"
        
        mensagem = f"""
        Olá,
        
        A coleta de dados do Diário Oficial do Piauí e SEFAZ/PI foi concluída com sucesso.
        
        Resumo da execução:
        - Tipo de execução: {log_execucao.get_tipo_execucao_display()}
        - Documentos coletados: {log_execucao.documentos_coletados}
        - Normas coletadas: {log_execucao.normas_coletadas}
        - Hora de início: {log_execucao.data_inicio.strftime('%d/%m/%Y %H:%M:%S')}
        - Hora de conclusão: {log_execucao.data_fim.strftime('%d/%m/%Y %H:%M:%S')}
        
        Acesse o sistema para visualizar os detalhes.
        
        Atenciosamente,
        Sistema de Monitoramento do Diário Oficial do Piauí
        """
        
        send_mail(
            assunto,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        
        logger.info(f"E-mail de notificação enviado para {email}")
        
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail de notificação: {str(e)}")

def enviar_email_erro(email, log_execucao):
    """
    Envia e-mail de notificação sobre erros na execução
    """
    try:
        assunto = f"[Diário Oficial PI] ERRO na coleta - {timezone.now().strftime('%d/%m/%Y %H:%M')}"
        
        mensagem = f"""
        Olá,
        
        Ocorreu um erro durante a coleta de dados do Diário Oficial do Piauí e SEFAZ/PI.
        
        Detalhes do erro:
        - Tipo de execução: {log_execucao.get_tipo_execucao_display()}
        - Hora de início: {log_execucao.data_inicio.strftime('%d/%m/%Y %H:%M:%S')}
        - Hora de conclusão: {log_execucao.data_fim.strftime('%d/%m/%Y %H:%M:%S')}
        - Mensagem: {log_execucao.mensagem}
        
        Erro detalhado:
        {log_execucao.erro_detalhado}
        
        Acesse o sistema para verificar o problema.
        
        Atenciosamente,
        Sistema de Monitoramento do Diário Oficial do Piauí
        """
        
        send_mail(
            assunto,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        
        logger.info(f"E-mail de notificação de erro enviado para {email}")
        
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail de notificação de erro: {str(e)}")
