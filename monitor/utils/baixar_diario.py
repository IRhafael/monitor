import os
import time
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import logging

# Configurações
BASE_URL = "https://www.diario.pi.gov.br/doe/"
DOWNLOAD_DIR = "diarios_oficiais"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('diario_downloader.log'),
        logging.StreamHandler()
    ]
)

def configurar_navegador():
    """Configura e retorna uma instância do navegador Chrome em modo headless"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Configuração para downloads automáticos de PDF
    chrome_options.add_experimental_option(
        "prefs", {
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "download.default_directory": os.path.abspath(DOWNLOAD_DIR)
        }
    )
    
    return webdriver.Chrome(options=chrome_options)

def gerar_datas_no_intervalo(data_inicio, data_fim):
    """Gera todas as datas no intervalo especificado"""
    delta = data_fim - data_inicio
    return [data_inicio + timedelta(days=i) for i in range(delta.days + 1)]

def formatar_data_para_url(data):
    """Formata a data no padrão usado pela URL do site"""
    return data.strftime("%Y-%m-%d")

def construir_url_por_data(data):
    """Constrói a URL completa para uma data específica"""
    data_formatada = formatar_data_para_url(data)
    return f"{BASE_URL}?data={data_formatada}"

def extrair_links_pdf(driver, url):
    """Extrai todos os links de PDFs de uma página específica"""
    try:
        driver.get(url)
        # Espera explícita por elementos dinâmicos
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='.pdf']"))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return [a['href'] for a in soup.find_all('a', href=lambda href: href and '.pdf' in href)]
    except Exception as e:
        logging.error(f"Erro ao extrair links de {url}: {str(e)}")
        return []

def baixar_pdf(pdf_url, pasta_destino, data_referencia):
    """Baixa um arquivo PDF e salva com estrutura organizada"""
    try:
        # Criar estrutura de pastas por ano/mês
        pasta_ano = os.path.join(pasta_destino, str(data_referencia.year))
        pasta_mes = os.path.join(pasta_ano, f"{data_referencia.month:02d}")
        os.makedirs(pasta_mes, exist_ok=True)
        
        # Obter nome do arquivo
        nome_arquivo = pdf_url.split('/')[-1].split('?')[0]
        if not nome_arquivo.lower().endswith('.pdf'):
            nome_arquivo += '.pdf'
            
        # Adicionar data ao nome do arquivo se não estiver presente
        data_str = data_referencia.strftime("%Y-%m-%d")
        if data_str not in nome_arquivo:
            nome_arquivo = f"{data_str}_{nome_arquivo}"
        
        caminho_completo = os.path.join(pasta_mes, nome_arquivo)
        
        # Verificar se já existe
        if os.path.exists(caminho_completo):
            logging.info(f"Arquivo já existe: {caminho_completo}")
            return caminho_completo
            
        # Fazer download
        response = requests.get(pdf_url, stream=True, timeout=30)
        response.raise_for_status()
        
        with open(caminho_completo, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logging.info(f"Baixado com sucesso: {caminho_completo}")
        return caminho_completo
        
    except Exception as e:
        logging.error(f"Falha ao baixar {pdf_url}: {str(e)}")
        return None

def baixar_diarios_por_intervalo(data_inicio, data_fim):
    """Baixa todos os diários em um intervalo de datas"""
    driver = configurar_navegador()
    datas = gerar_datas_no_intervalo(data_inicio, data_fim)
    total_baixados = 0
    
    try:
        for data in datas:
            logging.info(f"Processando diário de {data.strftime('%d/%m/%Y')}")
            url = construir_url_por_data(data)
            links_pdf = extrair_links_pdf(driver, url)
            
            if not links_pdf:
                logging.warning(f"Nenhum PDF encontrado para {data.strftime('%d/%m/%Y')}")
                continue
                
            for link in links_pdf:
                pdf_url = link if link.startswith('http') else BASE_URL + link.lstrip('/')
                if baixar_pdf(pdf_url, DOWNLOAD_DIR, data):
                    total_baixados += 1
                    
            # Intervalo entre requisições para evitar sobrecarga
            time.sleep(2)
            
    finally:
        driver.quit()
        
    return total_baixados

if __name__ == "__main__":
    # Exemplo: baixar diários dos últimos 30 dias
    data_fim = datetime.now()
    data_inicio = data_fim - timedelta(days=5)
    
    logging.info(f"Iniciando download de diários de {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    
    total = baixar_diarios_por_intervalo(data_inicio, data_fim)
    
    logging.info(f"Processo concluído. Total de arquivos baixados: {total}")