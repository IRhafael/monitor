from bs4 import BeautifulSoup
import requests
from datetime import datetime
import logging
from django.core.files.base import ContentFile
from monitor.models import Documento

logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    def __init__(self, max_docs=5):
        self.url_base = "https://www.diario.pi.gov.br/doe/"
        self.max_docs = max_docs
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def iniciar_coleta(self):
        logger.info("Iniciando coleta do Diário Oficial")
        try:
            pdfs_encontrados = self.buscar_links_pdfs()
            
            if not pdfs_encontrados:
                logger.warning("Nenhum PDF encontrado")
                return []
                
            logger.info(f"Encontrados {len(pdfs_encontrados)} PDFs")
            return self.baixar_pdfs(pdfs_encontrados)
            
        except Exception as e:
            logger.error(f"Falha na coleta: {str(e)}", exc_info=True)
            return []

    def buscar_links_pdfs(self):
        logger.info("Buscando links de PDFs na página principal")
        
        try:
            response = self.session.get(self.url_base, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            pdf_links = []
            
            # Busca os links para os PDFs diretamente na página
            containers = soup.find_all('div', class_='item-edicao')  # Ajuste conforme a estrutura do site
            
            for container in containers:
                date_element = container.find('span', class_='edicao-data')  # Ajuste conforme o site
                link_element = container.find('a', href=True)
                
                if not link_element:
                    continue
                
                href = link_element['href']
                if not href.lower().endswith('.pdf'):
                    continue
                
                # Extrai a data da edição
                data_edicao = datetime.now().date()  # Padrão caso não encontre a data
                if date_element:
                    try:
                        data_texto = date_element.get_text().strip()
                        data_edicao = datetime.strptime(data_texto, '%d/%m/%Y').date()
                    except ValueError:
                        pass
                
                # Constrói a URL completa
                pdf_url = href if href.startswith('http') else self.url_base + href.lstrip('/')

                # Extrai o título
                titulo = f"Diário Oficial - {data_edicao.strftime('%d/%m/%Y')}"
                if link_element.get_text().strip():
                    titulo = link_element.get_text().strip()
                
                pdf_links.append({
                    'url': pdf_url,
                    'titulo': titulo,
                    'data': data_edicao
                })
            
            return pdf_links[:self.max_docs]
            
        except Exception as e:
            logger.error(f"Erro ao buscar PDFs: {str(e)}")
            return []

    def baixar_pdfs(self, pdfs_encontrados):
        documentos_baixados = []

        for i, pdf in enumerate(pdfs_encontrados):
            try:
                logger.info(f"Baixando PDF {i+1}/{len(pdfs_encontrados)}: {pdf['url']}")
                response = self.session.get(pdf['url'], stream=True, timeout=30)

                if response.status_code != 200:
                    logger.warning(f"Falha ao baixar PDF: {pdf['url']} - Status: {response.status_code}")
                    continue

                filename = f"doe_{pdf['data'].strftime('%Y%m%d')}_{i}.pdf"

                documento = Documento(
                    titulo=pdf['titulo'],
                    data_publicacao=pdf['data'],
                    url_original=pdf['url'],
                    data_coleta=datetime.now()
                )

                documento.arquivo_pdf.save(filename, ContentFile(response.content), save=True)
                documentos_baixados.append(documento)
                logger.info(f"PDF baixado com sucesso: {filename}")

            except Exception as e:
                logger.error(f"Erro ao baixar PDF {pdf['url']}: {str(e)}")

        return documentos_baixados
