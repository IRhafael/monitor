# monitor/utils/sefaz_scraper.py

import os
import re
import time
import logging
import traceback
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (TimeoutException, NoSuchElementException,
                                      WebDriverException, StaleElementReferenceException)
from webdriver_manager.chrome import ChromeDriverManager
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 60
        self.max_retries = 3
        self.debug_dir = os.path.join(os.getcwd(), "debug")
        self.driver = None
        
        # Configuração otimizada do ChromeDriver
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        # Adicione estas linhas para configurar o logging
        logging.getLogger('selenium').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('WDM').setLevel(logging.WARNING)
        logger.setLevel(logging.INFO)  # Nível do seu logger principal
        
    @contextmanager
    def browser_session(self):
        """Gerencia a sessão do navegador."""
        if self.driver is None:
            try:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                logger.info("WebDriver Chrome inicializado.")
            except Exception as e:
                logger.error(f"Erro ao inicializar WebDriver: {e}", exc_info=True)
                raise

        try:
            yield self.driver
        except Exception as e:
            logger.error(f"Erro durante a sessão do navegador: {e}", exc_info=True)
            # Captura e loga o stack trace completo
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise

    def _fechar_webdriver(self):
        """Fecha o WebDriver se estiver aberto."""
        if self.driver:
            logger.info("Fechando WebDriver Chrome.")
            self.driver.quit()
            self.driver = None

    def _salvar_pagina_erro(self, prefix="erro", norma=None):
        """Salva o HTML da página atual em caso de erro para depuração."""
        try:
            os.makedirs(self.debug_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            norma_str = f"_{norma.replace('/', '_')}" if norma else ""
            filename = os.path.join(self.debug_dir, f"{prefix}{norma_str}_{timestamp}.html")
            
            # Registra informações sobre o contexto atual
            current_url = "Não disponível"
            try:
                current_url = self.driver.current_url
                logger.debug(f"URL atual: {current_url}")
            except:
                logger.debug("Não foi possível obter a URL atual")
            
            # Salva a página
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"\n")
                f.write(self.driver.page_source)
            logger.error(f"HTML da página de erro salvo em: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Erro ao salvar página de erro: {e}")
            return None

    def _wait_for_iframe_and_switch(self, timeout=30):
        """Aguarda o iframe de resultados ficar disponível e muda o contexto para ele."""
        try:
            # Verifica se já estamos em um iframe
            try:
                self.driver.switch_to.default_content()
                logger.debug("Retornando ao contexto principal antes de procurar iframe")
            except:
                pass
            
            # Primeiro, aguarda que a página esteja completamente carregada
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            logger.debug("Página completamente carregada, procurando iframe")
            
            # Lista todos os iframes disponíveis para debug
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            logger.debug(f"Número de iframes encontrados: {len(iframes)}")
            for i, iframe in enumerate(iframes):
                try:
                    src = iframe.get_attribute("src")
                    logger.debug(f"Iframe {i}: src={src}")
                except:
                    logger.debug(f"Iframe {i}: não foi possível obter src")
            
            # Espera o iframe ficar disponível
            iframe = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe"))
            )
            logger.debug("Iframe encontrado, verificando visibilidade")
            
            # Espera o iframe ficar visível
            WebDriverWait(self.driver, timeout).until(
                EC.visibility_of(iframe)
            )
            logger.debug("Iframe visível, mudando contexto")
            
            # Muda para o contexto do iframe
            self.driver.switch_to.frame(iframe)
            logger.info("Mudou para o contexto do iframe de resultados")
            
            # Verifica se conseguimos acessar elementos dentro do iframe
            try:
                body = self.driver.find_element(By.TAG_NAME, "body")
                logger.debug(f"Conteúdo do iframe: {body.text[:200]}...")
            except Exception as e:
                logger.warning(f"Não foi possível verificar conteúdo do iframe: {e}")
            
            return True
        except TimeoutException:
            logger.error("Timeout ao aguardar iframe de resultados")
            self._salvar_pagina_erro("timeout_iframe")
            return False
        except Exception as e:
            logger.error(f"Erro ao mudar para iframe: {e}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            self._salvar_pagina_erro("erro_iframe")
            return False

    def _preencher_e_enviar_busca(self, tipo_norma, numero_norma):
        """Preenche o campo de busca e envia a consulta na página principal."""
        try:
            logger.info(f"Preenchendo busca para: {tipo_norma} {numero_norma}")

            # Espera até que a página esteja completamente carregada
            WebDriverWait(self.driver, self.timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            logger.debug("Página completamente carregada")

            # Localiza e preenche o campo de busca
            logger.debug("Procurando campo de busca")
            search_input = WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='searchQuery']"))
            )
            logger.debug("Campo de busca encontrado, limpando")
            search_input.clear()
            
            # Registra para debug
            campos_busca = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search']")
            logger.debug(f"Total de campos de busca encontrados: {len(campos_busca)}")
            
            # Digitação simulada mais humana
            search_text = f"{tipo_norma} {numero_norma}"
            logger.debug(f"Digitando texto: '{search_text}'")
            for char in search_text:
                search_input.send_keys(char)
                time.sleep(0.1)
            
            # Tenta enviar a busca
            try:
                # Lista todos os botões visíveis para debug
                buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                logger.debug(f"Botões encontrados: {len(buttons)}")
                for i, btn in enumerate(buttons):
                    try:
                        logger.debug(f"Botão {i} texto: '{btn.text}', classe: '{btn.get_attribute('class')}'")
                    except:
                        logger.debug(f"Não foi possível obter informações do botão {i}")
                
                logger.debug("Procurando botão de busca")
                search_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'], img[alt='search']"))
                )
                logger.debug("Botão de busca encontrado, clicando")
                search_button.click()
                logger.debug("Busca enviada via botão")
            except (TimeoutException, NoSuchElementException) as e:
                logger.debug(f"Botão não encontrado: {e}, tentando ENTER")
                search_input.send_keys(Keys.ENTER)
                logger.debug("Busca enviada via ENTER")

            # Aguarda o carregamento dos resultados (com mais tempo)
            logger.debug("Aguardando carregamento dos resultados")
            time.sleep(5)
            
            # Aguarda o carregamento do iframe de resultados
            if not self._wait_for_iframe_and_switch(timeout=45):
                logger.error("Iframe de resultados não carregado")
                self._salvar_pagina_erro("iframe_nao_carregado", f"{tipo_norma}_{numero_norma}")
                raise TimeoutException("Iframe de resultados não carregado")
            
            return True

        except TimeoutException as e:
            logger.error(f"Timeout ao preencher formulário de busca: {e}")
            self._salvar_pagina_erro("timeout_busca", f"{tipo_norma}_{numero_norma}")
            return False
        except Exception as e:
            logger.error(f"Erro ao preencher busca: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            self._salvar_pagina_erro("erro_busca", f"{tipo_norma}_{numero_norma}")
            return False
        finally:
            # Tentativa de retornar ao contexto principal se necessário
            try:
                self.driver.switch_to.default_content()
            except:
                pass

    def _is_exact_match(self, text, tipo, numero):
        """Verifica se o texto corresponde à norma buscada, com flexibilidade para pontos no número."""
        # Normaliza o texto para comparação
        text = text.strip().lower()
        tipo = tipo.strip().lower()
        numero = numero.strip().lower()
        
        logger.debug(f"Verificando correspondência entre: '{text}' e '{tipo} {numero}'")
        
        # Constrói o padrão de pesquisa para o número, permitindo pontos opcionais entre os dígitos.
        # Ex: "23741/2025" -> "2\.?3\.?7\.?4\.?1/2\.?0\.?2\.?5"
        flexible_numero_pattern = ""
        parts = numero.split('/')
        
        for i, part in enumerate(parts):
            flexible_part = ""
            for j, char in enumerate(part):
                if char.isdigit():
                    flexible_part += char
                    # Adiciona \.? (ponto opcional) se o próximo caractere também for um dígito
                    if j < len(part) - 1 and part[j+1].isdigit():
                        flexible_part += r'\.?'
                else:
                    # Caracteres não-dígitos (como a própria barra '/') são escapados
                    flexible_part += re.escape(char)
            
            flexible_numero_pattern += flexible_part
            if i < len(parts) - 1:
                flexible_numero_pattern += '/' # Adiciona a barra de volta entre as partes

        # Constrói o padrão de pesquisa completo
        norm_pattern = re.compile(
            rf"{re.escape(tipo)}\s*(?:n[º°]?\s*)?{flexible_numero_pattern}", 
            re.IGNORECASE
        )
        
        # Verifica se o padrão corresponde
        match = bool(norm_pattern.search(text))
        logger.debug(f"Resultado da correspondência: {match}")
        return match

    def _extract_status(self, element):
        """Extrai o status da norma do elemento."""
        try:
            logger.debug("Extraindo status do elemento")
            
            # Captura o texto completo do elemento para debug
            element_text = element.text
            logger.debug(f"Texto do elemento: {element_text[:200]}...")
            
            # Verifica classes CSS que indicam status
            if element.find_elements(By.XPATH, ".//*[contains(@class, 'bg-green')]"):
                logger.debug("Status VIGENTE detectado pela classe bg-green")
                return "VIGENTE"
            if element.find_elements(By.XPATH, ".//*[contains(@class, 'bg-red')]"):
                logger.debug("Status REVOGADO detectado pela classe bg-red")
                return "REVOGADO"
            
            # Lista todas as classes do elemento para depuração
            try:
                classes = element.get_attribute("class")
                logger.debug(f"Classes do elemento: {classes}")
            except:
                logger.debug("Não foi possível obter classes do elemento")
            
            # Verifica texto do elemento
            status_text = element_text.lower()
            if "revogado" in status_text:
                logger.debug("Status REVOGADO detectado pelo texto")
                return "REVOGADO"
            elif "alterado" in status_text:
                logger.debug("Status ALTERADO detectado pelo texto")
                return "ALTERADO"
            elif "vigente" in status_text:
                logger.debug("Status VIGENTE detectado pelo texto")
                return "VIGENTE"
            
            # Se não encontrou status específico
            logger.debug("Status não encontrado no elemento")
            return None
        except Exception as e:
            logger.error(f"Erro ao extrair status: {e}")
            return None

    def check_norm_status(self, tipo_norma, numero_norma):
        """Versão específica para HTML aninhado da SEFAZ-PI"""
        with self.browser_session():
            try:
                # 1. Acessar e pesquisar (mantido igual)
                self.driver.get(f"{self.base_url}/site/index.html")
                search_input = WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='searchQuery']"))
                )
                search_input.clear()
                search_input.send_keys(f"{tipo_norma} {numero_norma}")
                search_input.send_keys(Keys.RETURN)
                
                # 2. Lidar com iframe de resultados
                time.sleep(3)
                try:
                    iframe = WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='consultar']"))
                    )
                    self.driver.switch_to.frame(iframe)
                except:
                    self._salvar_pagina_erro("iframe_nao_encontrado")
                    return {"status": "ERRO", "detalhes": "Iframe de resultados não encontrado"}

                # 3. Nova estratégia para HTML aninhado
                try:
                    # Primeiro verifica se há texto visível com a norma
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    
                    if f"{tipo_norma} {numero_norma}" not in body_text:
                        return {"status": "NAO_ENCONTRADO"}
                    
                    # Extrai todos os blocos que podem conter resultados
                    blocos = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Decreto') or contains(text(), 'Lei') or contains(text(), 'Portaria')]")
                    
                    for bloco in blocos:
                        try:
                            texto = bloco.text
                            if not texto:
                                continue
                                
                            # Verifica se é a norma exata que procuramos
                            if self._is_exact_match(texto, tipo_norma, numero_norma):
                                status = self._extract_status_sefaz_pi_aninhado(bloco)
                                return {
                                    "status": status or "VIGENTE",  # Assume vigente se não detectar status
                                    "detalhes": texto[:500],  # Pega mais texto para contexto
                                    "url": self.driver.current_url
                                }
                        except StaleElementReferenceException:
                            continue
                            
                    # Se encontrou texto mas não identificou blocos
                    return {
                        "status": "VIGENTE",  # Assume que está vigente se encontrou o texto
                        "detalhes": "Norma encontrada no corpo da página",
                        "url": self.driver.current_url
                    }
                    
                except Exception as e:
                    self._salvar_pagina_erro("erro_processamento")
                    return {"status": "ERRO", "detalhes": str(e)}
                    
            finally:
                try:
                    self.driver.switch_to.default_content()
                except:
                    pass

    def _extract_status_sefaz_pi_aninhado(self, element):
        """Extrai status para HTML aninhado específico da SEFAZ-PI"""
        try:
            # Verifica o texto do elemento e elementos próximos
            texto = element.text.lower()
            
            # Padrões observados no seu print
            if "revogado" in texto or "revogada" in texto:
                return "REVOGADO"
            if "alterado" in texto or "alterada" in texto:
                return "ALTERADO"
            if "publicado" in texto:  # Pode indicar vigência
                return "VIGENTE"
                
            # Verifica elementos irmãos/pais
            try:
                parent = element.find_element(By.XPATH, "./..")
                parent_text = parent.text.lower()
                if "revogado" in parent_text:
                    return "REVOGADO"
            except:
                pass
                
            return None
        except:
            return None

    def _check_detailed_page(self, element):
        """Acessa a página de detalhes para verificar o status."""
        try:
            logger.debug("Tentando acessar página de detalhes")
            
            # Salva o contexto atual (iframe)
            current_window = self.driver.current_window_handle
            
            # Encontra e clica no link para detalhes
            try:
                logger.debug("Procurando link no elemento")
                link = element.find_element(By.TAG_NAME, "a")
                detalhes_url = link.get_attribute("href")
                logger.debug(f"Link encontrado: {detalhes_url}")
            except NoSuchElementException:
                logger.debug("Link não encontrado diretamente, procurando em subelementos")
                links = element.find_elements(By.CSS_SELECTOR, "a[href]")
                if links:
                    link = links[0]
                    detalhes_url = link.get_attribute("href")
                    logger.debug(f"Link encontrado em subelemento: {detalhes_url}")
                else:
                    logger.debug("Nenhum link encontrado no elemento")
                    return None
            
            # Abre nova aba
            logger.debug("Abrindo nova aba")
            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[1])
            
            # Acessa URL de detalhes
            logger.debug(f"Acessando URL de detalhes: {detalhes_url}")
            self.driver.get(detalhes_url)
            
            # Espera carregar
            logger.debug("Aguardando carregamento da página de detalhes")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
            )
            
            # Procura por informações de status
            logger.debug("Procurando informações de status")
            status = None
            selectors = [
                "//div[contains(@class, 'field-situacao')]",
                "//*[contains(text(), 'Situação')]/following-sibling::*",
                "//*[contains(text(), 'Status')]/following-sibling::*",
                "//*[contains(text(), 'Vigência')]/following-sibling::*",
                "//*[contains(text(), 'Estado')]/following-sibling::*"
            ]
            
            for selector in selectors:
                try:
                    logger.debug(f"Tentando selector: {selector}")
                    status_element = self.driver.find_element(By.XPATH, selector)
                    status_text = status_element.text.lower()
                    logger.debug(f"Texto do status encontrado: {status_text}")
                    
                    if "vigente" in status_text:
                        status = "VIGENTE"
                    elif "revogado" in status_text:
                        status = "REVOGADO"
                    elif "alterado" in status_text:
                        status = "ALTERADO"
                    if status:
                        logger.debug(f"Status determinado: {status}")
                        break
                except NoSuchElementException:
                    logger.debug(f"Selector {selector} não encontrado")
                    continue
            
            # Se não encontrou por seletores específicos, verifica o conteúdo geral
            if not status:
                logger.debug("Verificando conteúdo geral da página")
                body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                if "revogado" in body_text:
                    status = "REVOGADO"
                    logger.debug("Status REVOGADO encontrado no conteúdo geral")
                elif "vigente" in body_text:
                    status = "VIGENTE"
                    logger.debug("Status VIGENTE encontrado no conteúdo geral")
                elif "alterado" in body_text:
                    status = "ALTERADO"
                    logger.debug("Status ALTERADO encontrado no conteúdo geral")
            
            # Fecha a aba de detalhes
            logger.debug("Fechando aba de detalhes")
            self.driver.close()
            self.driver.switch_to.window(current_window)
            
            return status
            
        except Exception as e:
            logger.error(f"Erro ao verificar página de detalhes: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[0])
            return None

    def test_connection(self):
        """Testa conexão com o portal."""
        try:
            with self.browser_session():
                logger.info(f"Testando conexão com {self.base_url}")
                self.driver.get(self.base_url)
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='searchQuery']"))
                )
                logger.info("Conexão com SEFAZ bem-sucedida")
                return True
        except Exception as e:
            logger.error(f"Falha ao testar conexão: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            self._salvar_pagina_erro("teste_conexao_falha")
            return False

    def close(self):
        """Fecha o navegador e limpa recursos."""
        self._fechar_webdriver()