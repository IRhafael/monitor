from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
import time

logger = logging.getLogger(__name__)

class BingScraper:
    def __init__(self, driver):
        self.driver = driver
        self.base_url = "https://www.bing.com"
        self.copilot_url = "https://www.bing.com/search?q=Bing+AI&showconv=1"

    def pesquisar_norma(self, norm_type, norm_number, norm_year=None):
        """Pesquisa a norma no Bing e obtém resumo do Copilot"""
        try:
            termo = f"{norm_type} {norm_number}"
            if norm_year:
                termo += f"/{norm_year}"
            
            # Pesquisa normal no Bing
            self.driver.get(self.base_url)
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q")))
            
            search_input.clear()
            search_input.send_keys(termo + " site:.gov.br")
            search_input.send_keys(Keys.RETURN)
            time.sleep(2)
            
            # Tenta obter snippet do Bing
            bing_result = self._get_bing_results()
            
            # Se não encontrou ou quer complementar com Copilot
            copilot_summary = self._get_copilot_summary(termo)
            
            return {
                'fonte': 'Bing',
                'resultados_bing': bing_result,
                'resumo_copilot': copilot_summary,
                'url': self.driver.current_url
            }
            
        except Exception as e:
            logger.error(f"Erro ao pesquisar no Bing: {str(e)}")
            return None

    def _get_bing_results(self):
        """Captura os primeiros resultados do Bing"""
        try:
            resultados = []
            items = WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".b_algo")))
            
            for item in items[:3]:  # Pega os 3 primeiros
                titulo = item.find_element(By.CSS_SELECTOR, "h2").text
                snippet = item.find_element(By.CSS_SELECTOR, ".b_caption p").text
                resultados.append({'titulo': titulo, 'snippet': snippet})
            
            return resultados
            
        except Exception:
            return None

    def _get_copilot_summary(self, termo):
        """Obtém resumo da IA do Bing (Copilot)"""
        try:
            self.driver.get(self.copilot_url)
            time.sleep(3)  # Espera o chat carregar
            
            # Envia a pergunta
            chat_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "textarea#searchbox")))
            chat_input.clear()
            chat_input.send_keys(f"Resuma a norma {termo} com foco no status de vigência")
            chat_input.send_keys(Keys.RETURN)
            time.sleep(5)  # Espera a resposta
            
            # Captura a resposta
            resposta = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='message']:last-child")))
            return resposta.text
            
        except Exception as e:
            logger.warning(f"Não foi possível obter resposta do Copilot: {str(e)}")
            return None