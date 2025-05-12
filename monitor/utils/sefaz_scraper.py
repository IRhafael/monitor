# monitor/utils/sefaz_scraper.py
import logging
from django.utils import timezone
from monitor.models import LogExecucao, Norma 
from datetime import date, datetime

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self, max_normas=20):
        self.url_base = "https://www.sefaz.pi.gov.br/"
        self.max_normas = max_normas
        logger.info("Inicializando SEFAZScraper")

    def iniciar_coleta(self):
        """Método principal para iniciar a coleta"""
        from monitor.models import Norma, LogExecucao
        
        logger.info("Iniciando coleta de normas")
        try:
            normas_coletadas = self.coletar_normas()
            normas_salvas = 0
            
            for norma in normas_coletadas:
                # Converte a string de data para objeto date se necessário
                data_norma = norma['data'] if isinstance(norma['data'], date) else datetime.strptime(norma['data'], '%Y-%m-%d').date()
                
                _, created = Norma.objects.get_or_create(
                    tipo=norma['tipo'],
                    numero=norma['numero'],
                    defaults={
                        'data': data_norma,
                        'conteudo': norma.get('conteudo', '')
                    }
                )
                if created:
                    normas_salvas += 1
            
            LogExecucao.objects.create(
                tipo_execucao='SEFAZ',
                status='SUCESSO',
                normas_coletadas=len(normas_coletadas),
                normas_salvas=normas_salvas,
                data_fim=timezone.now(),
                mensagem=f"Coletadas {len(normas_coletadas)} normas, {normas_salvas} novas"
            )
            
            return {
                'status': 'success',
                'normas_coletadas': len(normas_coletadas),
                'normas_novas': normas_salvas
            }
            
        except Exception as e:
            logger.error(f"Erro na coleta: {str(e)}", exc_info=True)
            LogExecucao.objects.create(
                tipo_execucao='SEFAZ',
                status='ERRO',
                data_fim=timezone.now(),
                erro_detalhado=str(e)
            )
            return {
                'status': 'error',
                'message': str(e)
            }

    def coletar_normas(self):
        """Método existente que implementa a lógica real"""
        # Mantenha sua implementação atual aqui
        return [
            {"tipo": "LEI", "numero": "1234", "data": "2023-01-01"},
            {"tipo": "PORTARIA", "numero": "567", "data": "2023-02-01"}
        ]
    