import re
import time
import logging
import urllib.parse
from datetime import datetime
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (TimeoutException, 
                                      NoSuchElementException, 
                                      WebDriverException)
from selenium.webdriver.chrome.service import Service as ChromeService
from contextlib import contextmanager
import os

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.search_url = f"{self.base_url}/search-results"
        self.driver = None
        self.timeout = 30
        self.max_retries = 2
        self.chrome_service = ChromeService(
            log_path='chromedriver.log',
            service_args=['--silent', '--disable-logging']
        )

    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto para sessão do navegador"""
        try:
            if not self._iniciar_navegador():
                raise WebDriverException("Não foi possível iniciar o navegador")
            yield self.driver
        finally:
            self._fechar_navegador()

    def _iniciar_navegador(self):
        """Configuração otimizada do navegador"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)

            self.driver = webdriver.Chrome(
                service=self.chrome_service,
                options=chrome_options
            )
            self.driver.set_page_load_timeout(self.timeout)
            return True
        except Exception as e:
            logger.error(f"Erro ao iniciar navegador: {str(e)}")
            return False

    def _fechar_navegador(self):
        """Fecha o navegador corretamente"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Erro ao fechar navegador: {str(e)}")
            finally:
                self.driver = None

    def testar_conexao(self):
        """Testa a conexão com o portal"""
        try:
            with self.browser_session():
                self.driver.get(self.base_url)
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body")))
                return "SEFAZ" in self.driver.title or "sefaz" in self.driver.current_url
        except Exception as e:
            logger.error(f"Falha no teste de conexão: {str(e)}")
            return False

    def verificar_vigencia_norma(self, tipo, numero):
        """Verifica se uma norma está vigente"""
        tipo = tipo.upper().strip()
        numero = re.sub(r'[^\d/]', '', str(numero)).strip()
        
        for tentativa in range(1, self.max_retries + 1):
            try:
                with self.browser_session():
                    # Tentativa 1: URL direta
                    status = self._verificar_por_url_direta(tipo, numero)
                    if status is not None:
                        return status
                    
                    # Tentativa 2: Pesquisa
                    encontrada = self._pesquisar_norma(tipo, numero)
                    if encontrada is None:
                        return False
                        
                    return self._extrair_status_norma() or True
            except Exception as e:
                logger.error(f"Tentativa {tentativa} falhou: {str(e)}")
                if tentativa == self.max_retries:
                    return False
                time.sleep(2 ** tentativa)  # Backoff exponencial

    def _verificar_por_url_direta(self, tipo, numero):
        """Tenta acessar diretamente a norma"""
        try:
            url = f"{self.base_url}/{tipo.lower()}/{numero}"
            self.driver.get(url)
            
            if "revogado" in self.driver.page_source.lower():
                return False
            if "vigente" in self.driver.page_source.lower():
                return True
            return None
        except Exception:
            return None

    def _pesquisar_norma(self, tipo, numero):
        """Pesquisa a norma no portal"""
        try:
            query = f"{tipo} {numero}"
            url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
            self.driver.get(url)
            
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item, .search-result")))
                
            return bool(self.driver.find_elements(By.CSS_SELECTOR, ".result-item, .search-result"))
        except TimeoutException:
            logger.warning("Timeout na pesquisa - nenhum resultado encontrado")
            return None
        except Exception as e:
            logger.error(f"Erro na pesquisa: {str(e)}")
            return None

    def _extrair_status_norma(self):
        """Extrai o status da norma nos resultados"""
        try:
            resultados = self.driver.find_elements(
                By.CSS_SELECTOR, ".result-item, .search-result"
            )
            
            for resultado in resultados[:3]:  # Analisa apenas os 3 primeiros
                texto = resultado.text.lower()
                if "revogado" in texto or "cancelado" in texto:
                    return False
                if "vigente" in texto:
                    return True
                    
            return True  # Default conservador
        except Exception as e:
            logger.error(f"Erro ao extrair status: {str(e)}")
            return None

    def testar_verificacao_norma(self, tipo, numero):
        """Método de teste completo para uma norma"""
        print(f"\n=== TESTE PARA {tipo} {numero} ===")
        
        print("\n1. Testando conexão...")
        if not self.testar_conexao():
            print("❌ Falha na conexão")
            return False
        print("✅ Conexão OK")
        
        print("\n2. Verificando vigência...")
        resultado = self.verificar_vigencia_norma(tipo, numero)
        print(f"Resultado: {'VIGENTE' if resultado else 'REVOGADA/NÃO ENCONTRADA'}")
        
        return resultado