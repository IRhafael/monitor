import os
import re
import requests
from datetime import datetime, timedelta


# --- Lógica do Diário Oficial ---
import time
import logging
import requests
from pdfminer.high_level import extract_text
from io import BytesIO
from datetime import datetime, timedelta, date
from urllib.parse import urljoin
import uuid
from typing import List, Optional, Tuple
from pdfminer.layout import LAParams
from django.utils import timezone
from django.core.files.base import ContentFile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import traceback

logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    def __init__(self):
        self.BASE_URL = "https://www.diario.pi.gov.br/doe/"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.122.52 Chrome/91.0.4472.124 Safari/537.36'
        })
        self.driver = None
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--incognito")
        self.chrome_options.page_load_strategy = 'normal'

    def _get_webdriver(self):
        if self.driver is None:
            try:
                service = webdriver.chrome.service.Service()
                self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
                self.driver.set_page_load_timeout(30)
                logger.info("WebDriver inicializado com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao inicializar WebDriver: {e}", exc_info=True)
                self.driver = None
                raise
        return self.driver

    def _fechar_webdriver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("WebDriver fechado.")

    def _extrair_links_pdf(self, url: str) -> List[str]:
        driver = self._get_webdriver()
        try:
            logger.info(f"Acessando URL: {url}")
            driver.get(url)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '.pdf')]") )
            )
            logger.info("Página carregada, iniciando extração dos links PDF")
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            links_pdf = set()
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if href.lower().endswith('.pdf'):
                    full_url = urljoin(self.BASE_URL, href)
                    links_pdf.add(full_url)
            links_pdf = list(links_pdf)
            logger.info(f"{len(links_pdf)} links PDF encontrados em {url}")
            logger.debug(f"Links encontrados: {links_pdf}")
            return links_pdf
        except TimeoutException:
            logger.error(f"Timeout ao carregar a página ou encontrar elementos em {url}")
            return []
        except Exception as e:
            logger.error(f"Erro ao extrair links PDF de {url}: {str(e)}", exc_info=True)
            return []
        finally:
            pass

    def _extrair_texto_de_pdf(self, pdf_content: bytes) -> Optional[str]:
        try:
            laparams = LAParams(all_texts=True, detect_vertical=True)
            text = extract_text(BytesIO(pdf_content), laparams=laparams)
            if text and text.strip():
                return text.strip()
            logger.warning("Nenhum texto extraído do PDF.")
            return None
        except Exception as e:
            logger.error(f"Erro ao extrair texto do PDF: {e}", exc_info=True)
            return None

    def _baixar_pdf(self, url: str) -> Optional[bytes]:
        try:
            logger.info(f"Tentando baixar PDF de: {url}")
            response = self.session.get(url, stream=True, timeout=15)
            response.raise_for_status()
            pdf_content = response.content
            logger.info(f"PDF baixado com sucesso de {url}")
            return pdf_content
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao baixar PDF de {url}: {e}")
            return None

    def extrair_texto_pdf(self, pdf_bytes, paginas=None):
        try:
            from pdfminer.high_level import extract_text
            from pdfminer.layout import LAParams
            from io import BytesIO
            import logging
            import re
            import traceback
            try:
                from PyPDF2 import PdfFileReader
                pdf_reader_class = PdfFileReader
                use_pypdf = True
            except ImportError:
                use_pypdf = False
            logger = logging.getLogger(__name__)
            logger.info(f"Iniciando extração de texto de PDF com {len(pdf_bytes)} bytes")
            pdf_file = BytesIO(pdf_bytes)
            laparams = LAParams(
                line_margin=0.3,
                word_margin=0.1,
                char_margin=2.0,
                boxes_flow=0.5,
                detect_vertical=True,
                all_texts=True
            )
            if paginas is not None:
                logger.info(f"Extraindo páginas específicas: {paginas}")
                texto_total = ""
                if use_pypdf:
                    pdf = pdf_reader_class(pdf_file)
                    total_paginas = pdf.getNumPages()
                    logger.info(f"Total de páginas no documento: {total_paginas}")
                    paginas = [p for p in paginas if 0 <= p < total_paginas]
                    pdf_file.seek(0)
                for pagina in paginas:
                    try:
                        texto_pagina = extract_text(
                            pdf_file, 
                            page_numbers=[pagina], 
                            laparams=laparams
                        )
                        texto_total += f"\n\n--- PÁGINA {pagina+1} ---\n\n" + texto_pagina
                        pdf_file.seek(0)
                    except Exception as e:
                        logger.error(f"Erro ao extrair página {pagina}: {str(e)}")
                texto = texto_total
            else:
                texto = extract_text(pdf_file, laparams=laparams)
            if (not texto or len(texto.strip()) < 200) and use_pypdf:
                logger.info("Texto insuficiente extraído pelo PDFMiner, tentando PyPDF como fallback")
                try:
                    pdf_file.seek(0)
                    pdf = pdf_reader_class(pdf_file)
                    texto_pypdf = ""
                    for pagina in range(pdf.getNumPages()):
                        if paginas is None or pagina in paginas:
                            page = pdf.getPage(pagina)
                            texto_pypdf += page.extractText() + "\n\n"
                    if len(texto_pypdf.strip()) > len(texto.strip()):
                        logger.info("Usando texto extraído pelo PyPDF (mais completo)")
                        texto = texto_pypdf
                except Exception as e:
                    logger.error(f"Erro ao usar PyPDF como fallback: {str(e)}")
            if texto:
                texto = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', texto)
                texto = re.sub(r'\s+', ' ', texto)
                texto = re.sub(r' {2,}', ' ', texto)
                texto = re.sub(r'(\S)\n(\S)', r'\1 \2', texto)
                texto = re.sub(r'([.:;,]) (\S)', r'\1 \2', texto)
                texto = re.sub(r'(\d+)[,\.](\d{2})(?=\s|$)', r'\1,\2', texto)
                char_map = {
                    '~': 'ã', '^': 'ê', '´': 'é', '`': 'à', '¸': 'ç',
                    'Ã£': 'ã', 'Ãª': 'ê', 'Ã©': 'é', 'Ã¡': 'á', 'Ã§': 'ç',
                    'Ãµ': 'õ', 'Ã³': 'ó', 'Ã­': 'í', 'Ãº': 'ú', 'Ã¢': 'â'
                }
                for orig, corr in char_map.items():
                    texto = texto.replace(orig, corr)
                texto = re.sub(r'([.:;,])([A-Za-z0-9])', r'\1 \2', texto)
                termos_contabeis_map = {
                        r'i c m s': 'icms',
                        r'i\. c\. m\. s\.': 'icms',
                        r'i\.c\.m\.s\.': 'icms',
                        r'substit\. tribut\.': 'substituição tributária',
                        r'subst\. trib\.': 'substituição tributária',
                        r'reg\. especial': 'regime especial',
                        r'dec\. 21\.866': 'decreto 21.866',
                        r'decreto21\.866': 'decreto 21.866',
                        r'unatri': 'unatri',
                        r'unifis': 'unifis',
                        r'lei 4\.257': 'lei 4.257',
                        r'ato normativo 25/21': 'ato normativo 25/21',
                        r'ato normativo 26/21': 'ato normativo 26/21',
                        r'ato normativo 27/21': 'ato normativo 27/21',
                        r'secretaria de fazenda do estado do piauí': 'secretaria de fazenda do estado do piauí',
                        r'sefaz-?pi': 'sefaz-pi',
                        r'sefaz': 'sefaz',
                        r'substituição tributária': 'substituição tributária',
                    }
                for termo_orig, termo_norm in termos_contabeis_map.items():
                    texto = re.sub(r'\b' + re.escape(termo_orig) + r'\b', termo_norm, texto, flags=re.IGNORECASE)
                logger.info(f"Texto extraído com sucesso. Tamanho: {len(texto)} caracteres")
            else:
                logger.warning("Nenhum texto extraído do PDF")
                texto = ""
            return texto
        except Exception as e:
            logger.error(f"Erro ao extrair texto do PDF: {str(e)}")
            logger.error(traceback.format_exc())
            return ""

    def identificar_assunto_geral(self, texto: str) -> str:
        texto_lower = texto.lower()
        palavras_chave_contabeis = ['contábil', 'fiscal', 'imposto', 'icms', 'issqn', 'tributo', 'declaração', 'contabilidade', 'auditoria']
        for palavra in palavras_chave_contabeis:
            if palavra in texto_lower:
                return "Contábil/Fiscal"
        return "Geral"

    def extrair_norma(self, texto: str) -> List[Tuple[str, str]]:
        normas = []
        padrao = r'(?i)(lei complementar|lc|lei|decreto[\- ]?lei|decreto|ato normativo|portaria|instrução normativa|in|emenda constitucional|ec)[\s:]*(n[º°o.]?\s*)?(\d+([\.\/\-]\d+)*)'
        matches = re.finditer(padrao, texto)
        for match in matches:
            tipo = match.group(1).strip().upper()
            numero_raw = match.group(3).strip()
            numero_padronizado = self._padronizar_numero(numero_raw)
            normas.append((tipo, numero_padronizado))
        return normas

    def _padronizar_numero(self, numero):
        numero = re.sub(r'[^0-9./-]', '', numero)
        partes = re.split(r'([./-])', numero)
        resultado = []
        for parte in partes:
            if parte in ['.', '/', '-']:
                resultado.append(parte)
            else:
                resultado.append(parte.lstrip('0') or '0')
        return ''.join(resultado)

    def _contem_termos_prioritarios(self, texto: str) -> bool:
        from monitor.models import TermoMonitorado
        termos = TermoMonitorado.objects.filter(ativo=True).order_by('-prioridade')
        texto = texto.upper()
        for termo_obj in termos:
            termos_verificar = [termo_obj.termo]
            if termo_obj.variacoes:
                termos_verificar.extend([v.strip() for v in termo_obj.variacoes.split(',')])
            for termo in termos_verificar:
                if termo.upper() in texto:
                    logger.info(f"Documento contém termo prioritário: {termo_obj.termo}")
                    return True
        return False

    def coletar_e_salvar_documentos(self, data_inicio=None, data_fim=None):
        from monitor.models import Documento
        documentos_salvos = []
        if data_inicio and data_fim:
            datas = [data_inicio + timedelta(days=i) for i in range((data_fim - data_inicio).days + 1)]
        else:
            hoje = timezone.now().date()
            datas = [hoje]
        for data in datas:
            logger.info(f"Processando diário para a data: {data.strftime('%Y-%m-%d')}")
            url_diario = f"{self.BASE_URL}?data={data.strftime('%d-%m-%Y')}"
            links_pdf_para_data = self._extrair_links_pdf(url_diario)
            if not links_pdf_para_data:
                logger.info(f"Nenhum PDF encontrado para a data {data.strftime('%Y-%m-%d')}")
                continue
            for index, pdf_url in enumerate(links_pdf_para_data):
                logger.info(f"Baixando PDF {index + 1}/{len(links_pdf_para_data)}: {pdf_url}")
                pdf_content = self._baixar_pdf(pdf_url)
                if pdf_content:
                    logger.info(f"Iniciando extração de texto de PDF: {pdf_url.split('/')[-1]}")
                    texto_extraido = self._extrair_texto_de_pdf(pdf_content)
                    if texto_extraido:
                        if not self._contem_termos_prioritarios(texto_extraido):
                            logger.info(f"PDF não contém termos monitorados. Ignorando.")
                            continue
                        assunto_geral = "Contábil/Fiscal"
                        try:
                            file_name = pdf_url.split('/')[-1]
                            documento, created = Documento.objects.update_or_create(
                                url_original=pdf_url,
                                defaults={
                                    'titulo': file_name,
                                    'data_publicacao': data,
                                    'texto_completo': texto_extraido,
                                    'processado': False,
                                    'relevante_contabil': True,
                                    'assunto': assunto_geral,
                                    'metadata': {'data_coleta': timezone.now().isoformat()},
                                }
                            )
                            documento.arquivo_pdf.save(file_name, ContentFile(pdf_content), save=True)
                            documentos_salvos.append(documento)
                            logger.info(f"Documento '{file_name}' salvo com sucesso (novo: {created}).")
                        except Exception as db_e:
                            logger.error(f"Erro ao salvar documento {pdf_url}: {db_e}", exc_info=True)
                    else:
                        logger.warning(f"Não foi possível extrair texto de {pdf_url}.")
                else:
                    logger.warning(f"Não foi possível baixar o PDF de {pdf_url}.")
        self._fechar_webdriver()
        return documentos_salvos

    def _log_termos_encontrados(self, texto: str):
        from monitor.models import TermoMonitorado
        termos_encontrados = []
        termos = TermoMonitorado.objects.filter(ativo=True)
        for termo_obj in termos:
            termos_verificar = [termo_obj.termo]
            if termo_obj.variacoes:
                termos_verificar.extend([v.strip() for v in termo_obj.variacoes.split(',')])
            for termo in termos_verificar:
                if termo.upper() in texto.upper():
                    termos_encontrados.append(termo_obj.termo)
                    break
        if termos_encontrados:
            logger.info(f"Termos encontrados no documento: {', '.join(termos_encontrados)}")


