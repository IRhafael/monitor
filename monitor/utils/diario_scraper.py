# diario_scraper.py

import os
import re
import time
import logging
import requests
from pdfminer.high_level import extract_text
from io import BytesIO
from datetime import datetime, timedelta
from urllib.parse import urljoin

from django.utils import timezone
from django.core.files.base import ContentFile

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from monitor.models import Documento
import traceback
import io
import PyPDF2
from pdfminer.high_level import extract_text as extract_text_pdfminer
from pdfminer.layout import LAParams




logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    def __init__(self, max_docs=10):  # Aumentei o limite padrão
        self.BASE_URL = "https://www.diario.pi.gov.br/doe/"
        self.max_docs = max_docs
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Atualizar a lista de termos contábeis
        self.termos_contabeis = [
            'icms', 'decreto 21.866', 'unatri', 
            'substituição tributária', 'regime especial'
        ]
    # Modifique o método configurar_navegador
    def configurar_navegador(self):
        """Configura o navegador Chrome em modo headless"""
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")  # Novo modo headless
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1280,720")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--log-level=3")  # Reduz logs do Chrome
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        # Configurações para evitar detecção
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            logger.error(f"Erro ao iniciar navegador: {str(e)}")
            return None

    def iniciar_coleta(self, data_inicio=None, data_fim=None):
        try:
            logger.info("Iniciando coleta de documentos")
            driver = self.configurar_navegador()
            if not driver:
                logger.error("Falha ao iniciar navegador")
                return []

            # Define data_inicio e data_fim padrão para evitar erros
            if data_inicio is None:
                data_inicio = datetime.now() - timedelta(days=7)  # padrão 7 dias atrás
                logger.info(f"data_inicio não fornecida. Usando padrão: {data_inicio}")
            if data_fim is None:
                data_fim = datetime.now()
                logger.info(f"data_fim não fornecida. Usando padrão: {data_fim}")

            datas = self.gerar_datas_no_intervalo(data_inicio, data_fim)
            logger.info(f"Datas a serem verificadas: {datas}")

            documentos_coletados = []

            for data in datas:
                url = self.construir_url_por_data(data)
                logger.info(f"Acessando URL: {url}")

                pdf_links = self.extrair_links_pdf(driver, url)
                logger.info(f"Encontrados {len(pdf_links)} links PDF para a data {data}")

                for link in pdf_links:
                    logger.info(f"Verificando acessibilidade do link: {link}")
                    if self.verificar_link_acessivel(link):
                        logger.info(f"Link acessível: {link} - Processando PDF")
                        documento = self.processar_pdf(link, data)
                        if documento:
                            documentos_coletados.append(documento)
                            logger.info(f"Documento processado e coletado: {documento}")
                        else:
                            logger.warning(f"Falha ao processar documento no link: {link}")
                    else:
                        logger.warning(f"Link inacessível: {link}")

            logger.info(f"Total de documentos coletados: {len(documentos_coletados)}")
            return documentos_coletados

        except Exception as e:
            logger.error(f"Erro na coleta: {str(e)}", exc_info=True)
            return []

        finally:
            if 'driver' in locals():
                logger.info("Finalizando navegador")
                driver.quit()

    
    def extrair_texto_pdf(self, pdf_bytes):
        """
        Extrai texto de um PDF usando múltiplas estratégias com fallback
        """
        # Tentativa 1: PyPDF2 (mais rápido para PDFs simples)
        try:
            texto = ""
            with io.BytesIO(pdf_bytes) as pdf_file:
                reader = PyPDF2.PdfReader(pdf_file)
                for page in reader.pages:
                    texto += page.extract_text() or ""
            if len(texto.strip()) > 100:  # Verifica se extraiu conteúdo suficiente
                return texto
        except Exception as e:
            print(f"PyPDF2 falhou: {str(e)}")

        # Tentativa 2: pdfminer.six (melhor para PDFs complexos)
        try:
            laparams = LAParams()
            with io.BytesIO(pdf_bytes) as pdf_file:
                texto = extract_text_pdfminer(pdf_file, laparams=laparams)
            return texto
        except Exception as e:
            print(f"PDFMiner falhou: {str(e)}")
            return None

    def verificar_link_acessivel(self, url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = self.session.get(url, headers=headers, timeout=10, stream=True)
            return response.status_code == 200
        except Exception:
            return False

    def normalizar_url(self, link):
        """Versão robusta para normalização de URLs"""
        if link.startswith('http'):
            return link
            
        # Remove ../ e ./ da URL
        link = re.sub(r'\.\./', '', link)
        link = re.sub(r'\./', '', link)
        
        base = self.BASE_URL.rstrip('/')
        return f"{base}/{link.lstrip('/')}"

    def processar_pdf(self, pdf_url, data_referencia):
        try:
            logger.info(f"Iniciando download do PDF: {pdf_url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = self.session.get(pdf_url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').lower()
            logger.info(f"Content-Type recebido: {content_type}")
            
            if content_type != 'application/pdf':
                logger.warning(f"URL não é um PDF válido: {pdf_url}")
                return None
            
            # Aqui você deve processar o conteúdo do PDF
            # Por exemplo, ler os bytes do PDF
            pdf_bytes = response.content
            logger.info(f"PDF baixado com sucesso. Tamanho: {len(pdf_bytes)} bytes")
            
            # Exemplo: extrair texto do PDF (ajuste para seu método real)
            texto_extraido = self.extrair_texto_pdf(pdf_bytes)
            logger.info(f"Texto extraído do PDF. Tamanho do texto: {len(texto_extraido)} caracteres")
            
            # Supondo que você crie um objeto documento
            documento = {
                'url': pdf_url,
                'data_referencia': data_referencia,
                'texto': texto_extraido,
                # outros campos que você usa
            }
            
            logger.info(f"Processamento do PDF concluído com sucesso: {pdf_url}")
            return documento

        except requests.HTTPError as e:
            logger.error(f"Erro HTTP ao acessar {pdf_url}: {str(e)}")
            logger.error(traceback.format_exc())
            return None
        except Exception as e:
            logger.error(f"Erro ao processar PDF {pdf_url}: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def verificar_conteudo_contabil(self, conteudo):
        sample = conteudo[:5000]  # Verifica o início (cabeçalho)
        if any(termo.lower() in sample.decode('utf-8', errors='ignore').lower() 
            for termo in self.termos_contabeis):
            return True
        
        # Verifica o final (assinaturas/seções importantes)
        sample = conteudo[-10000:]
        return any(termo.lower() in sample.decode('utf-8', errors='ignore').lower() 
                for termo in self.termos_contabeis)

    def gerar_nome_arquivo(self, pdf_url, data_referencia):
        """Gera um nome de arquivo consistente para o PDF"""
        nome_base = pdf_url.split('/')[-1].split('?')[0]
        if not nome_base.lower().endswith('.pdf'):
            nome_base += '.pdf'
            
        data_str = data_referencia.strftime("%Y-%m-%d")
        if data_str not in nome_base:
            nome_base = f"{data_str}_{nome_base}"
            
        return nome_base

    def gerar_datas_no_intervalo(self, data_inicio, data_fim):
        """Gera todas as datas no intervalo especificado"""
        delta = data_fim - data_inicio
        return [data_inicio + timedelta(days=i) for i in range(delta.days + 1)]

    def construir_url_por_data(self, data):
        """Constrói a URL completa para uma data específica"""
        data_formatada = data.strftime("%Y-%m-%d")
        return f"{self.BASE_URL}?data={data_formatada}"

    def extrair_links_pdf(self, driver, url): 
        try:
            logger.info(f"Acessando URL para extrair PDFs: {url}")
            driver.get(url)

            # Espera até que pelo menos 1 link PDF esteja presente na página
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

        except Exception as e:
            logger.error(f"Erro ao extrair links PDF de {url}: {str(e)}", exc_info=True)
            return []

    def extrair_norma(self, texto):
        padrao = r'(?i)(lei complementar|lc|lei|decreto[\- ]?lei|decreto|ato normativo|portaria)[\s:]*(n[º°o.]?\s*)?(\d+[\.,\/]?\d*)'
        match = re.search(padrao, texto)
        if match:
            tipo = match.group(1).upper()
            numero = match.group(3).replace('.', '').replace(',', '')
            return tipo, numero
        return None, None
    

