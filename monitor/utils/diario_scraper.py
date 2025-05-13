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
from selenium.webdriver.chrome.options import Options

logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    def __init__(self, max_docs=5):
        self.BASE_URL = "https://www.diario.pi.gov.br/doe/"
        self.max_docs = max_docs
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    # diario_scraper.py
    from selenium.webdriver.chrome.options import Options

    def configurar_navegador(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--ignore-ssl-errors")
        chrome_options.add_argument("--no-sandbox")
        return webdriver.Chrome(options=chrome_options)
        


    def iniciar_coleta(self, data_inicio=None, data_fim=None):
        logger.info("Iniciando coleta do Diário Oficial")
        
        if data_inicio is None:
            data_inicio = datetime.now() - timedelta(days=5)
        if data_fim is None:
            data_fim = datetime.now()
            
        try:
            driver = self.configurar_navegador()
            datas = self.gerar_datas_no_intervalo(data_inicio, data_fim)
            documentos = []
            
            for data in datas:
                logger.info(f"Processando diário de {data.strftime('%d/%m/%Y')}")
                url = self.construir_url_por_data(data)
                pdf_links = self.extrair_links_pdf(driver, url)
                
                if not pdf_links:
                    logger.warning(f"Nenhum PDF encontrado para {data.strftime('%d/%m/%Y')}")
                    continue
                    
                for link in pdf_links[:self.max_docs]:
                    pdf_url = link if link.startswith('http') else self.BASE_URL + link.lstrip('/')
                    documento = self.baixar_e_salvar_pdf(pdf_url, data)
                    if documento:
                        documentos.append(documento)
                
                # Intervalo entre requisições para evitar sobrecarga
                time.sleep(2)
                
            return documentos
            
        except Exception as e:
            logger.error(f"Falha na coleta: {str(e)}", exc_info=True)
            return []
        finally:
            if 'driver' in locals():
                driver.quit()

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
            driver.get(url)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='.pdf']"))
            )
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            return [a['href'] for a in soup.find_all('a', href=lambda href: href and '.pdf' in href)]
        except Exception as e:
            logger.error(f"Erro ao extrair links de {url}: {str(e)}")
            return []

    def baixar_e_salvar_pdf(self, pdf_url, data_referencia):
        try:
            response = self.session.get(pdf_url, stream=True, timeout=30)
            response.raise_for_status()
                    # Verificação rápida do conteúdo antes de salvar
            if b"contabilidade" not in response.content[:5000] and b"tribut" not in response.content[:5000]:
                  logger.info(f"PDF não parece ser contábil - ignorando: {pdf_url}")
                  return None
            
            nome_arquivo = pdf_url.split('/')[-1].split('?')[0]
            if not nome_arquivo.lower().endswith('.pdf'):
                nome_arquivo += '.pdf'
                
            data_str = data_referencia.strftime("%Y-%m-%d")
            if data_str not in nome_arquivo:
                nome_arquivo = f"{data_str}_{nome_arquivo}"
            
            titulo = f"Diário Oficial - {data_referencia.strftime('%d/%m/%Y')}"
            
            documento = Documento(
                titulo=titulo,
                data_publicacao=data_referencia,
                url_original=pdf_url,
                data_coleta=timezone.now()  # Usando timezone agora
            )

            documento.arquivo_pdf.save(nome_arquivo, ContentFile(response.content), save=True)
            logger.info(f"PDF baixado e salvo: {nome_arquivo}")
            return documento
            
        except Exception as e:
            logger.error(f"Falha ao baixar {pdf_url}: {str(e)}")
            return None