# --- Lógica do SEFAZ ---
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

logger = logging.getLogger(__name__)

class SEFAZScraper:

    def verificar_vigencia_rapida(self, norm_type, norm_number):
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
                numero_flex = re.sub(r'[^0-9/]', '', norm_number)
            padrao_numero = r'(n[º°\.]?\s*)?' + r''.join([f'{d}[\.\-/\s]*' for d in numero_flex]) + r'(\d{2,4})?'
            padrao_tipo = re.escape(norm_type.lower())
            padrao_geral = rf"{padrao_tipo}.{{0,40}}?{padrao_numero}|{padrao_numero}.{{0,40}}?{padrao_tipo}"
            for bloco in blocos:
                texto_bloco = bloco.get_text(" ", strip=True).lower()
                texto_bloco_norm = re.sub(r"\s+", " ", texto_bloco)
                self.logger.info(f"[DEBUG] Analisando bloco: {texto_bloco_norm}")
                if re.search(padrao_geral, texto_bloco_norm, re.DOTALL):
                    self.logger.info(f"[DEBUG] Match tipo/numero: {texto_bloco_norm}")
                    if "vigente" in texto_bloco_norm and not any(t in texto_bloco_norm for t in ["revogado", "cancelado", "extinto"]):
                        self.logger.info(f"[DEBUG] Encontrado vigente: {texto_bloco_norm}")
                        return True
                    if any(t in texto_bloco_norm for t in ["revogado", "cancelado", "extinto"]):
                        self.logger.info(f"[DEBUG] Encontrado revogado/cancelado/extinto: {texto_bloco_norm}")
                        return False
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
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        os.makedirs(self.debug_dir, exist_ok=True)
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def get_priority_terms(self):
        return self.priority_terms

    def _save_debug_info(self, prefix):
        pass

    def _contem_termos_prioritarios(self, texto: str) -> bool:
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
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value)))
        except TimeoutException:
            self.logger.warning(f"Elemento não encontrado: {value}")
            return None

    def _clean_number(self, number):
        return re.sub(r'[^0-9/]', '', number).lower()

    def coletar_documentos(self, data_inicio=None, data_fim=None):
        from monitor.models import Documento
        documentos_salvos = []
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
        return []
    def _pesquisar_norma(self, norm_type=None, norm_number=None, term=None):
        try:
            search_input = self._wait_for_element(
                By.CSS_SELECTOR, "input[formcontrolname='searchQuery']")
            if not search_input:
                self.logger.error("Campo de busca não encontrado")
                return False
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
            search_button = self.driver.find_element(By.CSS_SELECTOR, "img[alt='search']")
            search_button.click()
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(By.TAG_NAME, "iframe").is_displayed())
            self._save_debug_info("03_pos_busca")
            return True
        except Exception as e:
            self.logger.error(f"Erro ao pesquisar: {str(e)}")
            self._save_debug_info("99_erro_pesquisa")
            return False

    def get_norm_details(self, norm_type, norm_number):
        try:
            from monitor.utils.enriquecedor import enriquecer_documento_dict
            with self.browser_session():
                self.driver.get(self.base_url)
                self._save_debug_info("01_pagina_inicial")
                if not self._pesquisar_norma(norm_type, norm_number):
                    return None
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.frame_to_be_available_and_switch_to_it((By.TAG_NAME, "iframe")))
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.document-body")))
                    doc_body = self.driver.find_element(By.CSS_SELECTOR, "div.document-body")
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
        try:
            no_results = self.driver.find_elements(By.XPATH, 
                "//*[contains(text(), 'Nenhum resultado') or contains(text(), 'No results')]")
            return not bool(no_results)
        except:
            return True
    
    def _extract_field(self, parent, field_class):
        try:
            field = parent.find_element(By.CSS_SELECTOR, f"div.{field_class}")
            field_text = field.text
            for strong in field.find_elements(By.TAG_NAME, "strong"):
                field_text = field_text.replace(strong.text, "").strip()
            return field_text if field_text else ""
        except NoSuchElementException:
            return ""
    
    def _extract_link(self, parent, field_class):
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
        try:
            iframe = self._wait_for_element(By.CSS_SELECTOR, "iframe")
            if iframe:
                self.driver.switch_to.frame(iframe)
                return True
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
        try:
            norm_type = norm_type.lower()
            norm_number_clean = re.sub(r'[^0-9/]', '', clean_number).lower()
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
        if (situacao_lower and 
            'vigente' in situacao_lower and 
            not any(term in situacao_lower for term in ['revogado', 'cancelado', 'extinto'])):
            status = "VIGENTE"
        else:
            status = "NAO_VIGENTE"
        return {
            "status": status,
            "vigente": status == "VIGENTE",
            "fonte": self.driver.current_url if self.driver else None,
            "dados": details
        }

    def test_connection(self):
        try:
            try:
                response = requests.get(self.base_url, timeout=10)
                if response.status_code != 200:
                    return False
            except requests.RequestException:
                return False
            with self.browser_session():
                self.driver.get(self.base_url)
                return "sefaz" in self.driver.title.lower()
        except Exception:
            return False
    
    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

