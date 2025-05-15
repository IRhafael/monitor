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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (TimeoutException, 
                                      NoSuchElementException, 
                                      WebDriverException)
from selenium.webdriver.chrome.service import Service as ChromeService
from contextlib import contextmanager
import os
from bs4 import BeautifulSoup
import base64

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
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
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
        """Método principal simplificado e eficiente"""
        tipo = tipo.upper().strip()
        numero = self._formatar_numero(numero)
        
        logger.info(f"Verificando vigência de {tipo} {numero}")
        
        try:
            with self.browser_session():
                # Primeiro tenta via pesquisa avançada
                logger.info("Tentando busca via pesquisa avançada...")
                resultado = self._verificar_via_pesquisa_avancada(tipo, numero)
                if resultado is not None:
                    logger.info(f"Resultado via pesquisa: {'VIGENTE' if resultado else 'REVOGADA/NÃO ENCONTRADA'}")
                    return resultado
                
                # Se não encontrou nada, tenta via URL direta
                logger.info("Tentando busca via URL direta...")
                resultado_url = self._verificar_via_url_direta(tipo, numero)
                if resultado_url is not None:
                    logger.info(f"Resultado via URL direta: {'VIGENTE' if resultado_url else 'REVOGADA/NÃO ENCONTRADA'}")
                    return resultado_url
                
                # Se não encontrou por nenhum método, assume que não existe/não está vigente
                logger.info("Norma não encontrada por nenhum método")
                return False
                
        except Exception as e:
            logger.error(f"Erro na verificação: {str(e)}")
            return False

    def coletar_normas_recentes(self, max_normas=10):
        """Coleta as normas mais recentes do portal"""
        try:
            with self.browser_session():
                self.driver.get(self.base_url)
                
                # Aguarda carregamento da página inicial
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Busca por elementos recentes na página inicial
                normas = []
                selectors = [
                    ".item-recente", 
                    ".norma-recente", 
                    ".documento-recente",
                    ".ultimas-normas li"
                ]
                
                for selector in selectors:
                    try:
                        elementos = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elementos:
                            for item in elementos[:max_normas]:
                                try:
                                    normas.append(self._extrair_dados_norma(item.text))
                                except Exception as e:
                                    logger.warning(f"Erro ao processar item: {str(e)}")
                            break
                    except Exception:
                        continue
                
                # Se não encontrou normas recentes, tenta via pesquisa
                if not normas:
                    logger.info("Tentando encontrar normas via pesquisa")
                    self.driver.get(self.search_url)
                    
                    # Executa pesquisa genérica
                    try:
                        search_input = WebDriverWait(self.driver, self.timeout).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search'], input[type='text']"))
                        )
                        search_input.send_keys("norma")
                        search_input.send_keys(Keys.RETURN)
                        
                        # Aguarda resultados
                        time.sleep(3)
                        
                        # Processa resultados
                        resultados = self._extrair_resultados()[:max_normas]
                        
                        for item in resultados:
                            try:
                                normas.append(self._extrair_dados_norma(item.text))
                            except Exception as e:
                                logger.warning(f"Erro ao processar item: {str(e)}")
                    except Exception as e:
                        logger.error(f"Erro na pesquisa de normas: {str(e)}")
                        
                return normas
                
        except Exception as e:
            logger.error(f"Erro na coleta de normas: {str(e)}")
            return []

    # ================== SUPPORT METHODS ==================
    def _formatar_numero(self, numero):
        """Padroniza o formato do número da norma"""
        # Remove espaços
        numero = numero.strip()
        
        # Verifica se tem ano com 2 ou 4 dígitos
        if '/' in numero:
            num_parts = numero.split('/')
            if len(num_parts) == 2:
                num, ano = num_parts
                # Se ano tem 2 dígitos, converte para 4 dígitos
                if len(ano) == 2:
                    # Assume que é 2000+ se o ano é menor que 30
                    # caso contrário assume que é 1900+
                    ano_int = int(ano)
                    if ano_int < 30:
                        ano = f"20{ano}"
                    else:
                        ano = f"19{ano}"
                    numero = f"{num}/{ano}"
                
        return numero
    
    def _verificar_via_url_direta(self, tipo, numero):
        """Tentativa de verificação via URL direta"""
        try:
            # Formata a URL conforme esperado pelo site
            tipo_url = tipo.lower()
            numero_url = numero.replace('/', '-')
            
            urls_para_tentar = [
                f"{self.base_url}/{tipo_url}/{numero_url}",
                f"{self.base_url}/{tipo_url.lower()}/{numero}",
                f"{self.base_url}/{tipo_url.lower()}/{numero.replace('/', '')}"
            ]
            
            for url in urls_para_tentar:
                logger.info(f"Tentando URL: {url}")
                self.driver.get(url)
                time.sleep(2)
                
                # Captura evidência
                self._capturar_evidencias(f"url_{tipo}_{numero}")
                
                # Verifica se a URL redirecionou para página de erro
                if "error" in self.driver.current_url.lower() or "404" in self.driver.current_url:
                    logger.info("URL resultou em erro 404")
                    continue
                
                # Verifica o conteúdo da página
                page_source = self.driver.page_source.lower()
                
                # Busca por indicações de revogação
                if any(termo in page_source for termo in ["revogado", "revogada", "não vigente"]):
                    logger.info("Norma encontrada mas está revogada")
                    return False
                
                # Busca por indicações de vigência
                if any(termo in page_source for termo in ["vigente", "em vigor"]):
                    logger.info("Norma encontrada e está vigente")
                    return True
                
                # Se encontrou a página da norma mas sem status claro
                if tipo.lower() in page_source and numero.replace('/', '-') in page_source:
                    logger.info("Norma encontrada sem status explícito - assumindo vigente")
                    return True
            
            # Se chegou aqui, não encontrou por nenhuma URL
            return None
            
        except Exception as e:
            logger.warning(f"Falha na verificação por URL: {str(e)}")
            return None

    def _verificar_via_pesquisa_avancada(self, tipo, numero):
        """Versão reformulada que abre o detalhe da norma e coleta dados completos"""
        try:
            # Formata a consulta mantendo a formatação original
            query = f"{tipo.upper()} {numero}"
            url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
            self.driver.get(url)
            
            # Aguarda o carregamento dos resultados
            WebDriverWait(self.driver, 15).until(
                lambda d: "resultado" in d.page_source.lower() or "busca" in d.page_source.lower()
            )
            
            # Captura evidência para análise
            self._capturar_evidencias(f"pesquisa_{tipo}_{numero}")
            
            # Verifica se há mensagem de "nenhum resultado"
            if "nenhum resultado" in self.driver.page_source.lower():
                return None
            
            # Analisa os resultados encontrados
            resultados = self.driver.find_elements(By.CSS_SELECTOR, ".result-item, .search-result, .resultado")
            
            if not resultados:
                return None
                
            # Normaliza os números para comparação
            numero_busca = numero.lower().replace(".", "").replace("/", "-")
            
            for resultado in resultados:
                texto = resultado.text.lower()
                
                # Verifica se é a norma que estamos buscando
                if (tipo.lower() in texto and 
                    (numero.lower() in texto or numero_busca in texto.replace("/", "-"))):
                    
                    # Tenta abrir o detalhe da norma clicando no resultado
                    try:
                        resultado.click()
                    except Exception:
                        # Se não conseguir clicar, tenta pegar link e navegar direto
                        try:
                            link = resultado.find_element(By.TAG_NAME, "a").get_attribute("href")
                            if link:
                                self.driver.get(link)
                            else:
                                # Se não conseguir abrir a página de detalhe, volta o resultado parcial
                                return None
                        except Exception:
                            return None
                    
                    # Aguarda o carregamento do detalhe da norma
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.document-wrapper.clearfix"))
                    )
                    
                    # Coleta os detalhes da norma
                    detalhes = self._coletar_detalhes_norma()
                    
                    # Analisa o campo 'situacao' ou 'situação' para verificar status
                    situacao = detalhes.get("situacao") or detalhes.get("situacao") or detalhes.get("field-situacao") or detalhes.get("situacao") or detalhes.get("field-situacao")
                    situacao = situacao.lower() if situacao else ""
                    
                    if "vigente" in situacao or "em vigor" in situacao:
                        return True
                    elif "revogado" in situacao or "cancelado" in situacao:
                        return False
                    
                    # Caso não tenha situação explícita, verifica campos alternativos, por exemplo:
                    # 'altera' ou 'legislacao alterada por'
                    if "altera" in detalhes or "legislacao alterada por" in detalhes:
                        # Pode implementar lógica extra se quiser
                        return True
                    
                    # Se ainda não sabe, assume vigente
                    return True
            
            return None
            
        except TimeoutException:
            logger.warning("Timeout ao aguardar resultados da pesquisa")
            return None
        except Exception as e:
            logger.error(f"Erro na pesquisa avançada: {str(e)}")
            return None



    def _coletar_detalhes_norma(self):
        """
        Coleta os dados da norma no layout detalhado dentro do 'div.document-wrapper.clearfix'.
        Extrai todas as divs com classe 'field field-xxxx' e retorna um dicionário
        com as chaves sendo o sufixo da classe 'field-xxxx' e os valores o texto contido.
        """
        detalhes = {}
        try:
            wrapper = self.driver.find_element(By.CSS_SELECTOR, "div.document-wrapper.clearfix")
            campos = wrapper.find_elements(By.CSS_SELECTOR, "div.field")
            for campo in campos:
                classes = campo.get_attribute("class").split()
                # Procura a classe que começa com "field-" para usar como chave
                chave = next((c.replace("field-", "") for c in classes if c.startswith("field-")), None)
                if chave:
                    valor = campo.text.strip()
                    detalhes[chave] = valor
            return detalhes
        except Exception as e:
            logger.debug(f"Erro ao coletar detalhes norma: {e}")
            return {}


    def _extrair_resultados(self):
        """Tenta múltiplos seletores para encontrar resultados"""
        resultados = []
        
        # Lista de seletores para encontrar resultados (ordem de prioridade)
        selectors = [
            ("CSS", ".result-item"),
            ("CSS", ".search-result"),
            ("CSS", ".resultado-busca li"),
            ("CSS", "ul.lista-resultados > li"),
            ("CSS", ".resultado"),
            ("XPATH", "//div[contains(@class,'resultado')]"),
            ("XPATH", "//li[contains(@class,'resultado')]"),
            ("XPATH", "//*[contains(text(),'Norma') or contains(text(),'Documento')]/ancestor::div[1]")
        ]
        
        for selector_type, selector in selectors:
            try:
                if selector_type == "CSS":
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                else:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    
                if elements:
                    logger.info(f"Encontrados {len(elements)} resultados com seletor {selector}")
                    return elements
            except Exception as e:
                logger.debug(f"Erro com seletor {selector}: {str(e)}")
                continue
                
        # Última tentativa: busca por texto genérico na página
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Procura divs que possam conter resultados
            for div in soup.find_all('div'):
                texto = div.get_text().lower()
                # Se a div tem texto relacionado a normas
                if (len(texto) > 50 and 
                    any(termo in texto for termo in ["norma", "decreto", "lei", "portaria"])):
                    # Tenta encontrar o elemento no Selenium
                    try:
                        xpath = f"//div[contains(text(),'{div.get_text()[:30]}')]"
                        elemento = self.driver.find_element(By.XPATH, xpath)
                        resultados.append(elemento)
                    except:
                        continue
        except Exception as e:
            logger.debug(f"Erro na busca por BeautifulSoup: {str(e)}")
            
        return resultados

    def _capturar_evidencias(self, prefixo="debug"):
        """Versão robusta para salvar arquivos de debug"""
        if not self.driver:
            logger.error("Tentativa de capturar evidências com driver fechado")
            return None, None
            
        try:
            # Remove caracteres inválidos do nome do arquivo
            safe_prefix = re.sub(r'[\\/*?:"<>|]', "_", prefixo)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Cria diretório se não existir
            os.makedirs("debug", exist_ok=True)
            
            screenshot_path = f"debug/{safe_prefix}_{timestamp}.png"
            html_path = f"debug/{safe_prefix}_{timestamp}.html"
            
            self.driver.save_screenshot(screenshot_path)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            
            logger.info(f"Evidências salvas: {screenshot_path} e {html_path}")
            return screenshot_path, html_path
        except Exception as e:
            logger.error(f"Falha ao capturar evidências: {str(e)}")
            return None, None

    def _extrair_dados_norma(self, texto_item):
        """Extrai dados estruturados de um item de norma"""
        padrao_tipo = r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA)\s'
        padrao_numero = r'(?:N[º°]?\s*)?(\d+[\/-]\d+)'
        padrao_data = r'(\d{1,2}\/\d{1,2}\/\d{4})'
        
        tipo = re.search(padrao_tipo, texto_item.upper())
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
                
                # Verificação robusta e case-insensitive
                current_url = self.driver.current_url.lower()
                page_source = self.driver.page_source.lower()
                
                checks = [
                    "sefaz" in self.driver.title.lower() or "legislação" in self.driver.title.lower(),
                    "portaldalegislacao" in current_url,
                    any(termo in page_source for termo in ["sefaz", "fazenda", "legislação"]),
                    len(page_source) > 1000
                ]
                
                logger.info(f"URL atual: {current_url}")
                logger.info(f"Checks: {checks}")
                
                return all(checks)
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

    def testar_conexao_manual(self):
        """Versão corrigida do teste de conexão que NÃO fecha o navegador"""
        try:
            if self.driver is None:
                self._iniciar_navegador()
                
            self.driver.get(self.base_url)
            
            # Aguarda carregamento da página
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Verificação robusta e case-insensitive
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()
            
            checks = [
                "sefaz" in self.driver.title.lower() or "legislação" in self.driver.title.lower(),
                "portaldalegislacao" in current_url,
                any(termo in page_source for termo in ["sefaz", "fazenda", "legislação"]),
                len(page_source) > 1000
            ]
            
            # Salva evidência
            self.driver.save_screenshot('debug/conexao_manual.png')
            with open('debug/conexao_page.html', 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
                
            logger.info(f"URL atual: {current_url}")
            logger.info(f"Checks: {checks}")
            
            return all(checks)
            
        except Exception as e:
            logger.error(f"Erro no teste: {str(e)}")
            return False