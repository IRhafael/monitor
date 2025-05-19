# diario_scraper.py
import os
import time
import requests
from datetime import datetime, timedelta
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import logging
from django.core.files.base import ContentFile
from monitor.models import Documento
import re

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
            driver = self.configurar_navegador()
            if not driver:
                return []
                
            datas = self.gerar_datas_no_intervalo(data_inicio, data_fim)
            documentos_coletados = []
            
            for data in datas:
                url = self.construir_url_por_data(data)
                pdf_links = self.extrair_links_pdf(driver, url)
                
                for link in pdf_links:
                    # Verifica se o link está acessível antes de processar
                    if self.verificar_link_acessivel(link):
                        documento = self.processar_pdf(link, data)
                        if documento:
                            documentos_coletados.append(documento)
                    else:
                        logger.warning(f"Link inacessível: {link}")
                        
            return documentos_coletados
            
        finally:
            if 'driver' in locals():
                driver.quit()

    def verificar_link_acessivel(self, url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = self.session.head(url, headers=headers, timeout=10)
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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = self.session.get(pdf_url, headers=headers, stream=True, timeout=60)
            response.raise_for_status()  # Lança exceção para status 4xx/5xx
            
            if not response.headers.get('Content-Type', '').lower() == 'application/pdf':
                logger.warning(f"URL não é um PDF válido: {pdf_url}")
                return None
                
            # Restante do seu código de processamento...
            
        except requests.HTTPError as e:
            logger.error(f"Erro HTTP ao acessar {pdf_url}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Erro ao processar PDF {pdf_url}: {str(e)}")
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
            driver.get(url)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "a"))
            )
            
            # Extrai todos os links e filtra apenas os PDFs válidos
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            links = []
            
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.lower().endswith('.pdf'):
                    # Normaliza a URL
                    if not href.startswith('http'):
                        href = urljoin(self.BASE_URL, href)
                    links.append(href)
            
            return list(set(links))  # Remove duplicados
            
        except Exception as e:
            logger.error(f"Erro ao extrair links de {url}: {str(e)}")
            return []
        

    def extrair_norma(texto):
        padrao = r'(?i)(lei complementar|lc|lei|decreto[\- ]?lei|decreto|ato normativo|portaria)[\s:]*(n[º°o.]?\s*)?(\d+[\.,\/]?\d*)'
        
        match = re.search(padrao, texto)
        if match:
            tipo = match.group(1).upper()
            numero = match.group(3).replace('.', '').replace(',', '')
            return tipo, numero
        return None, None
