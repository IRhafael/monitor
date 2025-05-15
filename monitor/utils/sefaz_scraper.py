from selenium.webdriver.common.keys import Keys
import re
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
import urllib.parse
from datetime import datetime
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (TimeoutException, 
                                      NoSuchElementException, 
                                      WebDriverException)
from selenium.webdriver.chrome.service import Service as ChromeService
from contextlib import contextmanager
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import logging

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 30
        self.driver = None
        
        # Configuração mais robusta do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        
        # Configuração de logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto mais robusto"""
        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=self.chrome_options
            )
            self.driver.set_page_load_timeout(self.timeout)
            yield self.driver
        except Exception as e:
            self.logger.error(f"Erro na sessão do navegador: {str(e)}")
            raise
        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None

    def _start_browser(self):
        """Configura e inicia o navegador"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            self.driver = webdriver.Chrome(
                service=self.chrome_service,
                options=chrome_options
            )
            self.driver.set_page_load_timeout(self.timeout)
            return True
        except Exception as e:
            logger.error(f"Browser start error: {str(e)}")
            return False

    def _close_browser(self):
        """Fecha o navegador corretamente"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error closing browser: {str(e)}")
            finally:
                self.driver = None

    def _find_norm_item(self, norm_type, norm_number):
        """Encontra o elemento HTML correto da norma"""
        all_items = self.driver.find_elements(By.CSS_SELECTOR, ".search-results .result-item")
        
        # Padroniza o número para comparação
        clean_number = re.sub(r'[^\d/]', '', norm_number)
        
        for item in all_items:
            # Verifica no snippet (campo que contém tipo e número)
            snippet = item.find_element(By.CSS_SELECTOR, ".field-snippet").text
            if (norm_type.lower() in snippet.lower() and 
                clean_number in re.sub(r'[^\d/]', '', snippet)):
                return item
        return None
    
    def _extract_norm_data(self, norm_element):
            """Extrai todos os campos da norma conforme a tabela fornecida"""
            fields_map = {
                'situacao': '.field-situacao',
                'data_assinatura': '.field-data_assinatura',
                'data_publicacao': '.field-data_publicacao',
                'link_fonte': '.field-link_fonte a',
                'instituicao': '.field-instituicao',
                'processo': '.field-processo',
                'sei': '.field-sei',
                'apelido': '.field-apelido',
                'ementa': '.field-ementa',
                'alt': '.field-alt'
            }
            
            data = {}
            for field, selector in fields_map.items():
                try:
                    element = norm_element.find_element(By.CSS_SELECTOR, selector)
                    data[field] = element.text.strip()
                    if field == 'link_fonte':  # Pega o href se for link
                        data['link_fonte_url'] = element.get_attribute('href')
                except NoSuchElementException:
                    data[field] = None
            
            return data

    

    def check_norm_status(self, norm_type, norm_number):
        """Verifica se a norma existe e está vigente"""
        try:
            details = self.get_norm_details(norm_type, norm_number)
            return details is not None and details.get('situacao') == 'VIGENTE'
        except Exception as e:
            self.logger.error(f"Erro ao verificar status: {str(e)}")
            return False

    def _check_via_search(self, norm_type, norm_number):
        """Verifica status via pesquisa avançada"""
        try:
            query = f"{norm_type.upper()} {norm_number}"
            self.driver.get(f"{self.search_url}?q={urllib.parse.quote_plus(query)}")
            
            WebDriverWait(self.driver, 15).until(
                lambda d: "resultado" in d.page_source.lower() or "busca" in d.page_source.lower()
            )
            
            if "nenhum resultado" in self.driver.page_source.lower():
                return None
            
            results = self.driver.find_elements(By.CSS_SELECTOR, ".result-item, .search-result")
            if not results:
                return None
                
            norm_number_clean = norm_number.lower().replace(".", "").replace("/", "-")
            
            for result in results:
                if (norm_type.lower() in result.text.lower() and 
                    (norm_number.lower() in result.text.lower() or 
                     norm_number_clean in result.text.lower().replace("/", "-"))):
                    
                    try:
                        result.click()
                    except:
                        try:
                            link = result.find_element(By.TAG_NAME, "a").get_attribute("href")
                            if link:
                                self.driver.get(link)
                            else:
                                return None
                        except:
                            return None
                    
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.document-wrapper.clearfix")))
                    
                    details = self._get_norm_details()
                    status = self._determine_status_from_details(details)
                    return status if status is not None else True
            
            return None
            
        except TimeoutException:
            logger.warning("Timeout waiting for search results")
            return None
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return None

    def _check_via_direct_url(self, norm_type, norm_number):
        """Tenta verificar status via URL direta"""
        try:
            norm_type_url = norm_type.lower()
            norm_number_url = norm_number.replace('/', '-')
            
            urls_to_try = [
                f"{self.base_url}/{norm_type_url}/{norm_number_url}",
                f"{self.base_url}/{norm_type_url.lower()}/{norm_number}",
                f"{self.base_url}/{norm_type_url.lower()}/{norm_number.replace('/', '')}"
            ]
            
            for url in urls_to_try:
                self.driver.get(url)
                time.sleep(2)
                
                if "error" in self.driver.current_url.lower() or "404" in self.driver.current_url:
                    continue
                
                page_source = self.driver.page_source.lower()
                
                if any(term in page_source for term in ["revogado", "revogada", "não vigente"]):
                    return False
                
                if any(term in page_source for term in ["vigente", "em vigor"]):
                    return True
                
                if (norm_type.lower() in page_source and 
                    norm_number.replace('/', '-') in page_source):
                    return True
            
            return None
            
        except Exception as e:
            logger.warning(f"Direct URL check failed: {str(e)}")
            return None

    def get_norm_details(self, norm_type, norm_number):
        """Obtém todos os detalhes da norma"""
        try:
            with self.browser_session():
                # 1. Faz a pesquisa
                search_url = f"{self.base_url}/search-results?q={norm_type}+{norm_number}"
                self.driver.get(search_url)
                
                # 2. Aguarda e obtém todos os resultados
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".search-results"))
                )
                
                results = self.driver.find_elements(By.CSS_SELECTOR, ".result-item")
                
                # 3. Procura a norma específica
                clean_number = self._clean_number(norm_number)
                for result in results:
                    if self._is_matching_norm(result, norm_type, clean_number):
                        return self._extract_norm_data(result)
                
                return None
                
        except Exception as e:
            self.logger.error(f"Erro ao obter detalhes: {str(e)}")
            return None
        
    def _is_matching_norm(self, result_element, norm_type, clean_number):
        """Verifica se o elemento corresponde à norma procurada"""
        try:
            title = result_element.find_element(By.CSS_SELECTOR, ".field-snippet").text
            title_clean = self._clean_number(title)
            return (norm_type.lower() in title.lower() and 
                    clean_number in title_clean)
        except NoSuchElementException:
            return False

    def _determine_status_from_details(self, details):
        """Determina o status com base nos detalhes coletados"""
        status = details.get("situacao", "").lower()
        
        if "vigente" in status or "em vigor" in status:
            return True
        elif "revogado" in status or "cancelado" in status:
            return False
        elif "altera" in details or "legislacao alterada por" in details:
            return True
            
        return None

    def _format_number(self, number):
        """Padroniza o formato do número da norma"""
        number = number.strip()
        
        if '/' in number:
            num_parts = number.split('/')
            if len(num_parts) == 2:
                num, year = num_parts
                if len(year) == 2:
                    year_int = int(year)
                    year = f"20{year}" if year_int < 30 else f"19{year}"
                    number = f"{num}/{year}"
                
        return number

    def test_connection(self):
        """Testa a conexão com o portal"""
        try:
            with self.browser_session():
                self.driver.get(self.base_url)
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                checks = [
                    "sefaz" in self.driver.title.lower(),
                    "portaldalegislacao" in self.driver.current_url.lower(),
                    len(self.driver.page_source) > 1000
                ]
                
                return all(checks)
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False