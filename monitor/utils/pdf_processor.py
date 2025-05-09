# monitor/utils/pdf_processor.py
import os
import logging
import re
import PyPDF2
import nltk
from nltk.tokenize import sent_tokenize
from datetime import datetime
from django.conf import settings
from monitor.models import Documento

# Baixar recursos do NLTK necessários
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

logger = logging.getLogger(__name__)

class PDFProcessor:
    """
    Classe responsável por processar PDFs, extrair texto e gerar resumos
    """
    
    def __init__(self):
        # Padrões relevantes para identificar no texto
        self.padroes_relevantes = [
            r'decreto n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'lei n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'portaria n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'resolução n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'nomeação',
            r'exoneração',
            r'licitação',
            r'concurso',
            r'edital',
        ]
    
    def processar_todos_documentos(self):
        """
        Processa todos os documentos não processados no banco de dados
        """
        logger.info("Iniciando processamento de documentos não processados")
        
        # Obter documentos não processados
        documentos = Documento.objects.filter(processado=False)
        
        logger.info(f"Encontrados {documentos.count()} documentos para processar")
        
        for documento in documentos:
            try:
                self.processar_documento(documento)
            except Exception as e:
                logger.error(f"Erro ao processar documento {documento.id}: {str(e)}")
        
        return documentos.count()
    
    def processar_documento(self, documento):
        """
        Processa um documento específico
        """
        logger.info(f"Processando documento: {documento.titulo}")
        
        try:
            # Verificar se o arquivo PDF existe
            if not documento.arquivo_pdf or not os.path.exists(documento.arquivo_pdf.path):
                logger.warning(f"Arquivo PDF não encontrado para o documento {documento.id}")
                return False
            
            # Extrair texto do PDF
            texto_completo = self.extrair_texto_pdf(documento.arquivo_pdf.path)
            
            # Salvar o texto completo no documento
            documento.texto_completo = texto_completo
            
            # Gerar resumo
            resumo = self.gerar_resumo(texto_completo)
            documento.resumo = resumo
            
            # Marcar como processado
            documento.processado = True
            documento.save()
            
            logger.info(f"Documento {documento.id} processado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro durante o processamento do documento {documento.id}: {str(e)}")
            return False
    
    def extrair_texto_pdf(self, caminho_pdf):
        """
        Extrai o texto de um arquivo PDF
        """
        texto_completo = ""
        
        try:
            with open(caminho_pdf, 'rb') as arquivo:
                leitor_pdf = PyPDF2.PdfReader(arquivo)
                
                # Processar cada página do PDF
                for pagina in leitor_pdf.pages:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n\n"
            
            return texto_completo
            
        except Exception as e:
            logger.error(f"Erro ao extrair texto do PDF {caminho_pdf}: {str(e)}")
            raise
    
    def gerar_resumo(self, texto):
        """
        Gera um resumo do texto usando técnicas simples de NLP
        """
        if not texto or len(texto.strip()) < 50:
            return "Documento sem conteúdo textual relevante."
        
        try:
            # Dividir o texto em frases
            frases = sent_tokenize(texto)
            
            # Limitar a análise às primeiras 30 frases para melhor desempenho
            frases_analise = frases[:30] if len(frases) > 30 else frases
            
            # Procurar por informações relevantes nas frases
            frases_relevantes = []
            
            # Primeiro ciclo: procurar por padrões específicos
            for frase in frases_analise:
                frase_limpa = frase.strip()
                if not frase_limpa or len(frase_limpa) < 20:
                    continue
                
                # Verificar se a frase contém algum dos padrões relevantes
                for padrao in self.padroes_relevantes:
                    if re.search(padrao, frase_limpa, re.IGNORECASE):
                        # Se a frase for muito longa, truncar
                        if len(frase_limpa) > 300:
                            frases_relevantes.append(frase_limpa[:300] + "...")
                        else:
                            frases_relevantes.append(frase_limpa)
                        break
            
            # Se não encontrou pelo menos 3 frases com padrões relevantes,
            # adicionar algumas das primeiras frases do documento
            if len(frases_relevantes) < 3:
                for frase in frases[:10]:  # Considerar apenas as 10 primeiras frases
                    frase_limpa = frase.strip()
                    if frase_limpa and len(frase_limpa) > 20 and frase_limpa not in frases_relevantes:
                        if len(frase_limpa) > 300:
                            frases_relevantes.append(frase_limpa[:300] + "...")
                        else:
                            frases_relevantes.append(frase_limpa)
                        
                        # Parar quando atingir pelo menos 3 frases
                        if len(frases_relevantes) >= 3:
                            break
            
            # Limitar o número total de frases no resumo
            if len(frases_relevantes) > 5:
                frases_relevantes = frases_relevantes[:5]
            
            # Se não conseguiu extrair nenhuma frase relevante
            if not frases_relevantes:
                # Usar as 3 primeiras frases que tenham tamanho razoável
                for frase in frases[:10]:
                    if len(frase.strip()) > 30:
                        if len(frase) > 300:
                            frases_relevantes.append(frase[:300] + "...")
                        else:
                            frases_relevantes.append(frase)
                    if len(frases_relevantes) >= 3:
                        break
            
            # Se ainda não tiver frases relevantes, usar um resumo padrão
            if not frases_relevantes:
                return "Documento sem conteúdo textual estruturado. Recomenda-se verificação manual."
            
            # Juntar as frases em um único texto
            resumo = " ".join(frases_relevantes)
            
            return resumo
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {str(e)}")
            return "Erro ao gerar resumo do documento."
