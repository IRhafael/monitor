# monitor/utils/sefaz_scraper.py
import re
import time
import logging
from datetime import datetime
from django.utils import timezone
from monitor.models import LogExecucao, Norma
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import urllib.parse

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self, max_normas=20):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.search_url = f"{self.base_url}/search-results"
        self.max_normas = max_normas
        self.driver = None
        self.timeout = 20  # segundos

    def _iniciar_navegador(self):
        """Configura o navegador Selenium com opções otimizadas"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--window-size=1280,720")
            
            # Configurações para evitar detecção
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return True
        except Exception as e:
            logger.error(f"Erro ao iniciar navegador: {str(e)}")
            return False

    def _fechar_navegador(self):
        """Fecha o navegador se estiver aberto"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Erro ao fechar navegador: {str(e)}")
            finally:
                self.driver = None

    def verificar_vigencia_norma(self, tipo, numero):
        """Verifica se uma norma específica está vigente"""
        try:
            if not self._iniciar_navegador():
                return False
                
            # Acessa a página de pesquisa
            self.driver.get(self.search_url)
            time.sleep(2)  # Espera inicial

            # Localiza e preenche o campo de busca
            try:
                search_input = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search'], input[type='text']"))
                )
                search_input.clear()
                search_input.send_keys(f"{tipo} {numero}")
                
                # Encontra e clica no botão de pesquisa
                search_button = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "button[type='submit'], button.search-button, button.btn-primary"
                )
                search_button.click()
                
                # Aguarda os resultados - ajuste este seletor conforme necessário
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results, .results-container, .result-item"))
                )
                
                # Analisa os resultados
                resultados = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    ".result-item, .search-result, .norma-item"
                )
                
                for resultado in resultados:
                    texto = resultado.text.lower()
                    if str(numero).lower() in texto and tipo.lower() in texto:
                        return "revogado" not in texto and "cancelado" not in texto
                
                return False
                
            except TimeoutException:
                logger.error("Timeout ao aguardar elementos da página")
                return False
            except NoSuchElementException:
                logger.error("Elemento não encontrado na página")
                return False
                
        except WebDriverException as e:
            logger.error(f"Erro no WebDriver: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado: {str(e)}")
            return False
        finally:
            self._fechar_navegador()

    def coletar_normas(self):
        """Coleta as últimas normas publicadas"""
        try:
            if not self._iniciar_navegador():
                return []

            self.driver.get(self.search_url)
            time.sleep(2)

            # Pesquisa genérica para trazer as últimas normas
            try:
                search_input = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search'], input[type='text']"))
                )
                search_input.send_keys("norma")
                
                search_button = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "button[type='submit'], button.search-button, button.btn-primary"
                )
                search_button.click()
                
                # Aguarda resultados - ajuste este seletor
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item, .search-result, .norma-item"))
                )
                
                # Processa os resultados
                normas = []
                resultados = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    ".result-item, .search-result, .norma-item"
                )[:self.max_normas]
                
                for item in resultados:
                    try:
                        texto = item.text
                        tipo = self._extrair_tipo(texto)
                        numero = self._extrair_numero(texto)
                        data = self._extrair_data(texto)
                        
                        if tipo and numero:
                            normas.append({
                                'tipo': tipo.upper(),
                                'numero': numero,
                                'data': data or datetime.now().date(),
                                'conteudo': texto[:500]  # Limita o conteúdo
                            })
                    except Exception as e:
                        logger.warning(f"Erro ao processar item: {str(e)}")
                        continue
                        
                return normas
                
            except TimeoutException:
                logger.error("Timeout ao coletar normas")
                return []
            except NoSuchElementException:
                logger.error("Elementos não encontrados na página")
                return []
                
        except Exception as e:
            logger.error(f"Erro na coleta de normas: {str(e)}")
            return []
        finally:
            self._fechar_navegador()

    def _extrair_tipo(self, texto):
        """Extrai o tipo da norma do texto"""
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução|Deliberação)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO|DELIBERAÇÃO)'
        ]
        
        texto = texto.replace('\n', ' ')
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extrair_numero(self, texto):
        """Extrai o número da norma do texto"""
        padroes = [
            r'(?:n[º°]?|numero?)\s*[:\.]?\s*([\d\/\.-]+)',
            r'(?:nº|n°|num|number)\s*([\d\/\.-]+)'
        ]
        
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return re.sub(r'[^\d\/]', '', match.group(1)).strip()
        return None

    def _extrair_data(self, texto):
        """Extrai a data da norma do texto"""
        padroes = [
            r'(\d{2}\/\d{2}\/\d{4})',
            r'(\d{2}\.\d{2}\.\d{4})',
            r'(?:publicad[oa]|em)\s*(\d{2}\/\d{2}\/\d{4})'
        ]
        
        for padrao in padroes:
            match = re.search(padrao, texto)
            if match:
                try:
                    data_str = match.group(1).replace('.', '/')
                    return datetime.strptime(data_str, '%d/%m/%Y').date()
                except ValueError:
                    continue
        return None

    def iniciar_coleta(self):
        """Método principal para iniciar a coleta"""
        logger.info("Iniciando coleta de normas")
        
        try:
            normas_coletadas = self.coletar_normas()
            normas_salvas = 0
            
            for norma in normas_coletadas:
                _, created = Norma.objects.get_or_create(
                    tipo=norma['tipo'],
                    numero=norma['numero'],
                    defaults={
                        'data': norma['data'],
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