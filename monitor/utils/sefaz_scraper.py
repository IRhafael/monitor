
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

    def verificar_vigencia_rapida(self, norm_type, norm_number):
        """
        Tenta verificar a vigência da norma acessando diretamente o iframe de busca (vivisimo) do portal SEFAZ.
        Retorna True se vigente, False se não vigente, None se não encontrou.
        Agora também analisa o bloco .field-snippet .value para maior robustez.
        Regex mais flexível e logs para debug.
        """
        try:
            termo_busca = f"{norm_type} {norm_number}".replace("/", " ")
            iframe_url = f"{self.base_url}/vivisimo/cgi-bin/query-meta?v%3Aproject=Legislacao&query={termo_busca.replace(' ', '+')}*"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(iframe_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                self.logger.warning(f"Busca rápida (iframe) falhou: status {resp.status_code}")
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            blocos = soup.select('.values .value')
            blocos += soup.select('a.title')
            snippet_bloco = soup.select_one('.field-snippet .value')
            if snippet_bloco:
                blocos.append(snippet_bloco)
            # Regex ainda mais tolerante para número e tipo
            # Gera regex flexível para número: aceita pontos, barras, espaços, etc
            numero_flex = re.sub(r'[^\d]', '', norm_number)
            # Cria padrão que aceita separadores entre os dígitos
            padrao_numero = r'(n[º°\.]?\s*)?' + r''.join([f'{d}[\.\-/\s]*' for d in numero_flex]) + r'(\d{{2,4}})?'
            padrao_tipo = re.escape(norm_type.lower())
            # Permite qualquer coisa (inclusive acentos, vírgulas, etc) entre tipo e número, e vice-versa
            padrao_geral = rf"{padrao_tipo}.{{0,40}}?{padrao_numero}|{padrao_numero}.{{0,40}}?{padrao_tipo}"
            for bloco in blocos:
                texto_bloco = bloco.get_text(" ", strip=True).lower()
                # Normaliza espaços e quebras de linha
                texto_bloco_norm = re.sub(r"\s+", " ", texto_bloco)
                self.logger.info(f"[DEBUG] Analisando bloco: {texto_bloco_norm}")
                if re.search(padrao_geral, texto_bloco_norm, re.DOTALL):
                    self.logger.info(f"[DEBUG] Match tipo/numero: {texto_bloco_norm}")
                    # Busca "vigente" ou "revogado" no texto do bloco
                    if "vigente" in texto_bloco_norm and not any(t in texto_bloco_norm for t in ["revogado", "cancelado", "extinto"]):
                        self.logger.info(f"[DEBUG] Encontrado vigente: {texto_bloco_norm}")
                        return True
                    if any(t in texto_bloco_norm for t in ["revogado", "cancelado", "extinto"]):
                        self.logger.info(f"[DEBUG] Encontrado revogado/cancelado/extinto: {texto_bloco_norm}")
                        return False
                    # Se não há menção explícita, mas há menção a alterações recentes, considerar vigente
                    if any(x in texto_bloco_norm for x in ["alterado pelo", "alterada pelo", "alterados pelos", "alterada pelos"]):
                        if not any(t in texto_bloco_norm for t in ["revogado", "cancelado", "extinto"]):
                            self.logger.info(f"[DEBUG] Considerado vigente por alterações: {texto_bloco_norm}")
                            return True
                else:
                    self.logger.info(f"[DEBUG] Não bateu tipo/numero: {texto_bloco_norm}")
            self.logger.info("[DEBUG] Nenhum bloco correspondeu ao tipo/número informado.")
            return False
        except Exception as e:
            self.logger.warning(f"verificar_vigencia_rapida falhou: {e}")
            return None
    def __init__(self):
        self.base_url = "https://portaldalegislacao.sefaz.pi.gov.br"
        self.timeout = 30
        self.debug_dir = r"C:\Users\RRCONTAS\Documents\GitHub\monitor\debug"
        self.driver = None
        
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
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Cria diretório de debug
        os.makedirs(self.debug_dir, exist_ok=True)
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)


    def get_priority_terms(self):
        """Retorna a lista de termos prioritários"""
        return self.priority_terms

    def _save_debug_info(self, prefix):

        pass


    def _contem_termos_prioritarios(self, texto: str) -> bool:
        """Verifica se o texto contém termos monitorados ativos"""
        try:
            from monitor.models import TermoMonitorado
        except ImportError:
            return False
        termos = TermoMonitorado.objects.filter(ativo=True).order_by('-prioridade')
        texto_upper = texto.upper()
        for termo_obj in termos:
            termos_verificar = [termo_obj.termo]
            if termo_obj.variacoes:
                termos_verificar.extend([v.strip() for v in termo_obj.variacoes.split(',')])
            for termo in termos_verificar:
                if termo.upper() in texto_upper:
                    return True
        return False

    @contextmanager
    def browser_session(self):
        tentativas = 0
        max_tentativas = 3
        driver = None
        try:
            while tentativas < max_tentativas:
                try:
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(
                        service=service,
                        options=self.chrome_options
                    )
                    driver.set_page_load_timeout(self.timeout)
                    self.driver = driver
                    yield driver
                    break
                except Exception as e:
                    tentativas += 1
                    self.logger.error(f"Erro na sessão do navegador (tentativa {tentativas}/{max_tentativas}): {str(e)}")
                    if tentativas >= max_tentativas:
                        raise
                    time.sleep(5)
        finally:
            if driver:
                try:
                    driver.quit()
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

    def coletar_documentos(self, data_inicio=None, data_fim=None):
        from monitor.models import Documento
        documentos_salvos = []
        # Exemplo: supondo que já existe uma lista de URLs de PDFs para coletar
        lista_urls = self._obter_lista_pdfs(data_inicio, data_fim)
        for pdf_url in lista_urls:
            try:
                pdf_content = self._baixar_pdf(pdf_url)
                if not pdf_content:
                    continue
                texto_extraido = self._extrair_texto_de_pdf(pdf_content)
                if not texto_extraido:
                    continue
                if not self._contem_termos_prioritarios(texto_extraido):
                    self.logger.info(f"PDF ignorado (sem relevância fiscal/contábil): {pdf_url}")
                    continue
                file_name = pdf_url.split('/')[-1]
                documento, created = Documento.objects.update_or_create(
                    url_original=pdf_url,
                    defaults={
                        'titulo': file_name,
                        'data_publicacao': datetime.now().date(),
                        'texto_completo': texto_extraido,
                        'processado': False,
                        'relevante_contabil': True,
                        'assunto': 'Contábil/Fiscal',
                        'metadata': {'data_coleta': datetime.now().isoformat()},
                    }
                )
                documento.arquivo_pdf.save(file_name, pdf_content)
                documentos_salvos.append(documento)
                self.logger.info(f"Documento '{file_name}' salvo com sucesso (novo: {created}).")
            except Exception as e:
                self.logger.error(f"Erro ao salvar documento {pdf_url}: {e}", exc_info=True)
        return documentos_salvos

    def _obter_lista_pdfs(self, data_inicio=None, data_fim=None):
        # Implemente a lógica para obter a lista de URLs de PDFs do SEFAZ
        # Exemplo: retornar uma lista mock para teste
        return []
    def _pesquisar_norma(self, norm_type=None, norm_number=None, term=None):
        """Executa a pesquisa no portal com norm_type/norm_number ou com termo prioritário"""
        try:
            search_input = self._wait_for_element(
                By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
            
            if not search_input:
                self.logger.error("Campo de busca não encontrado")
                return False
            
            # Define o termo de busca: se receber term, usa ele, senão usa norm_type + norm_number
            if term:
                termo_busca = term + "*"
            else:
                termo_busca = f"{norm_type} {norm_number}*" if norm_type and norm_number else ""
            
            if not termo_busca:
                self.logger.error("Nenhum termo de busca fornecido")
                return False

            search_input.clear()
            search_input.send_keys(termo_busca)
            self._save_debug_info("02_campo_preenchido")
            
            # Clica no botão de busca (melhor que usar Keys.RETURN)
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

    def get_norm_details(self, norm_type, norm_number):
        """Busca detalhes da norma com base na estrutura HTML fornecida e enriquece para o modelo Documento"""
        try:
            from monitor.utils.enriquecedor import enriquecer_documento_dict
            with self.browser_session():
                # 1. Acessa a página principal
                self.driver.get(self.base_url)
                self._save_debug_info("01_pagina_inicial")
                # 2. Executa a pesquisa
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
                    # Constrói o resultado bruto
                    result = {
                        'norma': f"{norm_type} {norm_number}",
                        'texto_completo': snippet,
                        **fields
                    }
                    # Enriquecimento para o modelo Documento
                    enriched = enriquecer_documento_dict(result)
                    self._save_debug_info("04_norma_encontrada")
                    return enriched
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
            field_text = field.text
            for strong in field.find_elements(By.TAG_NAME, "strong"):
                field_text = field_text.replace(strong.text, "").strip()
            return field_text if field_text else ""
        except NoSuchElementException:
            return ""
        
    def _extract_link(self, parent, field_class):
        """Extrai um link de um campo específico"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            link = field.find_element(By.TAG_NAME, "a")
            return {
                'texto': link.text if link.text else "",
                'url': link.get_attribute("href") if link.get_attribute("href") else ""
            }
        except NoSuchElementException:
            return {"texto": "", "url": ""}

    def _extract_links(self, parent, field_class):
        """Extrai múltiplos links de um campo (como 'Altera')"""
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            links = []
            for link in field.find_elements(By.TAG_NAME, "a"):
                links.append({
                    'texto': link.text if link.text else "",
                    'url': link.get_attribute("href") if link.get_attribute("href") else ""
                })
            return links
        except NoSuchElementException:
            return []

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
        # Verificação inicial rigorosa
        if not norm_type or not norm_number or len(norm_number.strip()) < 3:
            return {
                "status": "DADOS_INVALIDOS",
                "erro": "Tipo ou número da norma inválidos",
                "vigente": False
            }

        details = self.get_norm_details(norm_type, norm_number)

        if not details:
            return {
                "status": "NAO_ENCONTRADA",
                "vigente": False,
                "fonte": self.driver.current_url if self.driver else None
            }

        situacao = details.get('situacao', '')
        situacao_lower = situacao.lower() if situacao else ''
        
        # Apenas considera vigente se:
        # 1. O campo situação existir
        # 2. Contiver explicitamente "vigente"
        # 3. Não contiver termos de revogação
        if (situacao_lower and 
            'vigente' in situacao_lower and 
            not any(term in situacao_lower for term in ['revogado', 'cancelado', 'extinto'])):
            status = "VIGENTE"
        else:
            status = "NAO_VIGENTE"

        return {
            "status": status,
            "vigente": status == "VIGENTE",  # Campo booleano explícito
            "fonte": self.driver.current_url if self.driver else None,
            "dados": details
        }




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