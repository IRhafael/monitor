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
from bs4 import BeautifulSoup

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

    # ================== CORE METHODS ==================
    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto para sessão do navegador"""
        try:
            if not self._iniciar_navegador():
                raise WebDriverException("Não foi possível iniciar o navegador")
            yield self.driver
        except Exception as e:
            logger.error(f"Erro na sessão do navegador: {str(e)}")
            raise
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

    # ================== MAIN FLOW METHODS ==================
    def verificar_vigencia(self, tipo, numero):
        """Fluxo principal de verificação de vigência"""
        tipo = tipo.upper().strip()
        numero = re.sub(r'[^\d/]', '', str(numero)).strip()
        
        for tentativa in range(1, self.max_retries + 1):
            try:
                with self.browser_session():
                    # 1. Tentativa via URL direta
                    status = self._verificar_via_url_direta(tipo, numero)
                    if status is not None:
                        return status
                    
                    # 2. Tentativa via pesquisa
                    status = self._verificar_via_pesquisa(tipo, numero)
                    if status is not None:
                        return status
                    
                    return False  # Default se nenhum método funcionar
                    
            except Exception as e:
                logger.error(f"Tentativa {tentativa} falhou: {str(e)}")
                if tentativa == self.max_retries:
                    return False
                time.sleep(2 ** tentativa)  # Backoff exponencial

    def coletar_normas_recentes(self, max_normas=10):
        """Coleta as normas mais recentes do portal"""
        try:
            with self.browser_session():
                self.driver.get(self.search_url)
                
                # Executa pesquisa genérica
                search_input = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search']"))
                )
                search_input.send_keys("norma")
                self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
                
                # Processa resultados
                resultados = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".result-item"))
                )[:max_normas]
                
                normas = []
                for item in resultados:
                    try:
                        normas.append(self._extrair_dados_norma(item.text))
                    except Exception as e:
                        logger.warning(f"Erro ao processar item: {str(e)}")
                        continue
                        
                return normas
                
        except Exception as e:
            logger.error(f"Erro na coleta de normas: {str(e)}")
            return []

    # ================== SUPPORT METHODS ==================
    def _verificar_via_url_direta(self, tipo, numero):
        """Tentativa de verificação via URL direta"""
        try:
            url = f"{self.base_url}/{tipo.lower()}/{numero}"
            self.driver.get(url)
            
            if "revogado" in self.driver.page_source.lower():
                return False
            if "vigente" in self.driver.page_source.lower():
                return True
                
            return None
        except Exception as e:
            logger.warning(f"Falha na verificação por URL: {str(e)}")
            return None

    def _verificar_via_pesquisa(self, tipo, numero):
        """Tentativa de verificação via pesquisa"""
        try:
            query = f"{tipo} {numero}"
            url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
            self.driver.get(url)
            
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item"))
            )
            
            # Verifica status no primeiro resultado
            primeiro_resultado = self.driver.find_element(By.CSS_SELECTOR, ".result-item")
            if "revogado" in primeiro_resultado.text.lower():
                return False
            return True
        except TimeoutException:
            logger.warning("Nenhum resultado encontrado na pesquisa")
            return None
        except Exception as e:
            logger.warning(f"Erro na pesquisa: {str(e)}")
            return None

    def _extrair_dados_norma(self, texto_item):
        """Extrai dados estruturados de um item de norma"""
        padrao_tipo = r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA)\s'
        padrao_numero = r'N[º°]\s*([\d\/-]+)'
        padrao_data = r'(\d{2}\/\d{2}\/\d{4})'
        
        tipo = re.search(padrao_tipo, texto_item, re.IGNORECASE)
        numero = re.search(padrao_numero, texto_item)
        data = re.search(padrao_data, texto_item)
        
        return {
            'tipo': tipo.group(1) if tipo else None,
            'numero': numero.group(1) if numero else None,
            'data': datetime.strptime(data.group(1), '%d/%m/%Y').date() if data else None,
            'texto': texto_item[:500] + "..." if len(texto_item) > 500 else texto_item
        }

    # ================== TEST METHODS ==================
    def testar_conexao(self):
        """Testa a conexão com o portal"""
        try:
            with self.browser_session():
                self.driver.get(self.base_url)
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                return "SEFAZ" in self.driver.title
        except Exception as e:
            logger.error(f"Falha no teste de conexão: {str(e)}")
            return False

    def testar_fluxo_completo(self, tipo, numero):
        """Teste completo do fluxo para uma norma específica"""
        print(f"\n=== TESTE PARA {tipo} {numero} ===")
        
        print("\n1. Testando conexão...")
        if not self.testar_conexao():
            print("❌ Falha na conexão")
            return False
        print("✅ Conexão OK")
        
        print("\n2. Verificando vigência...")
        resultado = self.verificar_vigencia(tipo, numero)
        print(f"Resultado: {'VIGENTE' if resultado else 'REVOGADA/NÃO ENCONTRADA'}")
        
        print("\n3. Coletando normas relacionadas...")
        normas = self.coletar_normas_recentes(3)
        print(f"Encontradas {len(normas)} normas recentes")
        
        return resultado
    



    #TESTE MANUAL
    def testar_conexao_manual(self):
        """Teste manual da conexão"""
        try:
            self._iniciar_navegador()
            self.driver.get(self.base_url)
            time.sleep(5)  # Tempo para visualização
            
            # Tirar screenshot para análise
            self.driver.save_screenshot('conexao_manual.png')
            print("Página carregada. Verifique o screenshot 'conexao_manual.png'")
            
            # Verificar elementos
            print(f"Título da página: {self.driver.title}")
            print(f"URL atual: {self.driver.current_url}")
            
            return "SEFAZ" in self.driver.title
        except Exception as e:
            print(f"Erro durante teste manual: {str(e)}")
            return False
        finally:
            self._fechar_navegador() 