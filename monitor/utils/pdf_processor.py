# monitor/utils/pdf_processor.py
import os
import re
import logging
import traceback
from io import StringIO
from typing import Tuple, List, Dict, Optional
from datetime import datetime
import spacy
from spacy.matcher import Matcher
from spacy.language import Language
import PyPDF2
from pdfminer.high_level import extract_text as extract_text_to_fp
from pdfminer.layout import LAParams
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from monitor.models import Documento, NormaVigente

logger = logging.getLogger(__name__)

@Language.component("norma_matcher")
def norma_matcher_component(doc):
    """Componente de pipeline spaCy para identificar normas"""
    return doc

class PDFProcessor:
    def __init__(self):
        self._setup_spacy()
        #self._setup_patterns()
        self.limite_relevancia = 4
        self.max_retries = 3
        self.timeout = 30

    def _setup_spacy(self):
        """Configura o pipeline NLP com spaCy"""
        try:
            self.nlp = spacy.load("pt_core_news_sm")
            
            # Configurar matchers
            self._configure_matchers()
            
        except Exception as e:
            logger.error(f"Falha ao configurar spaCy: {str(e)}")
            raise

    def _configure_matchers(self):
        """Padrões atualizados para capturar números completos"""
        self.norma_matcher = Matcher(self.nlp.vocab)
        
        patterns = [
            # Padrão para Leis (ex: Lei nº 8.558/2024)
            [
                {"TEXT": {"REGEX": r"[Ll]ei"}},
                {"TEXT": {"REGEX": r"n?[º°]?"}, "OP": "?"},
                {"TEXT": {"REGEX": r"\d+[\.\/-]?\d*[\/-]?\d*"}}
            ],
            # Padrão para Decretos (ex: Decreto nº 21.866/2023)
            [
                {"TEXT": {"REGEX": r"[Dd]ecreto"}},
                {"TEXT": {"REGEX": r"n?[º°]?"}, "OP": "?"},
                {"TEXT": {"REGEX": r"\d+[\.\/-]?\d*[\/-]?\d*"}}
            ]
        ]
        
        for i, pattern in enumerate(patterns):
            self.norma_matcher.add(f"NORMA_{i}", [pattern])

    def processar_documento(self, documento: Documento) -> bool:
        """Versão corrigida do processamento"""
        try:
            if not documento or not documento.arquivo_pdf:
                logger.warning("Documento inválido ou sem arquivo PDF")
                return False

            # Verificação adicional do arquivo
            if not os.path.exists(documento.arquivo_pdf.path):
                logger.error(f"Arquivo não encontrado: {documento.arquivo_pdf.path}")
                return False

            texto = self._extrair_texto_com_fallback(documento.arquivo_pdf.path)
            if not texto or len(texto.strip()) < 50:
                logger.warning("Texto vazio ou muito pequeno")
                return False

            relevante, detalhes = self.analisar_relevancia(texto)
            if not relevante:
                logger.info(f"Documento ID {documento.id} não é relevante")
                documento.delete()  # Deleta corretamente
                return False

            return self._processar_documento_relevante(documento, texto, detalhes)

        except Exception as e:
            logger.error(f"Erro ao processar documento: {str(e)}")
            return False

    def _validar_documento(self, documento: Documento) -> bool:
        """Valida o documento antes do processamento"""
        if not documento.arquivo_pdf:
            logger.warning("Documento sem arquivo PDF associado")
            return False

        try:
            if not os.path.exists(documento.arquivo_pdf.path):
                logger.warning(f"Arquivo PDF não encontrado: {documento.arquivo_pdf.path}")
                return False
                
            if os.path.getsize(documento.arquivo_pdf.path) == 0:
                logger.warning("Arquivo PDF vazio")
                return False
                
            return True
            
        except (SuspiciousFileOperation, OSError) as e:
            logger.error(f"Erro ao validar arquivo: {str(e)}")
            return False

    def _extrair_com_pypdf2(self, caminho_pdf: str) -> str:
        """Extrai texto usando PyPDF2"""
        texto = ""
        try:
            with open(caminho_pdf, 'rb') as f:
                leitor = PyPDF2.PdfReader(f)
                for pagina in leitor.pages:
                    texto += pagina.extract_text() or ""
            return self._limpar_texto(texto)
        except Exception as e:
            logger.warning(f"Erro no PyPDF2: {str(e)}")
            return None

    def _extrair_com_pdfminer(self, caminho_pdf: str) -> str:
        """Extrai texto usando pdfminer.six"""
        try:
            output = StringIO()
            with open(caminho_pdf, 'rb') as f:
                extract_text_to_fp(
                    f,
                    output,
                    laparams=LAParams(),
                    output_type='text',
                    codec='utf-8'
                )
            return self._limpar_texto(output.getvalue())
        except Exception as e:
            logger.warning(f"Falha no pdfminer: {str(e)}")
            return None

    def _extrair_texto_com_fallback(self, caminho_pdf: str) -> Optional[str]:
        """Extrai texto com múltiplas estratégias de fallback"""
        strategies = [
            self._extrair_com_pypdf2,
            self._extrair_com_pdfminer
        ]
        
        for strategy in strategies:
            try:
                texto = strategy(caminho_pdf)
                if texto and len(texto.strip()) > 100:
                    return texto
            except Exception as e:
                logger.warning(f"Falha na estratégia {strategy.__name__}: {str(e)}")
                continue
                
        return None

    def _limpar_texto(self, texto):
        """Melhoria na limpeza do texto"""
        # Preserva quebras de linha entre artigos
        texto = re.sub(r'(Art\. \d+º)', r'\n\1', texto)
        # Corrige junções indevidas
        texto = re.sub(r'([a-z])([A-Z])', r'\1 \2', texto)
        return texto

    def analisar_relevancia(self, texto: str) -> Tuple[bool, Dict]:
        """Versão atualizada para usar termos do banco de dados"""
        from monitor.models import TermoMonitorado
        
        if not texto:
            return False, {}
            
        doc = self.nlp(texto.lower())
        detalhes = {
            'pontuacao': 0,
            'termos': {},
            'normas': self._extrair_normas_com_spacy(doc)  # Adiciona as normas encontradas
        }

        
        # Carrega termos ativos do banco de dados
        termos_monitorados = TermoMonitorado.objects.filter(ativo=True)
        
        for termo_obj in termos_monitorados:
            try:
                if termo_obj.tipo == 'TEXTO':
                    if termo_obj.termo.lower() in texto.lower():
                        detalhes['termos'][termo_obj.termo] = detalhes['termos'].get(termo_obj.termo, 0) + 1
                        detalhes['pontuacao'] += 3
                        
                elif termo_obj.tipo == 'NORMA':
                    normas = self._extrair_normas_especificas(texto, termo_obj.termo)
                    detalhes['normas'].extend(normas)
                    detalhes['pontuacao'] += len(normas) * 2
            except Exception as e:
                print(f"Erro ao processar termo {termo_obj}: {str(e)}")
                continue
        
        relevante = detalhes['pontuacao'] >= self.limite_relevancia
        return relevante, detalhes

    def _extrair_normas_com_spacy(self, doc) -> List[Tuple[str, str]]:
        """Versão com logs detalhados"""
        matches = self.norma_matcher(doc)
        normas = []
        
        for match_id, start, end in matches:
            span = doc[start:end].text
            print(f"Match encontrado: {span}")  # Log
            
            tipo = self._determinar_tipo_norma(span)
            numero = self._extrair_numero_norma(span)
            
            if tipo and numero:
                print(f"Norma identificada: {tipo} {numero}")  # Log
                normas.append((tipo, numero))
        
        return normas

    def _determinar_tipo_norma(self, texto: str) -> str:
        """Determina o tipo da norma"""
        texto = texto.lower()
        
        if "lei complementar" in texto:
            return "LC"
        elif "medida provisória" in texto:
            return "MP"
        elif "portaria" in texto:
            return "PORTARIA"
        elif "decreto" in texto:
            return "DECRETO"
        elif "lei" in texto:
            return "LEI"
        return None

    def _extrair_numero_norma(self, texto: str) -> str:
        """Extrai o número completo da norma com validação"""
        # Padrão para capturar números válidos (ex: 8.558/2024, 21.866, 25/2021)
        match = re.search(r'(\d{1,4}[\.\/-]\d{1,4}(?:[\/-]\d{2,4})?', texto)
        if not match:
            return None
            
        numero = match.group(1)
        # Validação adicional - deve ter pelo menos 3 dígitos no total
        if len(re.sub(r'[^\d]', '', numero)) < 3:
            return None
            
        # Padronização
        if '/' in numero:  # Se tem ano, remove pontos
            return numero.replace('.', '')
        return numero

    def _processar_documento_relevante(self, documento, texto, detalhes):
        try:
            documento.texto_completo = texto
            documento.resumo = self._gerar_resumo(texto, detalhes)
            documento.relevante_contabil = True
            documento.processado = True

            # Adicione este log para debug
            normas_encontradas = detalhes.get('normas', [])
            print(f"Normas encontradas no texto: {normas_encontradas}")
            
            for tipo, numero in normas_encontradas:
                print(f"Processando norma: {tipo} {numero}")  # Log adicional
                norma, _ = NormaVigente.objects.get_or_create(
                    tipo=tipo,
                    numero=numero,  # Note que é 'numero' aqui também
                    defaults={'situacao': 'A VERIFICAR'}
                )
                documento.normas_relacionadas.add(norma)

            documento.save()
            return True
        except Exception as e:
            print(f"Erro ao processar documento: {str(e)}")  # Log de erro
            return False


    def _gerar_resumo(self, texto: str, detalhes: Dict) -> str:
        """Gera um resumo simplificado do documento"""
        # Extrai as primeiras frases relevantes
        doc = self.nlp(texto)
        frases_relevantes = []
        
        for sent in doc.sents:
            if len(frases_relevantes) >= 3:
                break
            if any(termo in sent.text.lower() for termo in detalhes['termos']):
                frases_relevantes.append(sent.text.strip())
        
        # Monta o resumo
        partes = []
        if detalhes.get('normas'):
            normas_str = ", ".join(f"{tipo} {numero}" for tipo, numero in detalhes['normas'][:3])
            partes.append(f"Normas mencionadas: {normas_str}")
        
        if frases_relevantes:
            partes.append("Trechos relevantes:\n- " + "\n- ".join(frases_relevantes))
        
        return "\n\n".join(partes) if partes else "Resumo não disponível"

    def _handle_documento_nao_relevante(self, documento: Documento):
        """Lida com documentos não relevantes conforme configuração"""
        try:
            if getattr(settings, 'REMOVER_NAO_RELEVANTES', False):
                documento.delete()
                logger.info(f"Documento ID {documento.id} removido por irrelevância")
            else:
                documento.arquivo_pdf.delete(save=False)
                documento.arquivo_removido = True
                documento.save()
                logger.info(f"Arquivo do documento ID {documento.id} removido")
        except Exception as e:
            logger.error(f"Falha ao lidar com documento não relevante ID {documento.id}: {str(e)}")

    def processar_todos_documentos(self) -> Dict[str, int]:
        """Processa todos os documentos não processados"""
        docs = Documento.objects.filter(processado=False)
        logger.info(f"Iniciando processamento em lote de {docs.count()} documentos")
        
        resultados = {
            'total': docs.count(),
            'sucesso': 0,
            'irrelevantes': 0,
            'falhas': 0
        }
        
        for doc in docs:
            try:
                if self.processar_documento(doc):
                    resultados['sucesso'] += 1
                else:
                    resultados['irrelevantes'] += 1
            except Exception as e:
                resultados['falhas'] += 1
                logger.error(f"Falha no documento ID {doc.id}: {str(e)}")
        
        logger.info(
            f"Processamento concluído: "
            f"{resultados['sucesso']} sucessos, "
            f"{resultados['irrelevantes']} irrelevantes, "
            f"{resultados['falhas']} falhas"
        )
        return resultados
    
    
    def _inferir_tipo_norma(self, texto: str) -> str:
        texto = texto.lower()
        if "lei complementar" in texto:
            return "LC"
        elif "medida provisória" in texto:
            return "MP"
        elif "portaria" in texto:
            return "PORTARIA"
        elif "decreto" in texto:
            return "DECRETO"
        elif "lei" in texto:
            return "LEI"
        elif "ato normativo" in texto:
            return "ATO NORMATIVO"
        return "OUTRO"
    

    def _padronizar_numero_norma(self, numero: str) -> str:
        """Padroniza o formato do número da norma, preservando pontos, barras e hífens"""
        if not numero:
            return None
        # Remove espaços em branco extras
        numero = numero.strip()
        # Permite dígitos, pontos, barras, hífens
        numero = re.sub(r'[^0-9./-]', '', numero)
        # Remove zeros à esquerda de cada segmento numérico separado por / ou -
        partes = re.split(r'([./-])', numero)  # mantém separadores
        resultado = []
        for parte in partes:
            if parte in ['.', '/', '-']:
                resultado.append(parte)
            else:
                # Remove zeros à esquerda e mantém '0' se ficar vazio
                resultado.append(parte.lstrip('0') or '0')
        return ''.join(resultado)

    def _extrair_normas_especificas(self, texto: str, padrao_norma: str) -> List[Tuple[str, str]]:
        """Extrai normas específicas baseadas nos termos monitorados, capturando número completo"""
        normas = []
        tipo = None
        
        # Tenta extrair o tipo (ex: LEI, DECRETO, ATO NORMATIVO)
        tipo_match = re.match(r'^([A-ZÁÉÍÓÚÃÕÇ\s]+)', padrao_norma, re.IGNORECASE)
        if tipo_match:
            tipo = tipo_match.group(1).strip().upper()
            tipo = self._determinar_tipo_norma(tipo) or tipo
        
        # Regex melhorada para capturar número completo, incluindo pontos e barras
        numero_match = re.search(r'(\d{1,5}(?:[./-]\d{1,5})*)', padrao_norma)
        if numero_match:
            numero_raw = numero_match.group(1)
            numero = self._padronizar_numero_norma(numero_raw)
            if tipo and numero and (tipo, numero) not in normas:
                normas.append((tipo, numero))
        
        return normas

