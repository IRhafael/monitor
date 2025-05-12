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
import nltk
nltk.download('punkt')
nltk.download('punkt_tab')

logger = logging.getLogger(__name__)

# pdf_processor.py
class PDFProcessor:
    def __init__(self):
        self._baixar_recursos_nltk()
        # Padrões relevantes para contabilidade
        self.padroes_contabeis = [
            r'tribut[aá]r[ií]a',
            r'imposto',
            r'icms',
            r'ipi',
            r'iss',
            r'receita federal',
            r'declaração',
            r'fiscal',
            r'cont[aá]bil',
            r'escrituração',
            r'lucro real',
            r'lucro presumido',
            r'simples nacional',
            r'mei',
            r'darf',
            r'efd',
            r'sped',
            r'certidão negativa',
            r'dívida ativa',
            r'crédito tributário',
            r'compensação',
            r'parcelamento',
            r'auto de infração',
            r'debito fiscal'
        ]
        
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

    def _baixar_recursos_nltk(self):
        """Garante que todos os recursos do NLTK estão disponíveis"""
        try:
            nltk.data.find('tokenizers/punkt')
            nltk.data.find('tokenizers/punkt_tab/portuguese')
        except LookupError:
            nltk.download('punkt')
            nltk.download('punkt_tab')
            # Para português, pode ser necessário baixar recursos adicionais
            nltk.download('stopwords')

        
    def is_contabil(self, texto):
        """Verifica se o documento é relevante para contabilidade"""
        if not texto:
            return False
            
        texto = texto.lower()
        for padrao in self.padroes_contabeis:
            if re.search(padrao, texto, re.IGNORECASE):
                return True
        return False

    def processar_documento(self, documento):
        """
        Processa o documento fornecido e marca como processado.
        """
        logger.info(f"Iniciando processamento do documento ID {documento.id}")

        try:
            # Obter texto do documento (considerando que o arquivo está no caminho do modelo)
            texto = self.extrair_texto_pdf(documento.arquivo_pdf.path)
            if texto and self.is_contabil(texto):
                resumo = self.gerar_resumo_contabil(texto)
                documento.resumo = resumo
                documento.processado = True
                documento.save()
                logger.info(f"Documento ID {documento.id} processado com sucesso")
                return True
            else:
                logger.warning(f"Documento ID {documento.id} não relevante ou sem conteúdo")
                return False
        except Exception as e:
            logger.error(f"Erro ao processar documento {documento.id}: {str(e)}", exc_info=True)
            return False

    def extrair_texto_pdf(self, caminho_pdf):
        """Extrai o texto de um arquivo PDF"""
        try:
            with open(caminho_pdf, 'rb') as f:
                leitor = PyPDF2.PdfReader(f)
                texto = ""
                for pagina in leitor.pages:
                    texto += pagina.extract_text()
                return texto
        except Exception as e:
            logger.error(f"Erro ao extrair texto do PDF {caminho_pdf}: {str(e)}")
            return ""

    def gerar_resumo_contabil(self, texto):
        """Gera um resumo focado em informações contábeis com melhor contextualização"""
        if not texto or len(texto.strip()) < 50:
            return "Documento sem conteúdo textual relevante."
        
        try:
            # Pré-processamento do texto
            texto = self._limpar_texto(texto)
            
            # Divisão em parágrafos (melhor que frases para contexto)
            paragrafos = [p for p in texto.split('\n') if p.strip()]
            
            # Selecionar parágrafos mais relevantes
            paragrafos_relevantes = []
            for p in paragrafos:
                relevancia = self._calcular_relevancia_paragrafo(p)
                if relevancia > 0:
                    paragrafos_relevantes.append((relevancia, p))
            
            # Ordenar por relevância e selecionar os melhores
            paragrafos_relevantes.sort(reverse=True, key=lambda x: x[0])
            melhores_paragrafos = [p for (_, p) in paragrafos_relevantes[:3]]
            
            # Se não encontrou parágrafos relevantes, usar abordagem alternativa
            if not melhores_paragrafos:
                return self._gerar_resumo_fallback(texto)
            
            # Pós-processamento para melhor coerência
            resumo = self._pos_processar_resumo(melhores_paragrafos)
            return resumo
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {str(e)}")
            return "Erro ao gerar resumo do documento."

    def _limpar_texto(self, texto):
        """Remove formatação e caracteres especiais"""
        texto = re.sub(r'\s+', ' ', texto)  # Remove múltiplos espaços
        texto = re.sub(r'-\n', '', texto)  # Junta palavras quebradas
        return texto.strip()

    def _calcular_relevancia_paragrafo(self, paragrafo):
        """Calcula a relevância de um parágrafo para contabilidade"""
        pontos = 0
        
        # Verifica padrões contábeis
        for padrao in self.padroes_contabeis:
            if re.search(padrao, paragrafo, re.IGNORECASE):
                pontos += 2
        
        # Verifica menções a normas
        normas = self.extrair_normas_do_texto(paragrafo)
        pontos += len(normas)
        
        # Penaliza parágrafos muito curtos
        if len(paragrafo) < 100:
            pontos -= 1
        
        return pontos

    def _gerar_resumo_fallback(self, texto):
        """Método alternativo quando não encontra parágrafos relevantes"""
        # Usa as primeiras linhas que contenham termos contábeis
        linhas_relevantes = []
        for linha in texto.split('\n'):
            if len(linhas_relevantes) >= 3:
                break
            if any(re.search(padrao, linha, re.IGNORECASE) for padrao in self.padroes_contabeis):
                linhas_relevantes.append(linha[:300])  # Limita o tamanho
        
        if linhas_relevantes:
            return " | ".join(linhas_relevantes)
        return "Documento contém informações contábeis não estruturadas."

    def _pos_processar_resumo(self, paragrafos):
        """Melhora a formatação do resumo final"""
        resumo = "\n\n".join(paragrafos)
        
        # Remove múltiplas quebras de linha
        resumo = re.sub(r'\n{3,}', '\n\n', resumo)
        
        # Limita o tamanho total
        if len(resumo) > 1500:
            resumo = resumo[:1500] + "... [continua]"
        
        return resumo
        
    def processar_todos_documentos(self):
        """Processa todos os documentos não processados no banco de dados"""
        documentos = Documento.objects.filter(processado=False)
        logger.info(f"Iniciando processamento de {documentos.count()} documentos")
        
        for documento in documentos:
            try:
                logger.info(f"Processando documento ID {documento.id} - {documento.titulo}")
                
                # Verifica se o arquivo existe
                if not documento.arquivo_pdf:
                    logger.warning(f"Documento ID {documento.id} não tem arquivo PDF associado")
                    continue
                    
                if not os.path.exists(documento.arquivo_pdf.path):
                    logger.warning(f"Arquivo PDF não encontrado no caminho: {documento.arquivo_pdf.path}")
                    continue
                    
                # Extrai texto
                texto = self.extrair_texto_pdf(documento.arquivo_pdf.path)
                if not texto:
                    logger.warning(f"Não foi possível extrair texto do documento ID {documento.id}")
                    continue
                    
                # Verifica relevância e gera resumo
                documento.relevante_contabil = self.is_contabil(texto)
                documento.texto_completo = texto
                
                if documento.relevante_contabil:
                    documento.resumo = self.gerar_resumo_contabil(texto)
                else:
                    documento.resumo = "Documento não relevante para contabilidade"
                
                documento.processado = True
                documento.save()
                logger.info(f"Documento ID {documento.id} processado com sucesso")
                
            except Exception as e:
                logger.error(f"Erro ao processar documento ID {documento.id}: {str(e)}", exc_info=True)
        
        logger.info("Processamento de documentos concluído")
        return documentos.count()
    
    def extrair_normas_do_texto(self, texto):
        # Busca por padrões como: Lei nº 5.377/2004 ou Decreto nº 15.299
        padrao = r'(Lei|Decreto|Portaria|Instrução Normativa)[^\n,.]{0,80}?n[º°]?\s?\d{1,6}[^\n,.]{0,30}'
        return re.findall(padrao, texto, re.IGNORECASE)