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

from monitor.models import Documento # Certifique-se que Documento está importado
import traceback


logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    def __init__(self, max_docs=10):  # Aumentei o limite padrão
        self.BASE_URL = "https://www.diario.pi.gov.br/doe/"
        self.max_docs = max_docs
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

    def _extrair_links_pdf(self, url: str) -> List[str]:
        """Extrai URLs de PDF de uma página web usando Selenium."""
        driver = self._get_webdriver()
        try:
            logger.info(f"Acessando URL: {url}")
            driver.get(url)

            # Espera até que pelo menos um link .pdf esteja presente na página
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '.pdf')]"))
            )

            logger.info("Página carregada, iniciando extração dos links PDF")
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            links_pdf = set()  # usar set direto evita duplicados

            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if href.lower().endswith('.pdf'):
                    # Normaliza a URL absoluta se for relativa
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
            # Não feche o driver aqui se for usar na mesma sessão
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

    def extrair_norma(self, texto: str) -> List[Tuple[str, str, int]]:
        """Extrai normas (tipo, número e ano) do texto de um documento."""
        normas = []
        # Regex ajustado para capturar tipo, número e ano (2 ou 4 dígitos após barra)
        padrao = re.compile(
            r'(?i)(lei complementar|lc|lei|decreto[\- ]?lei|decreto|ato normativo|portaria|instrução normativa|in|emenda constitucional|ec)[\s:]*(n[º°o.]?\s*)?(\d+([\.\/\-]\d+)*)(?:/(\d{2,4}))?',
            re.IGNORECASE
        )

        matches = padrao.finditer(texto)
        for match in matches:
            tipo = match.group(1).strip().upper()
            numero_raw = match.group(3).strip()
            numero_padronizado = self._padronizar_numero(numero_raw)
            ano_raw = match.group(5)
            ano = None
            if ano_raw:
                try:
                    ano_int = int(ano_raw)
                    # Se ano for 2 dígitos, converte para 4 dígitos (assume 2000+ para <50, senão 1900+)
                    if len(ano_raw) == 2:
                        ano = 2000 + ano_int if ano_int < 50 else 1900 + ano_int
                    else:
                        ano = ano_int
                except Exception:
                    ano = None
            normas.append((tipo, numero_padronizado, ano))
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
        """Filtro restritivo: exige pelo menos 2 termos prioritários, sendo 1 obrigatoriamente fiscal/tributário"""
        from monitor.models import TermoMonitorado

        termos = TermoMonitorado.objects.filter(ativo=True).order_by('-prioridade')
        texto_upper = texto.upper()
        termos_encontrados = set()
        termos_fiscais = {"ICMS", "TRIBUTÁRIO", "FISCAL", "SUBSTITUIÇÃO TRIBUTÁRIA", "ISS", "IPI", "PIS", "COFINS", "IRPJ", "CSLL", "SPED", "EFD", "DCTF", "SIMPLIFICADO", "SEFAZ"}

        for termo_obj in termos:
            termos_verificar = [termo_obj.termo]
            if termo_obj.variacoes:
                termos_verificar.extend([v.strip() for v in termo_obj.variacoes.split(',')])
            for termo in termos_verificar:
                if termo.upper() in texto_upper:
                    termos_encontrados.add(termo_obj.termo.upper())

        # Exige pelo menos 2 termos encontrados e pelo menos 1 termo fiscal/tributário
        if len(termos_encontrados) >= 2 and any(t in termos_fiscais for t in termos_encontrados):
            logger.info(f"Documento contém termos fiscais/tributários suficientes: {', '.join(termos_encontrados)}")
            return True

        logger.info(f"Documento ignorado por não atender ao filtro restritivo. Termos encontrados: {', '.join(termos_encontrados)}")
        return False


    # --- MÉTODO QUE ESTAVA FALTANDO E PRECISA SER ADICIONADO/CORRIGIDO ---
    def coletar_e_salvar_documentos(self, data_inicio: date, data_fim: date) -> List[Documento]:
        """Versão modificada para filtrar por termos prioritários"""
        documentos_salvos = []
        current_date = data_inicio
        
        try:
            while current_date <= data_fim:
                # Verifica se a data é múltiplo de 3 dias (0, 3, 6, ... dias desde data_inicio)
                dias_desde_inicio = (current_date - data_inicio).days
                if dias_desde_inicio % 3 != 0:
                    current_date += timedelta(days=1)
                    continue
                    
                logger.info(f"Processando diário para a data: {current_date.strftime('%Y-%m-%d')}")
                url_diario = f"{self.BASE_URL}?data={current_date.strftime('%d-%m-%Y')}"
                
                links_pdf_para_data = self._extrair_links_pdf(url_diario)
                
                if not links_pdf_para_data:
                    logger.info(f"Nenhum PDF encontrado para a data {current_date.strftime('%Y-%m-%d')}.")
                    current_date += timedelta(days=1)
                    continue

                for index, pdf_url in enumerate(links_pdf_para_data):
                    logger.info(f"Baixando PDF {index + 1}/{len(links_pdf_para_data)}: {pdf_url}")
                    pdf_content = self._baixar_pdf(pdf_url)

                    if pdf_content:
                        logger.info(f"Iniciando extração de texto de PDF: {pdf_url.split('/')[-1]}")
                        texto_extraido = self._extrair_texto_de_pdf(pdf_content)

                        if texto_extraido:
                            # Filtro principal - só salva se contiver termos prioritários
                            if not self._contem_termos_prioritarios(texto_extraido):
                                logger.info(f"PDF não contém termos prioritários. Ignorando.")
                                continue
                                
                            # Se passou pelo filtro, processa normalmente
                            assunto_geral = "Contábil/Fiscal"  # Já que passou pelo filtro
                            
                            try:
                                documento, created = Documento.objects.update_or_create(
                                    url_original=pdf_url,
                                    defaults={
                                        'titulo': f"Diário Oficial - {current_date.strftime('%d/%m/%Y')} - Parte {index + 1}",
                                        'data_publicacao': current_date,
                                        'texto_completo': texto_extraido,
                                        'processado': False,
                                        'relevante_contabil': True,  # Já que passou pelo filtro
                                        'assunto': assunto_geral,
                                        'metadata': {'data_coleta': timezone.now().isoformat()},
                                    }
                                )
                                
                                file_name = f"DOEPI_{current_date.strftime('%Y%m%d')}_{pdf_url.split('/')[-1]}"
                                documento.arquivo_pdf.save(file_name, ContentFile(pdf_content), save=True)
                                
                                documentos_salvos.append(documento)
                                logger.info(f"Documento '{file_name}' salvo com sucesso (novo: {created}).")

                            except Exception as db_e:
                                logger.error(f"Erro ao salvar documento {pdf_url}: {db_e}", exc_info=True)
                        else:
                            logger.warning(f"Não foi possível extrair texto de {pdf_url}.")
                    else:
                        logger.warning(f"Não foi possível baixar o PDF de {pdf_url}.")
                
                current_date += timedelta(days=1)
                time.sleep(2)

        except Exception as e:
            logger.error(f"Erro durante coleta: {e}", exc_info=True)
            raise

        finally:
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