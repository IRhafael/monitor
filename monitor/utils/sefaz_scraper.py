# monitor/utils/sefaz_scraper.py
import re
import time
import logging
import urllib.parse
import json
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
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.service import Service as ChromeService
import nltk
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suprime mensagens do TensorFlow

# Garante que os recursos do NLTK estejam disponíveis
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

logger = logging.getLogger(__name__)

class SEFAZScraper:
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.search_url = f"{self.base_url}/search-results"
        self.driver = None
        self.timeout = 30
        self.max_retries = 2
        
        # Configuração otimizada do ChromeService
        self.chrome_service = ChromeService(
            log_path='chromedriver.log',
            service_args=['--silent', '--disable-logging']
        )

    def _iniciar_navegador(self):
        """Configuração otimizada do navegador"""
        try:
            chrome_options = Options()
            
            # Configurações essenciais
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            # Otimizações de performance
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument("--log-level=3")
            
            # Configurações de rede
            chrome_options.add_argument("--disable-http2")
            chrome_options.add_argument("--disable-quic")
            
            # Evitar detecção como bot
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # Configurações adicionais para evitar detecção
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            
            # Desabilitar imagens para melhor performance
            chrome_options.add_argument("--blink-settings=imagesEnabled=false")
            
            # Inicialização do driver
            self.driver = webdriver.Chrome(
                service=self.chrome_service,
                options=chrome_options
            )
            
            # Configurações de timeout
            self.driver.set_page_load_timeout(self.timeout)
            self.driver.set_script_timeout(20)
            self.driver.implicitly_wait(5)
            
            return True
        except Exception as e:
            logger.error(f"Erro ao iniciar navegador: {str(e)}")
            return False
        
    def _executar_com_retry(self, func, *args, **kwargs):
        for tentativa in range(1, self.max_retries + 1):
            try:
                if not self._iniciar_navegador():
                    time.sleep(2 * tentativa)
                    continue
                    
                resultado = func(*args, **kwargs)
                return resultado
                
            except Exception as e:
                logger.warning(f"Tentativa {tentativa} falhou: {str(e)}")
                if tentativa == self.max_retries:
                    raise
                time.sleep(3 * tentativa)  # Backoff exponencial
            finally:
                self._fechar_navegador()
        def testar_conexao(self):
            """Testa se a conexão com o portal está funcionando"""
            try:
                return self._executar_com_retry(self._testar_conexao_interna)
            except Exception as e:
                logger.error(f"Falha ao testar conexão: {str(e)}")
                return False

        def _testar_conexao_interna(self):
            """Teste interno de conexão"""
            self.driver.get(self.base_url)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body")))
            return "SEFAZ" in self.driver.title

    def _fechar_navegador(self):
        """Fecha o navegador corretamente"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Erro ao fechar navegador: {str(e)}")
            finally:
                self.driver = None

    def verificar_vigencia_rapida(self, tipo, numero):
        """Método otimizado para verificação rápida"""
        tipo = tipo.upper().strip()
        numero = re.sub(r'[^\d/]', '', str(numero)).strip()
        
        try:
            if not self._iniciar_navegador():
                return False
                
            # Tentativa 1: URL direta (mais rápida)
            status = self._verificar_por_url_direta(tipo, numero)
            if status is not None:
                return status
                
            # Tentativa 2: Pesquisa simplificada
            return self._pesquisa_rapida(tipo, numero) or False
            
        except Exception as e:
            logger.error(f"Erro na verificação rápida: {str(e)}")
            return False
        finally:
            self._fechar_navegador()

    def _pesquisar_norma(self, tipo, numero):
        """Pesquisa otimizada com timeout reduzido"""
        try:
            query = f"{tipo} {numero}".strip()
            url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
            
            # Timeout reduzido para a pesquisa
            self.driver.set_page_load_timeout(30)
            
            try:
                self.driver.get(url)
            except TimeoutException:
                logger.warning(f"Timeout parcial no carregamento de {query}")
                # Continua com o conteúdo já carregado
                
            # Espera flexível por resultados
            try:
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                
                # Verificação rápida de resultados
                resultados = self.driver.find_elements(By.CSS_SELECTOR, ".result-item, .search-result")
                return bool(resultados)
                
            except TimeoutException:
                logger.warning(f"Timeout ao aguardar resultados para {query}")
                return None
                
        except Exception as e:
            logger.error(f"Erro na pesquisa de {query}: {str(e)}")
            return None

    def _extrair_url_documento(self):
        """Extrai a URL do documento nos resultados"""
        try:
            resultados = self.driver.find_elements(
                By.CSS_SELECTOR, ".result-item, .search-result"
            )
            
            for resultado in resultados[:1]:  # Pega apenas o primeiro resultado
                try:
                    link = resultado.find_element(By.CSS_SELECTOR, "a")
                    return link.get_attribute("href")
                except NoSuchElementException:
                    continue
                    
            return None
            
        except Exception as e:
            logger.error(f"Erro ao extrair URL do documento: {str(e)}")
            return None

    def _extrair_status_norma(self):
        """Extrai o status da norma nos resultados"""
        try:
            resultados = self.driver.find_elements(
                By.CSS_SELECTOR, ".result-item, .search-result"
            )
            
            for resultado in resultados:
                try:
                    titulo = resultado.find_element(By.CSS_SELECTOR, "h3").text
                    texto = resultado.text.lower()
                    
                    # Verifica tags de status
                    tags = resultado.find_elements(By.CSS_SELECTOR, ".tag, .status-badge")
                    for tag in tags:
                        if "revogado" in tag.text.lower() or "cancelado" in tag.text.lower():
                            return False
                    
                    # Verifica no texto completo
                    if "revogado" in texto or "cancelado" in texto:
                        return False
                        
                    return True
                    
                except NoSuchElementException:
                    continue
                    
            return None
            
        except Exception as e:
            logger.error(f"Erro ao extrair status: {str(e)}")
            return None

    def _extrair_conteudo_completo(self, url):
        """Extrai o conteúdo completo de uma norma a partir da URL"""
        try:
            if not url:
                return None
                
            self.driver.get(url)
            time.sleep(2)
            
            # Aguarda carregamento do conteúdo
            WebDriverWait(self.driver, self.timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".document-content, .norma-content, article"))
            )
            
            # Extrai o conteúdo da norma
            conteudo_elemento = self.driver.find_element(
                By.CSS_SELECTOR, ".document-content, .norma-content, article"
            )
            
            return conteudo_elemento.text
            
        except TimeoutException:
            logger.error(f"Timeout ao acessar documento: {url}")
            return None
        except NoSuchElementException:
            logger.error(f"Conteúdo não encontrado em: {url}")
            return None
        except Exception as e:
            logger.error(f"Erro ao extrair conteúdo: {str(e)}")
            return None

    def _gerar_resumo(self, texto, max_sentencas=5):
        """Gera um resumo do texto utilizando NLTK"""
        if not texto:
            return "Conteúdo não disponível para resumo."
            
        try:
            # Tokeniza as sentenças
            sentencas = sent_tokenize(texto, language='portuguese')
            
            # Se o texto for pequeno, retorna ele mesmo
            if len(sentencas) <= max_sentencas:
                return texto
                
            # Escolhe as primeiras sentenças como resumo (geralmente são mais informativas em normas)
            resumo = ' '.join(sentencas[:max_sentencas])
            return resumo
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {str(e)}")
            return texto[:500] + "..."  # Fallback simples
    
    def _extrair_referencias_normas(self, texto):
        """Extrai referências a outras normas no texto"""
        if not texto:
            return []
            
        referencias = []
        
        # Padrões comuns de referências a normas
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução|Deliberação)\s+(?:n[º°.]?\s*)?(\d[\d\.\/\-]+)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO|DELIBERAÇÃO)\s+(?:N[º°.]?\s*)?(\d[\d\.\/\-]+)'
        ]
        
        for padrao in padroes:
            matches = re.finditer(padrao, texto, re.IGNORECASE)
            for match in matches:
                tipo = match.group(1).strip()
                numero = re.sub(r'[^\d\/]', '', match.group(2)).strip()
                
                # Evita duplicatas
                referencia = {'tipo': tipo.upper(), 'numero': numero}
                if referencia not in referencias:
                    referencias.append(referencia)
                    
        return referencias
    
    def _verificar_por_url_direta(self, tipo, numero):
        """Tenta acessar diretamente a norma"""
        try:
            url = f"{self.base_url}/{tipo.lower()}/{numero}"
            self.driver.get(url)
            
            # Verificação instantânea de conteúdo
            if "revogado" in self.driver.page_source.lower():
                return False
            if "vigente" in self.driver.page_source.lower():
                return True
            return None
        except Exception:
            return None

    def _pesquisa_rapida(self, tipo, numero):
        """Pesquisa simplificada com timeout reduzido"""
        try:
            query = f"{tipo} {numero}"
            url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
            self.driver.get(url)
            
            # Espera por elementos visíveis (não completa)
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.XPATH, "//*[contains(@class, 'result')]"))
            )
            
            # Verificação rápida no primeiro resultado
            primeiro_resultado = self.driver.find_element(By.XPATH, "//*[contains(@class, 'result')]")
            return "revogado" not in primeiro_resultado.text.lower()
        except Exception:
            return None

    def verificar_vigencia_norma(self, tipo, numero):
        """Versão robusta com múltiplas estratégias"""
        tipo = tipo.upper().strip()
        numero = re.sub(r'[^\d/]', '', str(numero)).strip()
        
        for tentativa in range(1, self.max_retries + 1):
            try:
                if not self._iniciar_navegador():
                    time.sleep(3 * tentativa)
                    continue
                    
                # Tentativa 1: URL direta (mais rápida)
                status = self._verificar_por_url_direta(tipo, numero)
                if status is not None:
                    return status
                    
                # Tentativa 2: Pesquisa tradicional
                encontrada = self._pesquisar_norma(tipo, numero)
                if encontrada is None:
                    return False
                    
                return self._extrair_status_norma() or True  # Assume vigente se não determinar
                
            except Exception as e:
                logger.error(f"Tentativa {tentativa} falhou: {str(e)}")
            finally:
                self._fechar_navegador()
                if tentativa < self.max_retries:
                    time.sleep(5 * tentativa)  # Backoff exponencial
        
        return False  # Default conservadorconservador

    def coletar_normas(self):
        """Coleta as últimas normas publicadas"""
        try:
            if not self._iniciar_navegador():
                return []

            self.driver.get(self.search_url)
            time.sleep(2)

            # Pesquisa genérica para trazer as últimas normas
            try:
                search_input = WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='search'], input[type='text']"))
                )
                search_input.send_keys("norma")
                
                search_button = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "button[type='submit'], button.search-button, button.btn-primary"
                )
                search_button.click()
                
                # Aguarda resultados
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item, .search-result, .norma-item"))
                )
                
                # Processa os resultados
                normas = []
                resultados = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    ".result-item, .search-result, .norma-item"
                )[:self.max_normas]
                
                for item in resultados:
                    try:
                        texto = item.text
                        tipo = self._extrair_tipo(texto)
                        numero = self._extrair_numero(texto)
                        data = self._extrair_data(texto)
                        
                        if tipo and numero:
                            normas.append({
                                'tipo': tipo.upper(),
                                'numero': numero,
                                'data': data or datetime.now().date(),
                                'conteudo': texto[:500]  # Limita o conteúdo
                            })
                    except Exception as e:
                        logger.warning(f"Erro ao processar item: {str(e)}")
                        continue
                        
                return normas
                
            except TimeoutException:
                logger.error("Timeout ao coletar normas")
                return []
            except NoSuchElementException:
                logger.error("Elementos não encontrados na página")
                return []
                
        except Exception as e:
            logger.error(f"Erro na coleta de normas: {str(e)}")
            return []
        finally:
            self._fechar_navegador()

    def _extrair_tipo(self, texto):
        """Extrai o tipo da norma do texto"""
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução|Deliberação)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO|DELIBERAÇÃO)'
        ]
        
        texto = texto.replace('\n', ' ')
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extrair_numero(self, texto):
        """Extrai o número da norma do texto"""
        padroes = [
            r'(?:n[º°]?|numero?)\s*[:\.]?\s*([\d\/\.-]+)',
            r'(?:nº|n°|num|number)\s*([\d\/\.-]+)'
        ]
        
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return re.sub(r'[^\d\/]', '', match.group(1)).strip()
        return None

    def _extrair_data(self, texto):
        """Extrai a data da norma do texto"""
        padroes = [
            r'(\d{2}\/\d{2}\/\d{4})',
            r'(\d{2}\.\d{2}\.\d{4})',
            r'(?:publicad[oa]|em)\s*(\d{2}\/\d{2}\/\d{4})'
        ]
        
        for padrao in padroes:
            match = re.search(padrao, texto)
            if match:
                try:
                    data_str = match.group(1).replace('.', '/')
                    return datetime.strptime(data_str, '%d/%m/%Y').date()
                except ValueError:
                    continue
        return None

    def pesquisar_norma_detalhada(self, tipo, numero):
        """Pesquisa e coleta informações detalhadas de uma norma"""
        logger.info(f"Pesquisando detalhes da norma {tipo} {numero}")
        
        resultado = {
            'tipo': tipo,
            'numero': numero,
            'encontrada': False,
            'vigente': False,
            'url_documento': None,
            'conteudo_completo': None,
            'resumo': None,
            'referencias': []
        }
        
        for tentativa in range(1, self.max_retries + 1):
            try:
                if not self._iniciar_navegador():
                    continue
                    
                # Pesquisa a norma
                encontrou = self._pesquisar_norma(tipo, numero)
                if not encontrou:
                    logger.warning(f"Norma {tipo} {numero} não encontrada (tentativa {tentativa})")
                    continue
                    
                resultado['encontrada'] = True
                
                # Verifica vigência
                status = self._extrair_status_norma()
                resultado['vigente'] = status if status is not None else False
                
                # Extrai URL do documento
                url_documento = self._extrair_url_documento()
                resultado['url_documento'] = url_documento
                
                # Se encontrou URL, extrai conteúdo completo
                if url_documento:
                    conteudo = self._extrair_conteudo_completo(url_documento)
                    resultado['conteudo_completo'] = conteudo
                    
                    # Gera resumo
                    if conteudo:
                        resultado['resumo'] = self._gerar_resumo(conteudo)
                        
                        # Extrai referências a outras normas
                        resultado['referencias'] = self._extrair_referencias_normas(conteudo)
                
                return resultado
                
            except Exception as e:
                logger.error(f"Erro ao pesquisar norma detalhada: {str(e)}")
            finally:
                self._fechar_navegador()
                time.sleep(1)  # Intervalo entre tentativas
                
        return resultado

    def pesquisar_referencias_entre_normas(self, normas_coletadas, max_refs=5):
        """Pesquisa referências entre as normas coletadas"""
        logger.info(f"Analisando referências entre {len(normas_coletadas)} normas")
        
        normas_detalhadas = []
        
        # Limita o número de normas para análise detalhada para evitar sobrecarga
        for norma in normas_coletadas[:max_refs]:
            try:
                detalhes = self.pesquisar_norma_detalhada(norma['tipo'], norma['numero'])
                if detalhes['encontrada']:
                    normas_detalhadas.append(detalhes)
            except Exception as e:
                logger.error(f"Erro ao processar referências: {str(e)}")
                
        return normas_detalhadas

    def iniciar_coleta(self):
        """Método principal para iniciar a coleta"""
        logger.info("Iniciando coleta de normas")
        
        try:
            normas_coletadas = self.coletar_normas()
            normas_salvas = 0
            
            # Adiciona informações de vigência para cada norma
            for i, norma in enumerate(normas_coletadas):
                try:
                    # Limita a verificação de vigência às primeiras normas para evitar sobrecarga
                    if i < 10:  # Verifica apenas as 10 primeiras
                        vigente = self.verificar_vigencia_norma(norma['tipo'], norma['numero'])
                        norma['vigente'] = vigente
                    
                    # Salva a norma no banco de dados
                    _, created = Norma.objects.get_or_create(
                        tipo=norma['tipo'],
                        numero=norma['numero'],
                        defaults={
                            'data': norma['data'],
                            'conteudo': norma.get('conteudo', ''),
                            'vigente': norma.get('vigente', True)
                        }
                    )
                    if created:
                        normas_salvas += 1
                        
                except Exception as e:
                    logger.error(f"Erro ao processar norma {norma['tipo']} {norma['numero']}: {str(e)}")
            
            # Registra log de execução
            LogExecucao.objects.create(
                tipo_execucao='SEFAZ',
                status='SUCESSO',
                normas_coletadas=len(normas_coletadas),
                normas_salvas=normas_salvas,
                data_fim=timezone.now(),
                mensagem=f"Coletadas {len(normas_coletadas)} normas, {normas_salvas} novas"
            )
            
            return {
                'status': 'success',
                'normas_coletadas': len(normas_coletadas),
                'normas_novas': normas_salvas
            }
                
        except Exception as e:
            logger.error(f"Erro na coleta: {str(e)}", exc_info=True)
            LogExecucao.objects.create(
                tipo_execucao='SEFAZ',
                status='ERRO',
                data_fim=timezone.now(),
                erro_detalhado=str(e)
            )
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def gerar_relatorio_normas(self, normas_ids=None, limit=10):
        """Gera um relatório detalhado das normas, opcionalmente filtrando por IDs"""
        logger.info(f"Gerando relatório de normas")
        
        try:
            # Define a query base
            if normas_ids:
                normas = Norma.objects.filter(id__in=normas_ids)
            else:
                normas = Norma.objects.all().order_by('-data')[:limit]
            
            relatorio = []
            
            for norma in normas:
                # Pesquisa detalhes completos da norma
                detalhes = self.pesquisar_norma_detalhada(norma.tipo, norma.numero)
                
                # Atualiza registro no banco com informações novas
                if detalhes['encontrada']:
                    norma.vigente = detalhes['vigente']
                    if detalhes['url_documento']:
                        norma.url_documento = detalhes['url_documento']
                    if detalhes['conteudo_completo']:
                        norma.conteudo = detalhes['conteudo_completo']
                    norma.save()
                
                # Adiciona ao relatório
                relatorio.append({
                    'id': norma.id,
                    'tipo': norma.tipo,
                    'numero': norma.numero,
                    'data': norma.data.strftime('%d/%m/%Y'),
                    'vigente': detalhes['vigente'] if detalhes['encontrada'] else norma.vigente,
                    'resumo': detalhes['resumo'] if detalhes['resumo'] else self._gerar_resumo(norma.conteudo),
                    'referencias': detalhes['referencias'] if detalhes['encontrada'] else []
                })
            
            return {
                'status': 'success',
                'normas': relatorio,
                'total': len(relatorio)
            }
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'message': str(e)
            }
