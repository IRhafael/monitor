from datetime import date, datetime
import logging
from django.utils import timezone
from monitor.models import LogExecucao, Norma  
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self, max_normas=20):
        self.url_base = "https://www.sefaz.pi.gov.br/"
        self.max_normas = max_normas
        logger.info("Inicializando SEFAZScraper")

    def iniciar_coleta(self):
        """Método principal para iniciar a coleta"""
        logger.info("Iniciando coleta de normas")
        
        try:
            normas_coletadas = self.coletar_normas()
            normas_salvas = 0
            
            for norma in normas_coletadas:
                # Garanta que a data está no formato correto
                if isinstance(norma['data'], str):
                    try:
                        data_norma = datetime.strptime(norma['data'], '%Y-%m-%d').date()
                    except ValueError:
                        data_norma = datetime.now().date()
                else:
                    data_norma = norma['data']
                
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
        """Implementação real da coleta de normas da SEFAZ"""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            response = requests.get(f"{self.url_base}/legislacao", timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            normas = []
            # Adapte este seletor conforme a estrutura real da página
            for item in soup.select('.item-norma'):
                tipo = item.select_one('.tipo-norma').text.strip()
                numero = item.select_one('.numero-norma').text.strip()
                data_texto = item.select_one('.data-norma').text.strip()
                
                normas.append({
                    'tipo': tipo,
                    'numero': numero,
                    'data': datetime.strptime(data_texto, '%d/%m/%Y').strftime('%Y-%m-%d'),
                    'conteudo': item.select_one('.resumo-norma').text.strip() if item.select_one('.resumo-norma') else ''
                })
                
            return normas[:self.max_normas]
            
        except Exception as e:
            logger.error(f"Erro ao coletar normas: {str(e)}")
            return []
        

    def verificar_vigencia_norma(self, tipo, numero):
        """Verifica se uma norma específica está vigente no site da SEFAZ"""
        try:
            # Implemente a lógica real de busca no site da SEFAZ aqui
            params = {
                'tipo': tipo.upper(),
                'numero': self._formatar_numero_busca(numero)
            }
            
            response = requests.get(f"{self.url_base}/consulta_norma", params=params, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Verifica se a norma está marcada como vigente
            status_element = soup.find('div', class_='norma-status')
            if status_element and 'vigente' in status_element.text.lower():
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Erro ao verificar vigência da norma {tipo} {numero}: {str(e)}")
            return False

    def _formatar_numero_busca(self, numero):
        """Formata o número para a busca na SEFAZ"""
        return numero.replace('/', '%2F').replace(' ', '+')