# --- Lógica do SEFAZ ICMS ---
class SEFAZICMSScraper:
    def __init__(self):
        from selenium.webdriver.chrome.options import Options
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless=new')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    def coletar_documentos(self):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        import time
        import requests
        import os
        import re
        from datetime import datetime
        from monitor.models import Documento

        driver = webdriver.Chrome(options=self.chrome_options)
        driver.get("https://portaldalegislacao.sefaz.pi.gov.br/inicio")
        time.sleep(5)

        documentos_salvos = []
        elementos = driver.find_elements(By.CSS_SELECTOR, "div.text-title-content.cursor-pointer")
        norma_icms = None
        for el in elementos:
            if "Últimas Normas ICMS" in el.text:
                norma_icms = el
                break

        if norma_icms:
            ActionChains(driver).move_to_element(norma_icms).click(norma_icms).perform()
            time.sleep(3)

            cards = driver.find_elements(By.CSS_SELECTOR, "h1.cursor-pointer")
            for card in cards:
                titulo = card.text.strip()
                ActionChains(driver).move_to_element(card).click(card).perform()
                time.sleep(5)
                try:
                    vigencia = driver.find_element(By.XPATH, "//*[contains(text(),'Início da vigência')]").text
                    try:
                        strong_situacao = driver.find_element(By.XPATH, "//strong[contains(text(),'Situação:')]")
                        situacao = strong_situacao.find_element(By.XPATH, "following-sibling::text()[1]").strip()
                        if not situacao:
                            situacao = strong_situacao.find_element(By.XPATH, "..") .text.replace('Situação:', '').strip()
                    except Exception:
                        situacao = ''
                    publicacao = driver.find_element(By.XPATH, "//*[contains(text(),'Publicação')]").text
                    ementa = driver.find_element(By.XPATH, "//*[contains(text(),'Ementa')]").text
                    match = re.search(r'em (\d{2}/\d{2}/\d{4})', publicacao)
                    data_publicacao = None
                    if match:
                        data_str = match.group(1)
                        data_publicacao = datetime.strptime(data_str, '%d/%m/%Y').date()
                    if not data_publicacao:
                        data_publicacao = datetime.today().date()
                    div_baixar = driver.find_element(By.XPATH, "//div[contains(@class, 'button-text') and text()='Baixar']")
                    link_baixar = div_baixar.find_element(By.XPATH, "..")
                    href_baixar = link_baixar.get_attribute("href")
                    pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
                    href_baixar = None
                    for link in pdf_links:
                        if link.is_displayed():
                            href_baixar = link.get_attribute("href")
                            break
                    if href_baixar:
                        response = requests.get(href_baixar)
                        if response.status_code == 200:
                            nome_arquivo = href_baixar.split('/')[-1]
                            caminho_arquivo = os.path.join('pdfs_sefaz', nome_arquivo)
                            os.makedirs('pdfs_sefaz', exist_ok=True)
                            with open(caminho_arquivo, 'wb') as f:
                                f.write(response.content)
                            doc = Documento(
                                titulo=titulo,
                                data_publicacao=data_publicacao,
                                url_original=href_baixar,
                                docs_sefaz=caminho_arquivo,
                                resumo=ementa,
                                texto_completo='',
                                fonte_documento=publicacao,
                                metadata={
                                    'vigencia': vigencia,
                                    'situacao': situacao
                                }
                            )
                            doc.save()
                            documentos_salvos.append(doc)
                        else:
                            pass
                except Exception as e:
                    pass
                try:
                    btn_fechar = driver.find_element(By.CSS_SELECTOR, "button.p-dialog-header-close")
                    btn_fechar.click()
                    time.sleep(1)
                except Exception as e:
                    pass
        driver.quit()
        return documentos_salvos



