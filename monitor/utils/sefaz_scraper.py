from selenium.webdriver.common.keys import Keys
import re
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
import urllib.parse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    WebDriverException,
    SessionNotCreatedException,
    StaleElementReferenceException
)
from selenium.webdriver.chrome.service import Service
from contextlib import contextmanager
from webdriver_manager.chrome import ChromeDriverManager
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 30
        self.driver = None
        
        # Configuração do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto para a sessão do navegador"""
        self.driver = None
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
                try:
                    self.driver.quit()
                except Exception as e:
                    self.logger.warning(f"Erro ao fechar navegador: {str(e)}")
                self.driver = None

    def _wait_for_element(self, by, value, timeout=30):
        """Espera por um elemento específico"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            self.logger.warning(f"Elemento não encontrado: {value}")
            return None

    def _clean_number(self, number):
        """Padroniza números para comparação"""
        return re.sub(r'[^\d/]', '', number).lower()

    def _extract_norm_data(self, norm_element):
        """Extrai dados da norma com tratamento robusto"""
        try:
            data = {
                'resumo': self._get_element_text(norm_element, '.field-snippet'),
                'situacao': self._get_element_text(norm_element, '.field-situacao'),
                'data_assinatura': self._get_element_text(norm_element, '.field-data_assinatura'),
                'data_publicacao': self._get_element_text(norm_element, '.field-data_publicacao'),
                'instituicao': self._get_element_text(norm_element, '.field-instituicao'),
                'processo': self._get_element_text(norm_element, '.field-processo'),
                'sei': self._get_element_text(norm_element, '.field-sei'),
                'apelido': self._get_element_text(norm_element, '.field-apelido'),
                'ementa': self._get_element_text(norm_element, '.field-ementa'),
                'leis_alteradas': self._get_alt_laws(norm_element),
                'link_fonte': self._get_link_text(norm_element),
                'link_fonte_url': self._get_link_href(norm_element)
            }
            return {k: v for k, v in data.items() if v is not None}
        except Exception as e:
            self.logger.error(f"Erro ao extrair dados: {str(e)}")
            return None

    def _get_element_text(self, parent, selector):
        """Obtém texto de elemento com tratamento de erro"""
        try:
            return parent.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return None

    def _get_link_text(self, parent):
        """Obtém texto do link"""
        try:
            return parent.find_element(By.CSS_SELECTOR, '.field-link_fonte a').text.strip()
        except NoSuchElementException:
            return None

    def _get_link_href(self, parent):
        """Obtém URL do link"""
        try:
            return parent.find_element(By.CSS_SELECTOR, '.field-link_fonte a').get_attribute('href')
        except NoSuchElementException:
            return None

    def _get_alt_laws(self, parent):
        """Obtém leis alteradas"""
        try:
            alt_element = parent.find_element(By.CSS_SELECTOR, '.field-alt')
            return [a.text.strip() for a in alt_element.find_elements(By.TAG_NAME, 'a') if a.text.strip()]
        except NoSuchElementException:
            return []

    def _switch_to_results_frame(self):
        """Muda para o iframe que contém os resultados"""
        try:
            # Primeiro tenta encontrar o iframe diretamente
            iframe = self._wait_for_element(By.CSS_SELECTOR, "iframe")
            if iframe:
                self.driver.switch_to.frame(iframe)
                return True
            
            # Se não encontrar, tenta métodos alternativos
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    # Verifica se está no frame correto procurando por elementos de resultado
                    if self._wait_for_element(By.CSS_SELECTOR, ".result-item, .search-result", timeout=5):
                        return True
                    self.driver.switch_to.default_content()
                except Exception:
                    self.driver.switch_to.default_content()
                    continue
            
            return False
        except Exception as e:
            self.logger.error(f"Erro ao mudar para o iframe: {str(e)}")
            return False

    def get_norm_details(self, norm_type, norm_number):
        """Obtém detalhes da norma com tratamento robusto"""
        try:
            with self.browser_session():
                search_url = f"{self.base_url}/search-results?q={urllib.parse.quote(norm_type)}+{urllib.parse.quote(norm_number)}"
                
                try:
                    self.driver.get(search_url)
                    time.sleep(3)  # Espera inicial para carregar a página
                    
                    # Verifica se a página carregou corretamente
                    if "search-results" not in self.driver.current_url:
                        self.logger.error("Redirecionamento inesperado")
                        return None
                    
                    # Tenta mudar para o iframe que contém os resultados
                    if not self._switch_to_results_frame():
                        self.logger.warning("Não foi possível encontrar o iframe de resultados")
                        return None
                    
                    # Aguarda os resultados aparecerem
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
                    )
                    
                    # Obtém o HTML do iframe
                    frame_html = self.driver.page_source
                    soup = BeautifulSoup(frame_html, 'html.parser')
                    
                    # Procura a norma específica
                    clean_number = self._clean_number(norm_number)
                    results = soup.select(".result-item, .search-result, .resultado")
                    
                    for result in results:
                        snippet = result.select_one(".field-snippet, .snippet, .resumo")
                        if snippet and self._is_matching_norm(snippet.get_text(), norm_type, clean_number):
                            return self._extract_norm_data_soup(result)
                    
                    self.logger.warning("Norma não encontrada nos resultados")
                    return None
                    
                except Exception as e:
                    self.logger.error(f"Erro durante a pesquisa: {str(e)}")
                    return None
                finally:
                    # Volta para o conteúdo principal
                    self.driver.switch_to.default_content()
                    
        except Exception as e:
            self.logger.error(f"Erro geral ao obter detalhes: {str(e)}")
            return None

    def _extract_norm_data_soup(self, soup_element):
        """Extrai dados usando BeautifulSoup"""
        try:
            data = {
                'resumo': self._get_text_soup(soup_element, '.field-snippet, .snippet, .resumo'),
                'situacao': self._get_text_soup(soup_element, '.field-situacao, .situacao, .status'),
                'data_assinatura': self._get_text_soup(soup_element, '.field-data_assinatura, .data-assinatura'),
                'data_publicacao': self._get_text_soup(soup_element, '.field-data_publicacao, .data-publicacao'),
                'instituicao': self._get_text_soup(soup_element, '.field-instituicao, .instituicao'),
                'processo': self._get_text_soup(soup_element, '.field-processo, .processo'),
                'sei': self._get_text_soup(soup_element, '.field-sei, .sei'),
                'apelido': self._get_text_soup(soup_element, '.field-apelido, .apelido'),
                'ementa': self._get_text_soup(soup_element, '.field-ementa, .ementa'),
                'leis_alteradas': [a.get_text().strip() for a in soup_element.select('.field-alt a, .leis-alteradas a') if a.get_text().strip()],
                'link_fonte': self._get_text_soup(soup_element, '.field-link_fonte a, .link-fonte'),
                'link_fonte_url': self._get_attr_soup(soup_element, '.field-link_fonte a, .link-fonte', 'href')
            }
            return {k: v for k, v in data.items() if v is not None}
        except Exception as e:
            self.logger.error(f"Erro no BeautifulSoup: {str(e)}")
            return None

    def _get_text_soup(self, parent, selector):
        """Obtém texto com BeautifulSoup"""
        element = parent.select_one(selector)
        return element.get_text().strip() if element else None

    def _get_attr_soup(self, parent, selector, attr):
        """Obtém atributo com BeautifulSoup"""
        element = parent.select_one(selector)
        return element.get(attr) if element else None

    def _is_matching_norm(self, text, norm_type, clean_number):
        """Verifica se o texto corresponde à norma"""
        if not text:
            return False
        text_clean = self._clean_number(text)
        return (norm_type.lower() in text.lower() and 
                clean_number in text_clean)

    def check_norm_status(self, norm_type, norm_number):
        """Verifica o status da norma com tratamento robusto"""
        details = self.get_norm_details(norm_type, norm_number)
        if not details:
            self.logger.warning(f"Norma {norm_type} {norm_number} não encontrada")
            return False
        
        # Extrai e normaliza o status
        situacao = details.get('situacao', '').strip().lower()
        self.logger.info(f"Situação encontrada: '{situacao}'")  # Log para depuração
        
        # Lista de termos que indicam vigência
        termos_vigentes = [
            'vigente', 'em vigor', 'válida', 'valido', 'valida', 
            'em execução', 'ativo', 'ativa', 'não revogada'
        ]
        
        # Lista de termos que indicam não vigência
        termos_revogados = [
            'revogado', 'revogada', 'cancelado', 'cancelada',
            'anulado', 'anulada', 'extinto', 'extinta',
            'suspenso', 'suspensa', 'invalidado', 'invalidada'
        ]
        
        # Verifica primeiro os termos de não vigência
        for termo in termos_revogados:
            if termo in situacao:
                self.logger.info(f"Norma identificada como NÃO VIGENTE pelo termo: '{termo}'")
                return False
        
        # Depois verifica os termos de vigência
        for termo in termos_vigentes:
            if termo in situacao:
                self.logger.info(f"Norma identificada como VIGENTE pelo termo: '{termo}'")
                return True
        
        # Fallback: verifica pela data de publicação
        if details.get('data_publicacao'):
            self.logger.info("Norma considerada VIGENTE por ter data de publicação")
            return True
        
        self.logger.warning("Não foi possível determinar o status da norma")
        return False


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