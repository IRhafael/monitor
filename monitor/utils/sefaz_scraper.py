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

    def _clean_number(self, number):
        """Padroniza números para comparação"""
        return re.sub(r'[^\d/]', '', number).lower()

    def _pesquisar_norma(self, norm_type, norm_number):
        """Executa a pesquisa no portal"""
        try:
            # Localiza o campo de busca pelo atributo formcontrolname
            search_input = self._wait_for_element(
                By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
            
            if not search_input:
                self.logger.error("Campo de busca não encontrado")
                return False
            
            # Preenche o campo de busca
            termo_busca = f"{norm_type} {norm_number}"
            search_input.clear()
            search_input.send_keys(termo_busca)
            self._save_debug_info("02_campo_preenchido")
            
            # Submete a pesquisa
            search_input.send_keys(Keys.RETURN)
            time.sleep(3)  # Espera o carregamento
            self._save_debug_info("03_pos_busca")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Erro ao pesquisar: {str(e)}")
            self._save_debug_info("99_erro_pesquisa")
            return False

    def get_norm_details(self, norm_type, norm_number):
        """Busca aprimorada com execução real da pesquisa"""
        try:
            with self.browser_session():
                # 1. Acessa a página principal
                self.driver.get(self.base_url)
                self._save_debug_info("01_pagina_inicial")
                
                # 2. Executa a pesquisa
                if not self._pesquisar_norma(norm_type, norm_number):
                    return None
                
                # 3. Verifica se há iframe de resultados
                if not self._switch_to_results_frame():
                    self.logger.warning("Nenhum iframe de resultados encontrado")
                    return None
                
                # 4. Processa os resultados
                results = self._wait_for_element(
                    By.CSS_SELECTOR, ".resultado-busca, .result-item, .search-result")
                
                if not results:
                    self.logger.warning("Nenhum resultado encontrado")
                    return None
                
                # 5. Obtém o HTML dos resultados
                frame_html = self.driver.page_source
                soup = BeautifulSoup(frame_html, 'html.parser')
                
                # 6. Procura a norma específica
                clean_number = self._clean_number(norm_number)
                results = soup.select(".resultado-busca, .result-item, .search-result")
                
                for result in results:
                    if self._is_matching_norm(result.get_text(), norm_type, clean_number):
                        self._save_debug_info("04_norma_encontrada")
                        return {
                            'texto': result.get_text(separator=' ', strip=True),
                            'elementos': len(results)
                        }
                
                self.logger.warning("Norma não encontrada nos resultados")
                return None
                
        except Exception as e:
            self.logger.error(f"Erro geral: {str(e)}")
            self._save_debug_info("99_erro_geral")
            return None
        finally:
            if self.driver:
                self.driver.switch_to.default_content()

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
        """Verifica status da norma"""
        details = self.get_norm_details(norm_type, norm_number)
        if not details:
            return False
        
        situacao = details.get('situacao', '').lower()
        if 'vigente' in situacao:
            return True
        elif 'revogado' in situacao or 'cancelado' in situacao:
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