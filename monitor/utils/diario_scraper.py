# monitor/utils/diario_scraper.py
import requests
from bs4 import BeautifulSoup
import re
import os
import logging
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
from monitor.models import Documento, LogExecucao

logger = logging.getLogger(__name__)

class DiarioOficialScraper:
    """
    Classe responsável por acessar o site do Diário Oficial do Piauí
    e extrair os documentos mais recentes.
    """
    
    def __init__(self, max_docs=5):
        self.url_base = "https://www.diario.pi.gov.br/doe/"
        self.max_docs = max_docs
        self.pdfs_encontrados = []
    
    def iniciar_coleta(self):
        """Versão com mais logs para debug"""
        logger.info("Iniciando coleta do Diário Oficial")
        try:
            self.buscar_links_pdfs()
            
            if not self.pdfs_encontrados:
                logger.warning("Nenhum PDF encontrado na página principal")
                self.buscar_links_pdfs_secundarios()
            
            if not self.pdfs_encontrados:
                logger.error("Nenhum PDF encontrado em nenhuma página")
                return []
                
            logger.info(f"Encontrados {len(self.pdfs_encontrados)} PDFs")
            return self.baixar_pdfs()
            
        except Exception as e:
            logger.error(f"Falha na coleta: {str(e)}", exc_info=True)
            return []
        
    def buscar_links_pdfs(self):
        """
        Busca links para PDFs na página principal do Diário Oficial
        """
        logger.info("Buscando links de PDFs na página principal")
        
        try:
            # Fazer requisição para a página principal
            response = requests.get(self.url_base)
            response.raise_for_status()
            
            # Parsear o HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Procurar links para PDFs
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.endswith('.pdf'):
                    # Verificar se é URL absoluta ou relativa
                    url_pdf = href if href.startswith('http') else self.url_base + href.lstrip('/')
                    
                    # Extrair texto e título do link
                    texto = link.text.strip()
                    
                    # Extrair data do nome do arquivo ou do texto do link
                    data_str = None
                    
                    # Procurar por padrões comuns de data no texto ou URL
                    data_patterns = [
                        r'(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{4})',  # dd/mm/yyyy
                        r'(\d{4})[\/\.\-](\d{1,2})[\/\.\-](\d{1,2})',  # yyyy/mm/dd
                    ]
                    
                    for pattern in data_patterns:
                        match = re.search(pattern, texto + " " + url_pdf)
                        if match:
                            try:
                                if match.group(3).startswith('20'):  # Assumindo formato dd/mm/yyyy
                                    data_str = f"{match.group(1).zfill(2)}/{match.group(2).zfill(2)}/{match.group(3)}"
                                    data = datetime.strptime(data_str, "%d/%m/%Y").date()
                                else:  # Assumindo formato yyyy/mm/dd
                                    data_str = f"{match.group(2).zfill(2)}/{match.group(3).zfill(2)}/{match.group(1)}"
                                    data = datetime.strptime(data_str, "%d/%m/%Y").date()
                                break
                            except ValueError:
                                continue
                    
                    # Se não conseguiu extrair a data, usar a data atual
                    if not data_str:
                        data = datetime.now().date()
                        data_str = data.strftime("%d/%m/%Y")
                    
                    # Verificar se o documento já existe no banco de dados
                    if not Documento.objects.filter(url_original=url_pdf).exists():
                        self.pdfs_encontrados.append({
                            'url': url_pdf,
                            'titulo': texto if texto else f"Diário Oficial do Piauí - {data_str}",
                            'data': data
                        })
            
            logger.info(f"Encontrados {len(self.pdfs_encontrados)} PDFs na página principal")
            
        except Exception as e:
            logger.error(f"Erro ao buscar links na página principal: {str(e)}")
    
    def buscar_links_pdfs_secundarios(self):
        """
        Busca links para PDFs em páginas secundárias (como "Edições Anteriores")
        """
        logger.info("Buscando links de PDFs em páginas secundárias")
        
        try:
            # Fazer requisição para a página principal
            response = requests.get(self.url_base)
            response.raise_for_status()
            
            # Parsear o HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Procurar links para edições anteriores ou arquivos
            paginas_secundarias = []
            
            for link in soup.find_all('a', href=True):
                texto = link.text.strip().lower()
                if 'ediç' in texto or 'anteriores' in texto or 'arquiv' in texto:
                    href = link['href']
                    url_secundaria = href if href.startswith('http') else self.url_base + href.lstrip('/')
                    paginas_secundarias.append(url_secundaria)
            
            # Visitar cada página secundária
            for url_secundaria in paginas_secundarias:
                try:
                    # Fazer requisição para a página secundária
                    response = requests.get(url_secundaria)
                    response.raise_for_status()
                    
                    # Parsear o HTML
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Procurar links para PDFs
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if href.endswith('.pdf'):
                            # Verificar se é URL absoluta ou relativa
                            url_pdf = href if href.startswith('http') else self.url_base + href.lstrip('/')
                            
                            # Extrair texto e título do link
                            texto = link.text.strip()
                            
                            # Extrair data do nome do arquivo ou do texto do link
                            # (lógica similar à função buscar_links_pdfs)
                            data_str = None
                            data_patterns = [
                                r'(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{4})',  # dd/mm/yyyy
                                r'(\d{4})[\/\.\-](\d{1,2})[\/\.\-](\d{1,2})',  # yyyy/mm/dd
                            ]
                            
                            for pattern in data_patterns:
                                match = re.search(pattern, texto + " " + url_pdf)
                                if match:
                                    try:
                                        if match.group(3).startswith('20'):  # Assumindo formato dd/mm/yyyy
                                            data_str = f"{match.group(1).zfill(2)}/{match.group(2).zfill(2)}/{match.group(3)}"
                                            data = datetime.strptime(data_str, "%d/%m/%Y").date()
                                        else:  # Assumindo formato yyyy/mm/dd
                                            data_str = f"{match.group(2).zfill(2)}/{match.group(3).zfill(2)}/{match.group(1)}"
                                            data = datetime.strptime(data_str, "%d/%m/%Y").date()
                                        break
                                    except ValueError:
                                        continue
                            
                            # Se não conseguiu extrair a data, usar a data atual
                            if not data_str:
                                data = datetime.now().date()
                                data_str = data.strftime("%d/%m/%Y")
                            
                            # Verificar se o documento já existe no banco de dados
                            if not Documento.objects.filter(url_original=url_pdf).exists():
                                self.pdfs_encontrados.append({
                                    'url': url_pdf,
                                    'titulo': texto if texto else f"Diário Oficial do Piauí - {data_str}",
                                    'data': data
                                })
                    
                except Exception as e:
                    logger.error(f"Erro ao acessar página secundária {url_secundaria}: {str(e)}")
            
            logger.info(f"Encontrados {len(self.pdfs_encontrados)} PDFs após busca em páginas secundárias")
            
        except Exception as e:
            logger.error(f"Erro ao buscar links em páginas secundárias: {str(e)}")
    
    def baixar_pdfs(self):
        """
        Baixa os PDFs encontrados e cria registros no banco de dados
        """
        documentos_baixados = []
        
        # Limitar ao número máximo de documentos
        pdfs_para_baixar = self.pdfs_encontrados[:self.max_docs]
        
        for i, pdf in enumerate(pdfs_para_baixar):
            try:
                logger.info(f"Baixando PDF {i+1}/{len(pdfs_para_baixar)}: {pdf['url']}")
                
                # Fazer requisição para baixar o PDF
                response = requests.get(pdf['url'])
                if response.status_code != 200:
                    logger.warning(f"Falha ao baixar PDF: {pdf['url']} - Status code: {response.status_code}")
                    continue
                
                # Extrair nome do arquivo da URL
                filename = os.path.basename(pdf['url'])
                if not filename.endswith('.pdf'):
                    filename = f"diario_oficial_{i+1}.pdf"
                
                # Criar um novo documento no banco de dados
                documento = Documento(
                    titulo=pdf['titulo'],
                    data_publicacao=pdf['data'],
                    url_original=pdf['url'],
                    data_coleta=datetime.now()
                )
                
                # Salvar o conteúdo do PDF
                documento.arquivo_pdf.save(filename, ContentFile(response.content), save=True)
                
                # Adicionar à lista de documentos baixados
                documentos_baixados.append(documento)
                
                logger.info(f"PDF baixado com sucesso: {filename}")
                
            except Exception as e:
                logger.error(f"Erro ao baixar PDF {pdf['url']}: {str(e)}")
        
        return documentos_baixados
