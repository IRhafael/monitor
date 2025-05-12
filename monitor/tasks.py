# monitor/tasks.py
from django.utils import timezone
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from monitor.models import ConfiguracaoColeta, LogExecucao, Documento, NormaVigente
from monitor.utils.diario_scraper import DiarioOficialScraper
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.utils.sefaz_scraper import SEFAZScraper 
from celery import shared_task
import logging 

logger = logging.getLogger(__name__)

from django.utils import timezone

def executar_coleta_completa():
    try:
        logger.info("Iniciando coleta completa")
        
        # Coleta Diário Oficial
        scraper_diario = DiarioOficialScraper()
        docs = scraper_diario.iniciar_coleta()
        
        # Coleta SEFAZ
        scraper_sefaz = SEFAZScraper()
        normas = scraper_sefaz.iniciar_coleta()
        
        # Processa PDFs
        processor = PDFProcessor()
        processados = processor.processar_todos_documentos()
        
        return {
            'status': 'success',
            'documentos': len(docs),
            'normas': len(normas),
            'processados': processados
        }
        
    except Exception as e:
        logger.error(f"Erro fatal: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e)
        }

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

@shared_task
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
        data_atual = timezone.now().strftime("%Y%m%d_%H%M%S")
        
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



@shared_task
def verificar_normas_sefaz():
    """
    Tarefa para verificar normas não verificadas na SEFAZ
    """
    integrador = IntegradorSEFAZ()
    resultados = integrador.verificar_documentos_nao_verificados()
    
    # Gerar relatório
    relatorio = {
        'total_documentos': len(resultados),
        'documentos_com_normas': sum(1 for r in resultados if r['status'] == 'sucesso' and r['normas_encontradas'] > 0),
        'erros': sum(1 for r in resultados if r['status'] == 'erro'),
    }
    
    return relatorio
