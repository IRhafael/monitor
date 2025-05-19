import os
from selenium.webdriver.common.keys import Keys
import re
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import requests
from bs4 import BeautifulSoup
from contextlib import contextmanager
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 180  # Timeout aumentado para 180 segundos
        self.max_retries = 3
        self.debug_dir = r"C:\Users\RRCONTAS\Documents\GitHub\monitor\debug"
        self.driver = None
        
        # Configuração otimizada do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--disable-infobars")
        self.chrome_options.add_argument("--disable-notifications")
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Timeouts adicionais
        self.page_load_timeout = 180
        self.script_timeout = 180
        
        # Cria diretório de debug
        os.makedirs(self.debug_dir, exist_ok=True)
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _save_debug_info(self, prefix):
        """Salva prints e HTML para debug"""
        try:
            if self.driver:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = os.path.join(self.debug_dir, f"{prefix}_{timestamp}.png")
                self.driver.save_screenshot(screenshot_path)
                self.logger.info(f"Screenshot salvo em: {screenshot_path}")
                
                html_path = os.path.join(self.debug_dir, f"{prefix}_{timestamp}.html")
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(self.driver.page_source)
        except Exception as e:
            self.logger.error(f"Erro ao salvar debug: {str(e)}")

    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto robusto com tratamento de timeout"""
        self.driver = None
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(
                service=service,
                options=self.chrome_options
            )
            # Configura timeouts
            self.driver.set_page_load_timeout(self.page_load_timeout)
            self.driver.set_script_timeout(self.script_timeout)
            yield self.driver
        except Exception as e:
            self.logger.error(f"Erro na sessão do navegador: {str(e)}")
            raise
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as e:
                    self.logger.warning(f"Erro ao fechar navegador: {str(e)}")
                self.driver = None

    def _wait_for_element(self, by, value, timeout=60):
        """Espera por um elemento específico com timeout aumentado"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value)))
        except TimeoutException:
            self.logger.warning(f"Elemento não encontrado: {value}")
            self._save_debug_info(f"timeout_element_{value}")
            return None

    def _clean_number(self, number):
        """Limpa e padroniza números de normas"""
        cleaned = re.sub(r'[^\d]', '', str(number))
        return cleaned.lower()

    def _padronizar_numero(self, numero):
        """Padroniza formatos diferentes de números de normas"""
        if '/' in numero:
            parts = numero.split('/')
            return f"19{parts[1].zfill(2)}/{parts[0]}" if len(parts[1]) == 2 else f"{parts[1]}/{parts[0]}"
        return re.sub(r'[^\d]', '', numero)

    def _pesquisar_norma(self, norm_type, norm_number):
        """Executa a pesquisa no portal com tratamento robusto"""
        norm_number = self._padronizar_numero(norm_number)
        termo_busca = f"{norm_type} {norm_number}"
        
        for attempt in range(self.max_retries):
            try:
                search_input = self._wait_for_element(
                    By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
                
                if not search_input:
                    self.logger.error("Campo de busca não encontrado")
                    continue
                
                search_input.clear()
                search_input.send_keys(termo_busca)
                self._save_debug_info(f"02_campo_preenchido_attempt{attempt}")
                
                search_button = self.driver.find_element(By.CSS_SELECTOR, "img[alt='search']")
                search_button.click()
                
                # Aguarda o carregamento com timeout maior
                WebDriverWait(self.driver, 30).until(
                    lambda d: d.find_element(By.TAG_NAME, "iframe").is_displayed())
                
                self._save_debug_info(f"03_pos_busca_attempt{attempt}")
                return True
                
            except Exception as e:
                self.logger.error(f"Tentativa {attempt+1}/{self.max_retries}: Erro ao pesquisar: {str(e)}")
                self._save_debug_info(f"99_erro_pesquisa_attempt{attempt}")
                if attempt == self.max_retries - 1:
                    return False
                time.sleep(5)  # Espera antes de tentar novamente

    def _switch_to_results_frame(self):
        """Muda para o iframe de resultados com tratamento robusto"""
        for attempt in range(self.max_retries):
            try:
                iframe = WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "iframe")))
                
                self.driver.switch_to.frame(iframe)
                
                WebDriverWait(self.driver, 30).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.document-body")))
                
                return True
            except Exception as e:
                self.logger.error(f"Tentativa {attempt+1}/{self.max_retries}: Falha ao acessar iframe: {str(e)}")
                if attempt == self.max_retries - 1:
                    return False
                self.driver.refresh()
                time.sleep(5)

    def get_norm_details(self, norm_type, norm_number):
        """Busca detalhes da norma com tratamento robusto de erros"""
        for attempt in range(self.max_retries):
            try:
                with self.browser_session():
                    self.driver.get(self.base_url)
                    self._save_debug_info("01_pagina_inicial")
                    
                    if not self._pesquisar_norma(norm_type, norm_number):
                        continue
                    
                    if not self._switch_to_results_frame():
                        continue
                    
                    # Extrai as informações da norma
                    doc_body = self._wait_for_element(By.CSS_SELECTOR, "div.document-body")
                    if not doc_body:
                        continue
                    
                    snippet = doc_body.find_element(By.CSS_SELECTOR, "div.field-snippet span.value").text
                    
                    fields = {
                        'situacao': self._extract_field(doc_body, "field-situacao"),
                        'inicio_vigencia': self._extract_field(doc_body, "field-data_assinatura"),
                        'data_publicacao': self._extract_field(doc_body, "field-data_publicacao"),
                        'link_publicacao': self._extract_link(doc_body, "field-link_fonte"),
                        'instituicao': self._extract_field(doc_body, "field-instituicao"),
                        'processo_sei': self._extract_field(doc_body, "field-processo"),
                        'documento_sei': self._extract_field(doc_body, "field-secao"),
                        'apelido': self._extract_field(doc_body, "field-apelido"),
                        'ementa': self._extract_field(doc_body, "field-ementa"),
                        'altera': self._extract_links(doc_body, "field-alt")
                    }
                    
                    result = {
                        'norma': f"{norm_type} {norm_number}",
                        'texto_completo': snippet,
                        **fields
                    }
                    
                    self._save_debug_info("04_norma_encontrada")
                    return result
                    
            except Exception as e:
                self.logger.error(f"Tentativa {attempt+1}/{self.max_retries}: Erro geral: {str(e)}")
                self._save_debug_info(f"99_erro_geral_attempt{attempt}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(10)

    def check_norm_status(self, norm_type, norm_number):
        """Verifica o status de uma norma com tratamento robusto"""
        for attempt in range(self.max_retries):
            try:
                details = self.get_norm_details(norm_type, norm_number)
                if not details:
                    continue
                    
                if not self._is_exact_match(details['norma'], norm_type, norm_number):
                    return False
                
                situacao = details.get('situacao', '').lower()
                return 'vigente' in situacao
                
            except Exception as e:
                logger.error(f"Tentativa {attempt+1}/{self.max_retries}: Erro ao verificar status: {str(e)}")
                if attempt == self.max_retries - 1:
                    return False
                time.sleep(10)

    def verificar_vigencia_em_lote(self, normas):
        """Verifica vigência para múltiplas normas"""
        resultados = {}
        for norma in normas:
            try:
                # Assume que a norma está no formato "Tipo Número" (ex: "Lei 1234")
                partes = norma.split()
                if len(partes) >= 2:
                    tipo = partes[0]
                    numero = ' '.join(partes[1:])
                    resultados[norma] = self.check_norm_status(tipo, numero)
                else:
                    resultados[norma] = False
            except Exception as e:
                logger.error(f"Erro ao verificar norma {norma}: {str(e)}")
                resultados[norma] = False
        return resultados

    # Métodos auxiliares (mantidos da versão anterior)
    def _extract_field(self, parent, field_class):
        """Extrai o valor de um campo específico"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            for strong in field.find_elements(By.TAG_NAME, "strong"):
                field_text = field.text.replace(strong.text, "").strip()
            return field_text
        except NoSuchElementException:
            return None
        
    def _extract_link(self, parent, field_class):
        """Extrai um link de um campo específico"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            link = field.find_element(By.TAG_NAME, "a")
            return {
                'texto': link.text,
                'url': link.get_attribute("href")
            }
        except NoSuchElementException:
            return None

    def _extract_links(self, parent, field_class):
        """Extrai múltiplos links de um campo"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            links = []
            for link in field.find_elements(By.TAG_NAME, "a"):
                links.append({
                    'texto': link.text,
                    'url': link.get_attribute("href")
                })
            return links
        except NoSuchElementException:
            return None

    def _is_exact_match(self, found_text, search_type, search_number):
        """Verifica se o texto encontrado corresponde exatamente à norma buscada"""
        patterns = [
            rf"{search_type}\s+{search_number}",
            rf"{search_type}\s+N[°º]?\s+{search_number}"
        ]
        return any(re.search(p, found_text, re.IGNORECASE) for p in patterns)

    def test_connection(self):
        """Testa conexão com o portal"""
        try:
            response = requests.get(self.base_url, timeout=10)
            if response.status_code != 200:
                return False
            
            with self.browser_session():
                self.driver.get(self.base_url)
                return "sefaz" in self.driver.title.lower()
        except Exception:
            return False