import re
import logging
import time
import urllib.parse
from datetime import datetime
from django.utils import timezone
from monitor.models import LogExecucao, Norma
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self, max_normas=20):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.search_url = f"{self.base_url}/search-results"
        self.max_normas = max_normas
        self.driver = None
        self.timeout = 15  # segundos

    def _iniciar_navegador(self):
        """Configura o navegador Selenium com opções otimizadas"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Configurações para evitar detecção como bot
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def _fechar_navegador(self):
        """Fecha o navegador se estiver aberto"""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def verificar_vigencia_norma(self, tipo, numero):
        """Verifica se uma norma específica está vigente"""
        try:
            self._iniciar_navegador()
            
            # Acessa a página de pesquisa
            self.driver.get(self.search_url)
            time.sleep(2)  # Espera inicial
            
            # Localiza e preenche o campo de busca
            search_input = WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search']"))
            )
            
            search_input.clear()
            search_input.send_keys(f"{tipo} {numero}")
            
            # Clica no botão de pesquisa
            search_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            search_button.click()
            
            # Aguarda os resultados
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results-container"))
            )
            
            # Analisa os resultados
            resultados = self.driver.find_elements(By.CSS_SELECTOR, ".result-item")
            
            for resultado in resultados:
                texto = resultado.text.lower()
                if str(numero).lower() in texto and tipo.lower() in texto:
                    return "revogado" not in texto
                    
            return False
            
        except TimeoutException:
            logger.error("Timeout ao aguardar elementos da página")
            return False
        except NoSuchElementException:
            logger.error("Elemento não encontrado na página")
            return False
        except Exception as e:
            logger.error(f"Erro inesperado: {str(e)}")
            return False
        finally:
            self._fechar_navegador()

    def coletar_normas(self):
        """Coleta as últimas normas publicadas"""
        try:
            self._iniciar_navegador()
            self.driver.get(self.search_url)
            
            # Pesquisa genérica para trazer as últimas normas
            search_input = WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search']"))
            )
            search_input.send_keys("norma")
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Aguarda resultados
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item"))
            )
            
            # Processa os resultados
            normas = []
            resultados = self.driver.find_elements(By.CSS_SELECTOR, ".result-item")[:self.max_normas]
            
            for item in resultados:
                try:
                    texto = item.text
                    tipo = self._extrair_tipo(texto)
                    numero = self._extrair_numero(texto)
                    data = self._extrair_data(texto)
                    
                    if tipo and numero:
                        normas.append({
                            'tipo': tipo,
                            'numero': numero,
                            'data': data or datetime.now().date(),
                            'conteudo': texto[:500]  # Limita o conteúdo
                        })
                except Exception as e:
                    logger.warning(f"Erro ao processar item: {str(e)}")
                    continue
                    
            return normas
            
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
        
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return match.group(1).upper()
        return None

    def _extrair_numero(self, texto):
        """Extrai o número da norma do texto"""
        padroes = [
            r'n[º°]?\s*[:\.]?\s*([\d\/\.-]+)',
            r'numero?\s*[:\.]?\s*([\d\/\.-]+)'
        ]
        
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return re.sub(r'[^\d\/]', '', match.group(1))
        return None

    def _extrair_data(self, texto):
        """Extrai a data da norma do texto"""
        match = re.search(r'(\d{2}\/\d{2}\/\d{4})', texto)
        if match:
            try:
                return datetime.strptime(match.group(1), '%d/%m/%Y').date()
            except ValueError:
                return None
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