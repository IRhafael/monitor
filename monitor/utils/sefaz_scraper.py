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
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 30
        self.debug_dir = r"C:\Users\RRCONTAS\Documents\GitHub\monitor\debug"
        self.driver = None
        
        # Configuração do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
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
        """Gerenciador de contexto robusto"""
        self.driver = None
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(
                service=service,
                options=self.chrome_options
            )
            self.driver.set_page_load_timeout(self.timeout)
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

    def _wait_for_element(self, by, value, timeout=30):
        """Espera por um elemento específico"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value)))
        except TimeoutException:
            self.logger.warning(f"Elemento não encontrado: {value}")
            return None

    # Em sefaz_scraper.py, adicione no método _clean_number:
    def _clean_number(self, number):
        # Remove pontos antes de comparar
        cleaned = re.sub(r'[^\d]', '', str(number))
        return cleaned.lower()

    def _padronizar_numero(self, numero):
        """Padroniza para formato ANO/NÚMERO (ex: 2023/22033)"""
        numero = re.sub(r'[^\d/]', '', str(numero))  # Remove não-dígitos exceto /
        
        # Casos como 22.033 → assume ano atual se não tiver /
        if '/' not in numero:
            current_year = datetime.now().year
            numero = f"{current_year}/{numero}"
        
        return numero

    def _pesquisar_norma(self, norm_type, norm_number):
        """Executa a pesquisa no portal SEM o asterisco no final"""
        norm_number = self._padronizar_numero(norm_number)
        termo_busca = f"{norm_type} {norm_number}" 
        try:
            search_input = self._wait_for_element(
                By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
            
            if not search_input:
                self.logger.error("Campo de busca não encontrado")
                return False
            
            # REMOVER O ASTERISCO DA BUSCA
            termo_busca = f"{norm_type} {norm_number}"  # Sem o * no final
            search_input.clear()
            search_input.send_keys(termo_busca)
            self._save_debug_info("02_campo_preenchido")
            
            # Clica no botão de busca
            search_button = self.driver.find_element(By.CSS_SELECTOR, "img[alt='search']")
            search_button.click()
            
            # Aguarda o carregamento
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(By.TAG_NAME, "iframe").is_displayed())
            
            self._save_debug_info("03_pos_busca")
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao pesquisar: {str(e)}")
            self._save_debug_info("99_erro_pesquisa")
            return False
    def _extrair_situacao(self, doc_body):
        """Extrai situação com fallback"""
        situacao = self._extract_field(doc_body, "field-situacao")
        if not situacao:
            # Fallback para outros padrões
            situacao = self._extract_field(doc_body, "field-status") or "NÃO ENCONTRADA"
        return situacao.lower()

    def get_norm_details(self, norm_type, norm_number):
        """Busca detalhes da norma com a pesquisa corrigida"""
        try:
            with self.browser_session():
                self.driver.get(self.base_url)
                self._save_debug_info("01_pagina_inicial")
                
                # Usa a versão corrigida sem asterisco
                if not self._pesquisar_norma(norm_type, norm_number):
                    return None
                
                # 3. Aguarda e muda para o iframe de resultados
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
                    
                    # 4. Aguarda o corpo do documento carregar
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.document-body")))
                    
                    # 5. Extrai as informações da norma
                    doc_body = self.driver.find_element(By.CSS_SELECTOR, "div.document-body")
                    
                    # Extrai o texto principal
                    snippet = doc_body.find_element(By.CSS_SELECTOR, "div.field-snippet span.value").text
                    
                    # Extrai os campos individuais
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
                    
                    # Constrói o resultado
                    result = {
                        'norma': f"{norm_type} {norm_number}",
                        'texto_completo': snippet,
                        **fields
                    }
                    
                    self._save_debug_info("04_norma_encontrada")
                    return result
                    
                except TimeoutException:
                    self.logger.warning("Tempo excedido ao carregar resultados")
                    return None
                except NoSuchElementException as e:
                    self.logger.warning(f"Elemento não encontrado: {str(e)}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Erro geral: {str(e)}")
            self._save_debug_info("99_erro_geral")
            return None
        finally:
            if self.driver:
                try:
                    self.driver.switch_to.default_content()
                except:
                    pass

    def _has_search_results(self):
        """Verifica se a busca retornou resultados"""
        try:
            # Verifica mensagem de "nenhum resultado"
            no_results = self.driver.find_elements(By.XPATH, 
                "//*[contains(text(), 'Nenhum resultado') or contains(text(), 'No results')]")
            return not bool(no_results)
        except:
            return True
        
    def _extract_field(self, parent, field_class):
        """Extrai o valor de um campo específico"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            # Remove o rótulo do campo (texto em strong)
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
        """Extrai múltiplos links de um campo (como 'Altera')"""
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

    def _switch_to_results_frame(self):
        """Versão aprimorada para localizar iframe de resultados"""
        try:
            # Tenta encontrar o iframe principal
            iframe = self._wait_for_element(By.CSS_SELECTOR, "iframe")
            
            if iframe:
                self.driver.switch_to.frame(iframe)
                return True
                
            # Fallback para outros iframes
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    if self._wait_for_element(By.CSS_SELECTOR, ".resultado-busca", timeout=3):
                        return True
                    self.driver.switch_to.default_content()
                except:
                    self.driver.switch_to.default_content()
                    continue
                
            return False
            
        except Exception as e:
            self.logger.error(f"Erro ao mudar para iframe: {str(e)}")
            return False

    def _is_matching_norm(self, text, norm_type, clean_number):
        """Verificação robusta com regex"""
        try:
            # Padroniza os termos para busca
            norm_type = norm_type.lower()
            norm_number_clean = re.sub(r'[^\d/]', '', clean_number).lower()
            
            # Verifica múltiplos padrões possíveis
            patterns = [
                rf"{norm_type}\s*{norm_number_clean}",
                rf"{norm_type}\s*n[º°]?\s*{norm_number_clean}",
                rf"{norm_number_clean}.*?{norm_type}"
            ]
            
            content = text.lower()
            return any(re.search(p, content) for p in patterns)
            
        except Exception as e:
            self.logger.error(f"Erro na verificação: {str(e)}")
            return False

    def check_norm_status(self, norm_type, norm_number):
        norm_type = norm_type.upper().strip()
        norm_number_clean = self._padronizar_numero(norm_number)

        details = self.get_norm_details(norm_type, norm_number)
        if not details:
            return False
        
    
        # Adicione esta verificação
        situacao = details.get('situacao')
        if not situacao:  # Caso o campo situacao seja None
            return False
            
        situacao = situacao.lower()

        norm_type = norm_type.upper().strip()
        norm_number = self._clean_number(norm_number)
        
        details = self.get_norm_details(norm_type, norm_number)
        if not details:
            return False
            
        situacao = details.get('situacao', '').lower()
        
        # Lógica mais robusta para determinar status
        if any(s in situacao for s in ['vigente', 'ativo', 'valido']):
            return True
        elif any(s in situacao for s in ['revogado', 'cancelado', 'expirado']):
            return False
        return bool(details.get('data_publicacao'))

    def test_connection(self):
        """Testa conexão com o portal"""
        try:
            # Teste HTTP simples
            try:
                response = requests.get(self.base_url, timeout=10)
                if response.status_code != 200:
                    return False
            except requests.RequestException:
                return False
            
            # Teste com navegador
            with self.browser_session():
                self.driver.get(self.base_url)
                return "sefaz" in self.driver.title.lower()
        except Exception:
            return False
        
    # Adicione este método à classe SEFAZScraper
    def verificar_vigencia_norma(self, norm_type, norm_number):
        """Método alternativo para verificação de vigência"""
        return self.check_norm_status(norm_type, norm_number)