# monitor/utils/diario_scraper.py

import os
import re
import time
import logging
import requests
from pdfminer.high_level import extract_text
from io import BytesIO
from datetime import datetime, timedelta, date # Adicione 'date' aqui
from urllib.parse import urljoin
import uuid # Importar uuid para títulos únicos, se necessário
from typing import List, Optional, Tuple # Adicionar Optional e Tuple para type hints
from pdfminer.layout import LAParams
from django.utils import timezone
from django.core.files.base import ContentFile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException # Adicionar import para tratamento de erros do Selenium
from selenium.webdriver.chrome.service import Service # Para inicializar o ChromeDriver corretamente

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
        self.driver = None # Inicializa o driver como None
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new") # Executa em modo headless
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--incognito") # Para evitar cache
        self.chrome_options.page_load_strategy = 'normal' # Espera a página carregar completamente


    def _get_webdriver(self):
        """Inicializa e retorna uma instância do WebDriver."""
        if self.driver is None:
            try:
                # Usa o Service para evitar o FutureWarning
                service = webdriver.chrome.service.Service() # Pode precisar de ChromeDriverManager().install() se não for automático
                self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
                self.driver.set_page_load_timeout(30) # Define um timeout para o carregamento da página
                logger.info("WebDriver inicializado com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao inicializar WebDriver: {e}", exc_info=True)
                self.driver = None # Garante que o driver está em um estado conhecido
                raise # Relaça o erro para ser tratado mais acima
        return self.driver

    def _fechar_webdriver(self):
        """Fecha a instância do WebDriver, se estiver aberta."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("WebDriver fechado.")

    def _extrair_links_pdf(self, url: str) -> List[Tuple[str, str, str]]:
        """Extrai tuplas (url_pdf, numero_edicao, data_edicao) dos PDFs da edição do dia atual."""
        driver = self._get_webdriver()
        try:
            logger.info(f"Acessando URL: {url}")
            driver.get(url)

            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//table[@id='tbl-diario']"))
            )

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            tabela = soup.find('table', id='tbl-diario')
            if not tabela:
                logger.warning("Tabela de edições não encontrada na página.")
                return []

            hoje = timezone.now().date()
            hoje_str = hoje.strftime('%d/%m/%Y')
            resultados = []

            for linha in tabela.find_all('tr'):
                colunas = linha.find_all('td')
                if len(colunas) < 3:
                    continue
                # Extrai link do PDF
                a_tag = colunas[0].find('a', href=True)
                if not a_tag:
                    continue
                href = a_tag['href'].strip()
                if not href.lower().endswith('.pdf'):
                    continue
                full_url = urljoin(self.BASE_URL, href)
                numero_edicao = colunas[1].get_text(strip=True)
                data_edicao = colunas[2].get_text(strip=True)
                if data_edicao == hoje_str:
                    resultados.append((full_url, numero_edicao, data_edicao))

            logger.info(f"{len(resultados)} PDFs encontrados para a data {hoje_str} em {url}")
            logger.debug(f"PDFs encontrados: {resultados}")
            return resultados

        except TimeoutException:
            logger.error(f"Timeout ao carregar a página ou encontrar elementos em {url}")
            return []
        except Exception as e:
            logger.error(f"Erro ao extrair links PDF de {url}: {str(e)}", exc_info=True)
            return []
        finally:
            pass


    def _extrair_texto_de_pdf(self, pdf_content: bytes) -> Optional[str]:
        """Extrai texto de conteúdo PDF em bytes."""
        try:
            # Tenta com pdfminer.high_level (mais robusto)
            # Use LAParams se precisar de layout de texto mais preciso
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
        """Baixa um arquivo PDF e retorna seu conteúdo como bytes."""
        try:
            logger.info(f"Tentando baixar PDF de: {url}")
            response = self.session.get(url, stream=True, timeout=15) # Aumentar timeout
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

            # Tentar importar PyPDF2 (mais comum e mantido)
            try:
                from PyPDF2 import PdfFileReader
                pdf_reader_class = PdfFileReader
                use_pypdf = True
            except ImportError:
                use_pypdf = False
            
            logger = logging.getLogger(__name__)
            logger.info(f"Iniciando extração de texto de PDF com {len(pdf_bytes)} bytes")
            
            # Criar um objeto BytesIO a partir dos bytes do PDF
            pdf_file = BytesIO(pdf_bytes)
            
            # ESTRATÉGIA 1: PDFMiner com parâmetros ajustados
            laparams = LAParams(
                line_margin=0.3,
                word_margin=0.1,
                char_margin=2.0,
                boxes_flow=0.5,
                detect_vertical=True,
                all_texts=True
            )
            
            # Lidar com páginas específicas se solicitado
            if paginas is not None:
                logger.info(f"Extraindo páginas específicas: {paginas}")
                texto_total = ""
                
                # Se PyPDF estiver disponível, verificar o número total de páginas
                if use_pypdf:
                    pdf = pdf_reader_class(pdf_file)
                    total_paginas = pdf.getNumPages()
                    logger.info(f"Total de páginas no documento: {total_paginas}")
                    
                    # Filtrar páginas válidas
                    paginas = [p for p in paginas if 0 <= p < total_paginas]
                    pdf_file.seek(0)  # Resetar o buffer para reutilização
                
                # Extrair cada página solicitada
                for pagina in paginas:
                    try:
                        texto_pagina = extract_text(
                            pdf_file, 
                            page_numbers=[pagina], 
                            laparams=laparams
                        )
                        texto_total += f"\n\n--- PÁGINA {pagina+1} ---\n\n" + texto_pagina
                        pdf_file.seek(0)  # Resetar o buffer para reutilização
                    except Exception as e:
                        logger.error(f"Erro ao extrair página {pagina}: {str(e)}")
                
                texto = texto_total
            else:
                # Extrair todas as páginas
                texto = extract_text(pdf_file, laparams=laparams)
            
            # ESTRATÉGIA 2: Se o texto estiver vazio ou muito curto, tentar PyPDF como fallback
            if (not texto or len(texto.strip()) < 200) and use_pypdf:
                logger.info("Texto insuficiente extraído pelo PDFMiner, tentando PyPDF como fallback")
                try:
                    pdf_file.seek(0)  # Resetar o buffer para reutilização
                    pdf = pdf_reader_class(pdf_file)
                    
                    texto_pypdf = ""
                    for pagina in range(pdf.getNumPages()):
                        if paginas is None or pagina in paginas:
                            page = pdf.getPage(pagina)
                            texto_pypdf += page.extractText() + "\n\n"
                    
                    # Se o texto do PyPDF for mais longo, usá-lo
                    if len(texto_pypdf.strip()) > len(texto.strip()):
                        logger.info("Usando texto extraído pelo PyPDF (mais completo)")
                        texto = texto_pypdf
                except Exception as e:
                    logger.error(f"Erro ao usar PyPDF como fallback: {str(e)}")
            
            # Tratamentos específicos para documentos contábeis
            if texto:
                # Remover caracteres de controle
                texto = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', texto)
                
                # Normalizar espaços em branco
                texto = re.sub(r'\s+', ' ', texto)
                texto = re.sub(r' {2,}', ' ', texto)
                
                # Normalizar quebras de linha
                texto = re.sub(r'(\S)\n(\S)', r'\1 \2', texto)
                
                # Preservar quebras de linha significativas (para tabelas e seções)
                texto = re.sub(r'([.:;,]) (\S)', r'\1 \2', texto)
                
                # Normalizar separadores decimais
                texto = re.sub(r'(\d+)[,\.](\d{2})(?=\s|$)', r'\1,\2', texto)
                
                # Resolver problemas com caracteres acentuados comuns em PDFs mal formatados
                char_map = {
                    '~': 'ã', '^': 'ê', '´': 'é', '`': 'à', '¸': 'ç',
                    'Ã£': 'ã', 'Ãª': 'ê', 'Ã©': 'é', 'Ã¡': 'á', 'Ã§': 'ç',
                    'Ãµ': 'õ', 'Ã³': 'ó', 'Ã­': 'í', 'Ãº': 'ú', 'Ã¢': 'â'
                }
                
                for orig, corr in char_map.items():
                    texto = texto.replace(orig, corr)
                
                # Corrigir espaçamento após pontuação
                texto = re.sub(r'([.:;,])([A-Za-z0-9])', r'\1 \2', texto)
                
                # Normalizar termos contábeis para facilitar buscas posteriores
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
        """Identifica o assunto geral do documento com base em palavras-chave."""
        texto_lower = texto.lower()
        palavras_chave_contabeis = ['contábil', 'fiscal', 'imposto', 'icms', 'issqn', 'tributo', 'declaração', 'contabilidade', 'auditoria']
        
        for palavra in palavras_chave_contabeis:
            if palavra in texto_lower:
                return "Contábil/Fiscal"
        
        return "Geral"

    def extrair_norma(self, texto: str) -> List[Tuple[str, str]]:
        """Extrai normas (tipo e número) do texto de um documento."""
        normas = []
        # Padrões para Lei, Decreto, Portaria, etc.
        # Captura o tipo da norma e um ou mais grupos de números separados por ponto, barra ou hífen
        padrao = r'(?i)(lei complementar|lc|lei|decreto[\- ]?lei|decreto|ato normativo|portaria|instrução normativa|in|emenda constitucional|ec)[\s:]*(n[º°o.]?\s*)?(\d+([\.\/\-]\d+)*)'
        
        matches = re.finditer(padrao, texto)
        for match in matches:
            tipo = match.group(1).strip().upper()
            numero_raw = match.group(3).strip()
            # Padroniza o número removendo zeros à esquerda se houver, e tratando separadores
            numero_padronizado = self._padronizar_numero(numero_raw)
            normas.append((tipo, numero_padronizado))
        return normas

    def _padronizar_numero(self, numero):
        """Padroniza o número da norma para remover zeros à esquerda e unificar separadores."""
        # Remove caracteres que não são dígitos, pontos, barras ou hífens
        numero = re.sub(r'[^0-9./-]', '', numero)
        # Divide o número em partes usando separadores e remove zeros à esquerda de cada parte numérica
        partes = re.split(r'([./-])', numero)
        resultado = []
        for parte in partes:
            if parte in ['.', '/', '-']:
                resultado.append(parte)
            else:
                # Remove zeros à esquerda, mas mantém '0' se o número for apenas '0'
                resultado.append(parte.lstrip('0') or '0')
        return ''.join(resultado)


    def _contem_termos_prioritarios(self, texto: str) -> bool:
        """Verifica se o texto contém termos monitorados ativos"""
        from monitor.models import TermoMonitorado
        
        # Busca termos ativos ordenados por prioridade (maior primeiro)
        termos = TermoMonitorado.objects.filter(ativo=True).order_by('-prioridade')
        
        texto = texto.upper()
        
        for termo_obj in termos:
            # Lista de termos para verificar incluindo o principal e variações
            termos_verificar = [termo_obj.termo]
            if termo_obj.variacoes:
                termos_verificar.extend([v.strip() for v in termo_obj.variacoes.split(',')])
            
            # Verifica cada variação
            for termo in termos_verificar:
                if termo.upper() in texto:
                    logger.info(f"Documento contém termo prioritário: {termo_obj.termo}")
                    return True
                    
        return False


    # --- MÉTODO QUE ESTAVA FALTANDO E PRECISA SER ADICIONADO/CORRIGIDO ---
    def coletar_e_salvar_documentos(self, *args, **kwargs):
        from monitor.models import Documento
        """Coleta e salva apenas os PDFs do Diário Oficial publicados na data de hoje."""
        documentos_salvos = []
        hoje = timezone.now().date()
        logger.info(f"Processando diário para a data: {hoje.strftime('%Y-%m-%d')}")
        url_diario = self.BASE_URL
        pdfs_do_dia = self._extrair_links_pdf(url_diario)
        if not pdfs_do_dia:
            logger.info(f"Nenhum PDF encontrado para a data {hoje.strftime('%Y-%m-%d')}")
        else:
            for index, (pdf_url, numero_edicao, data_edicao) in enumerate(pdfs_do_dia):
                logger.info(f"Baixando PDF {index + 1}/{len(pdfs_do_dia)}: {pdf_url} (Edição: {numero_edicao}, Data: {data_edicao})")
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
                                    'data_publicacao': hoje,
                                    'texto_completo': texto_extraido,
                                    'processado': False,
                                    'relevante_contabil': True,
                                    'assunto': assunto_geral,
                                    'numero_edicao': numero_edicao,
                                    'data_edicao': data_edicao,
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
    


    # Em diario_scraper.py
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