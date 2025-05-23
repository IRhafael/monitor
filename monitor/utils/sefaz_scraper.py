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
        self.bing_scraper = None

        
        # Termos com 100% de prioridade
        self.priority_terms = [
            "ICMS",
            "DECRETO 21.866",
            "UNATRI",
            "UNIFIS",
            "LEI 4.257",
            "ATO NORMATIVO: 25/21",
            "ATO NORMATIVO: 26/21",
            "ATO NORMATIVO: 27/21",
            "SECRETARIA DE FAZENDA DO ESTADO DO PIAUÍ (SEFAZ-PI)",
            "SEFAZ",
            "SUBSTITUIÇÃO TRIBUTÁRIA"
        ]
        
        # Configuração do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--disable-web-security")
        self.chrome_options.add_argument("--allow-running-insecure-content")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.114 Safari/537.36")
        
        # Cria diretório de debug
        os.makedirs(self.debug_dir, exist_ok=True)
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _setup_chromedriver(self):
        """Configura o ChromeDriver com tratamento de erros e versão atualizada"""
        try:
            self.logger.info("Configurando ChromeDriver...")
            
            # Usa o ChromeDriverManager sem tentar remover o cache manualmente
            service = Service(ChromeDriverManager().install())
            self.logger.info(f"ChromeDriver configurado: {service.path}")
            return service
            
        except Exception as e:
            self.logger.error(f"Erro ao configurar ChromeDriver: {e}")
            raise

    def get_priority_terms(self):
        """Retorna a lista de termos prioritários"""
        return self.priority_terms

    def _save_debug_info(self, prefix):
        pass

    @contextmanager
    def browser_session(self):
        """Gerenciador de contexto robusto com tratamento de erros do ChromeDriver"""
        self.driver = None
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                service = self._setup_chromedriver()
                self.driver = webdriver.Chrome(
                    service=service,
                    options=self.chrome_options
                )
                
                self.driver.set_page_load_timeout(self.timeout)
                self.logger.info("Sessão do navegador iniciada com sucesso")
                yield self.driver
                break
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Tentativa {retry_count}/{max_retries} falhou: {str(e)}")
                
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                
                if retry_count >= max_retries:
                    self.logger.error("Todas as tentativas de iniciar o navegador falharam")
                    raise Exception(f"Falha ao iniciar o navegador após {max_retries} tentativas: {str(e)}")
                
                time.sleep(2)
                
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("Navegador fechado com sucesso")
            except Exception as e:
                self.logger.warning(f"Erro ao fechar navegador: {str(e)}")
            finally:
                self.driver = None

    def _wait_for_element(self, by, value, timeout=30):
        """Espera por um elemento específico"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value)))
        except TimeoutException:
            self.logger.warning(f"Elemento não encontrado: {value}")
            return None

    def _clean_number(self, number):
        """Padroniza números para comparação"""
        return re.sub(r'[^\d/]', '', number).lower()

    def _pesquisar_norma(self, norm_type, norm_number, norm_year=None):
        """Tenta múltiplas estratégias de pesquisa"""
        estrategias = []
        
        # Estratégia 1: Com ano e aspas exatas
        if norm_year:
            estrategias.append(f'"{norm_type} {norm_number}/{norm_year}"')
        
        # Estratégia 2: Sem ano mas com número completo
        estrategias.append(f"{norm_type} {norm_number}")
        
        # Estratégia 3: Apenas número para buscas mais amplas
        if '/' in norm_number:
            num_base = norm_number.split('/')[0]
            estrategias.append(f"{norm_type} {num_base}*")
        
        for termo in estrategias:
            try:
                search_input = self._wait_for_element(By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
                search_input.clear()
                search_input.send_keys(termo)
                search_button = self.driver.find_element(By.CSS_SELECTOR, "img[alt='search']")
                search_button.click()
                
                # Verifica se encontrou resultados
                if self._verificar_resultados():
                    return True
                    
            except Exception as e:
                continue
        
        return False

    def _verificar_resultados(self):
        """Verifica se a busca retornou resultados válidos"""
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".resultado-item")))
            return True
        except:
            return False

    def get_norm_details(self, norm_type, norm_number, norm_year=None):
        """Busca detalhes da norma incluindo o ano se disponível"""
        try:
            with self.browser_session():
                # 1. Acessa a página principal
                self.driver.get(self.base_url)
                self._save_debug_info("01_pagina_inicial")
                
                # 2. Executa a pesquisa incluindo o ano
                if not self._pesquisar_norma(norm_type, norm_number, norm_year=norm_year):
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
                    
                    # Constrói o resultado incluindo o ano se existir
                    norma_completa = f"{norm_type} {norm_number}" + (f"/{norm_year}" if norm_year else "")
                    result = {
                        'norma': norma_completa,
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

    def check_norm_status(self, norm_type, norm_number, norm_year=None):
        """Versão híbrida que verifica SEFAZ e Bing/Copilot"""
        resultado = {
            'sefaz': None,
            'bing': None,
            'status': 'não encontrado',
            'vigente': False,
            'resumo_ia': None
        }
        
        with self.browser_session():
            # 1. Pesquisa na SEFAZ (prioritário)
            resultado['sefaz'] = self.get_norm_details(norm_type, norm_number, norm_year)
            
            # 2. Se SEFAZ não retornou, tenta Bing
            if not resultado['sefaz'] or not resultado['sefaz'].get('texto_completo'):
                self.bing_scraper = BingScraper(self.driver)
                resultado['bing'] = self.bing_scraper.pesquisar_norma(norm_type, norm_number, norm_year)
                
                if resultado['bing']:
                    resultado['resumo_ia'] = resultado['bing'].get('resumo_copilot')
                    resultado['status'] = self._analisar_resposta_bing(resultado['bing'])
            
            # Determina status final
            if resultado['sefaz']:
                resultado.update(self._determinar_status_sefaz(resultado['sefaz']))
            elif resultado['bing']:
                resultado['vigente'] = self._determinar_status_bing(resultado['bing'])
            
            return resultado

    def _analisar_resposta_bing(self, dados_bing):
        """Analisa a resposta do Bing/Copilot"""
        if not dados_bing:
            return 'não encontrado'
            
        texto_analise = ""
        if dados_bing.get('resumo_copilot'):
            texto_analise = dados_bing['resumo_copilot'].lower()
        elif dados_bing.get('resultados_bing'):
            texto_analise = ' '.join([r['snippet'].lower() for r in dados_bing['resultados_bing']])
        
        if 'revogado' in texto_analise or 'cancelado' in texto_analise:
            return 'revogado (fonte: Bing)'
        elif 'vigente' in texto_analise or 'em vigor' in texto_analise:
            return 'vigente (fonte: Bing)'
        else:
            return 'encontrado mas status indeterminado (fonte: Bing)'
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
        
    def close(self):
        """Fecha o navegador, se estiver aberto"""
        if self.driver:
            self.driver.quit()
            self.driver = None