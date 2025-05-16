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
                b'icms',
                b'decreto 21.866',
                b'decreto 21866',
                b'unatri',
                b'unifis',
                b'lei 4.257',
                b'ato normativo 25/21',
                b'ato normativo 26/21', 
                b'ato normativo 27/21',
                b'secretaria de fazenda',
                b'sefaz-pi',
                b'sefaz',
                b'substitui\xc3\xa7\xc3\xa3o tribut\xc3\xa1ria',
                b'st',
                b'regime especial'
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
        """Inicia a coleta de documentos contábeis"""
        logger.info("Iniciando coleta do Diário Oficial")
        
        # Ajusta o intervalo de datas padrão para 30 dias
        if data_inicio is None:
            data_inicio = datetime.now() - timedelta(days=30)
        if data_fim is None:
            data_fim = datetime.now()
            
        try:
            driver = self.configurar_navegador()
            datas = self.gerar_datas_no_intervalo(data_inicio, data_fim)
            documentos_coletados = []
            
            for data in datas:
                logger.info(f"Processando diário de {data.strftime('%d/%m/%Y')}")
                url = self.construir_url_por_data(data)
                
                try:
                    pdf_links = self.extrair_links_pdf(driver, url)
                    if not pdf_links:
                        logger.warning(f"Nenhum PDF encontrado para {data.strftime('%d/%m/%Y')}")
                        continue
                        
                    for link in pdf_links[:self.max_docs]:
                        pdf_url = self.normalizar_url(link)
                        logger.info(f"Processando PDF: {pdf_url}")
                        
                        documento = self.processar_pdf(pdf_url, data)
                        if documento:
                            documentos_coletados.append(documento)
                            logger.info(f"Documento contábil encontrado e salvo: {documento.titulo}")
                            
                    time.sleep(1)  # Intervalo entre requisições
                    
                except Exception as e:
                    logger.error(f"Erro ao processar data {data.strftime('%d/%m/%Y')}: {str(e)}")
                    continue
                    
            return documentos_coletados
            
        except Exception as e:
            logger.error(f"Falha na coleta: {str(e)}", exc_info=True)
            return []
        finally:
            if 'driver' in locals():
                driver.quit()

    def normalizar_url(self, link):
        """Normaliza a URL do PDF"""
        if link.startswith('http'):
            return link
        return self.BASE_URL + link.lstrip('/')

    def processar_pdf(self, pdf_url, data_referencia):
        """Processa um PDF individual e verifica se é contábil"""
        try:
            response = self.session.get(pdf_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Verificação inicial de conteúdo contábil
            conteudo = response.content
            if not self.verificar_conteudo_contabil(conteudo):
                logger.info(f"PDF não contém termos contábeis relevantes: {pdf_url}")
                return None
            
            # Salva o documento
            nome_arquivo = self.gerar_nome_arquivo(pdf_url, data_referencia)
            titulo = f"Diário Oficial - {data_referencia.strftime('%d/%m/%Y')}"
            
            documento = Documento(
                titulo=titulo,
                data_publicacao=data_referencia,
                url_original=pdf_url,
                data_coleta=timezone.now(),
                relevante_contabil=True  # Marca como contábil desde o início
            )
            
            documento.arquivo_pdf.save(nome_arquivo, ContentFile(conteudo), save=True)
            return documento
            
        except Exception as e:
            logger.error(f"Erro ao processar PDF {pdf_url}: {str(e)}")
            return None

    def verificar_conteudo_contabil(self, conteudo):
        """Verifica se o conteúdo do PDF é relevante para contabilidade"""
        # Verifica os primeiros 20KB do PDF (onde geralmente está o índice/sumário)
        sample = conteudo[:20000]
        
        # Verifica cada termo contábil
        for termo in self.termos_contabeis:
            if termo in sample.lower():
                return True
                
        # Se não encontrou nos primeiros 20KB, verifica uma amostra do meio
        if len(conteudo) > 50000:
            sample = conteudo[25000:45000]
            for termo in self.termos_contabeis:
                if termo in sample.lower():
                    return True
                    
        return False

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
        """Extrai todos os links de PDFs de uma página específica"""
        try:
            logger.debug(f"Acessando URL: {url}")
            driver.get(url)
            
            # Aguarda até que os links de PDF estejam presentes
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='.pdf']"))
            )
            
            # Extrai todos os links PDF da página
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            links = [a['href'] for a in soup.find_all('a', href=lambda href: href and '.pdf' in href)]
            
            logger.debug(f"Encontrados {len(links)} links PDF na página")
            return links
            
        except Exception as e:
            logger.error(f"Erro ao extrair links de {url}: {str(e)}")
            return []