# --- Lógica da API da Receita Federal ---
import requests
import json
import mysql.connector

BASE_URL = "http://localhost:8080/api"
ENDPOINTS = {
    "situacoes_tributarias_imposto_seletivo": "/calculadora/dados-abertos/situacoes-tributarias/imposto-seletivo",
    "situacoes_tributarias_cbs_ibs": "/calculadora/dados-abertos/situacoes-tributarias/cbs-ibs",
    "fundamentacoes_legais": "/calculadora/dados-abertos/fundamentacoes-legais",
    "classificacoes_tributarias_imposto_seletivo": "/calculadora/dados-abertos/classificacoes-tributarias/imposto-seletivo",
    "classificacoes_tributarias_cbs_ibs": "/calculadora/dados-abertos/classificacoes-tributarias/cbs-ibs",
    "aliquota_uniao": "/calculadora/dados-abertos/aliquota-uniao",
    "aliquota_uf": "/calculadora/dados-abertos/aliquota-uf"
}

def conectar_mysql():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="1234",
        database="monitor"
    )

def criar_tabelas():
    conn = conectar_mysql()
    cursor = conn.cursor()
    tabelas = {
        "situacoes_tributarias_imposto_seletivo": "CREATE TABLE IF NOT EXISTS situacoes_tributarias_imposto_seletivo (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "situacoes_tributarias_cbs_ibs": "CREATE TABLE IF NOT EXISTS situacoes_tributarias_cbs_ibs (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "fundamentacoes_legais": "CREATE TABLE IF NOT EXISTS fundamentacoes_legais (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "classificacoes_tributarias_imposto_seletivo": "CREATE TABLE IF NOT EXISTS classificacoes_tributarias_imposto_seletivo (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "classificacoes_tributarias_cbs_ibs": "CREATE TABLE IF NOT EXISTS classificacoes_tributarias_cbs_ibs (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "aliquota_uniao": "CREATE TABLE IF NOT EXISTS aliquota_uniao (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "aliquota_uf": "CREATE TABLE IF NOT EXISTS aliquota_uf (id INT AUTO_INCREMENT PRIMARY KEY, uf VARCHAR(2), data DATE, dados JSON)"
    }
    for sql in tabelas.values():
        cursor.execute(sql)
    conn.commit()
    cursor.close()
    conn.close()

def inserir_dados(nome, data, dados, uf=None):
    conn = conectar_mysql()
    cursor = conn.cursor()
    try:
        if nome == "aliquota_uf":
            cursor.execute(
                "INSERT INTO aliquota_uf (uf, data, dados) VALUES (%s, %s, %s)",
                (uf, data, json.dumps(dados, ensure_ascii=False))
            )
        else:
            cursor.execute(
                f"INSERT INTO {nome} (data, dados) VALUES (%s, %s)",
                (data, json.dumps(dados, ensure_ascii=False))
            )
        conn.commit()
    except Exception as e:
        print(f"[ERRO] Falha ao inserir em {nome} para data {data} UF {uf if nome == 'aliquota_uf' else ''}: {e}")
    finally:
        cursor.close()
        conn.close()

def consumir_endpoint(endpoint, params=None):
    url = BASE_URL + endpoint
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao consumir {endpoint}: {response.status_code}")
        try:
            print("Conteúdo da resposta:", response.text)
        except Exception:
            pass
        return None

def coletar_dados_receita(data=None):
    """
    Coleta dados dos endpoints da Receita Federal, salva no banco e retorna status.
    """
    criar_tabelas()
    ufs = consumir_endpoint("/calculadora/dados-abertos/ufs")
    if not ufs:
        print("Não foi possível obter a lista de UFs.")
        return False
    from datetime import date, timedelta
    hoje = date.today()
    datas_disponiveis = []
    datas_api = consumir_endpoint("/calculadora/dados-abertos/aliquota-uniao", {"data": hoje.strftime('%Y-%m-%d')})
    if datas_api and isinstance(datas_api, list):
        for item in datas_api:
            data_val = item.get('data') or item.get('dataReferencia') or item.get('data_ref')
            if data_val:
                datas_disponiveis.append(data_val)
    if not datas_disponiveis:
        for i in range(30):
            datas_disponiveis.append((hoje - timedelta(days=i)).strftime('%Y-%m-%d'))
    for nome, endpoint in ENDPOINTS.items():
        if nome == "aliquota_uf":
            continue
        for data in datas_disponiveis:
            dados = consumir_endpoint(endpoint, {"data": data})
            if dados:
                inserir_dados(nome, data, dados)
    for uf in ufs:
        codigo_uf = uf.get("codigoUf")
        sigla_uf = uf.get("sigla")
        if not codigo_uf:
            continue
        for data in datas_disponiveis:
            dados = consumir_endpoint(ENDPOINTS["aliquota_uf"], {"codigoUf": codigo_uf, "data": data})
            if dados:
                inserir_dados("aliquota_uf", data, dados, sigla_uf)
    return True


# --- Você pode adicionar outros scrapers aqui, copiando a lógica de cada arquivo ---

# Exemplo de uso centralizado:
if __name__ == "__main__":
    diario = DiarioOficialScraper()
    sefaz = SEFAZScraper()
    sefaz_icms = SEFAZICMSScraper()

    docs_diario = diario.coletar_e_salvar_documentos()
    docs_sefaz = sefaz.coletar_documentos()
    docs_icms = sefaz_icms.coletar_documentos()

    todos_docs = docs_diario + docs_sefaz + docs_icms
    print(f"Total de documentos coletados: {len(todos_docs)}")