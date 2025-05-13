import re
from datetime import date, datetime
import logging
from django.utils import timezone
from monitor.models import LogExecucao, Norma  
import requests
from bs4 import BeautifulSoup
from random import uniform
import time
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.consulta_url = f"{self.base_url}/content/consulta"
        self.driver = None

    def iniciar_navegador(self):
        """Configura o navegador Selenium"""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        self.driver = webdriver.Chrome(options=options)

    def fazer_requisicao(self, url):
        """Método seguro para fazer requisições"""
        try:
            time.sleep(uniform(*self.delay))  # Delay aleatório
            response = requests.get(url, headers=self.headers, timeout=15)
            
            if response.status_code == 403:
                logger.error("Acesso proibido (403) - Verifique headers e cookies")
                return None
                
            return response
            
        except Exception as e:
            logger.error(f"Erro na requisição: {str(e)}")
            return None

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
        """Verifica vigência usando Selenium"""
        try:
            if not self.driver:
                self.iniciar_navegador()
                
            # Acessa página de consulta
            self.driver.get(self.consulta_url)
            time.sleep(2)
            
            # Preenche formulário
            self.driver.find_element(By.NAME, "tipoNorma").send_keys(tipo.upper())
            self.driver.find_element(By.NAME, "numeroNorma").send_keys(numero)
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Aguarda resultados
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".resultado-consulta"))
            )
            
            # Analisa resultado
            resultado = self.driver.find_element(By.CSS_SELECTOR, ".resultado-consulta").text
            return "vigente" in resultado.lower()
            
        except Exception as e:
            print(f"Erro na consulta: {str(e)}")
            return False
        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None
        
    def _analisar_resposta(self, html, tipo, numero):
        """Analisa o HTML retornado"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Verifica mensagens de erro
        if "não encontrada" in soup.text.lower():
            return False
            
        # Procura pela norma na tabela de resultados
        resultados = soup.find_all('tr', class_='resultado-norma')
        for resultado in resultados:
            if numero in resultado.text and tipo.upper() in resultado.text:
                return "Revogada" not in resultado.text
                
        return False

    def _formatar_numero_busca(self, numero):
        """Formata o número para a busca na SEFAZ"""
        return numero.replace('/', '%2F').replace(' ', '+')