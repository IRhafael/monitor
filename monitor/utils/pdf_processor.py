# monitor/utils/pdf_processor.py
import os
import re
import logging
import traceback
from io import StringIO
from typing import Tuple, List, Dict, Optional
from datetime import datetime

import PyPDF2
from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams
import nltk
from nltk.tokenize import sent_tokenize
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from monitor.models import Documento, NormaVigente

logger = logging.getLogger(__name__)

class PDFProcessor:
    def __init__(self):
        self._setup_nltk()
        self._setup_patterns()
        self.limite_relevancia = 4
        self.max_retries = 3
        self.timeout = 30

    def _setup_nltk(self):
        """Configura recursos do NLTK com fallback"""
        try:
            nltk.data.find('tokenizers/punkt')
            nltk.data.find('tokenizers/punkt_tab/portuguese')
        except LookupError:
            try:
                nltk.download('punkt')
                nltk.download('punkt_tab')
                nltk.download('stopwords')
            except Exception as e:
                logger.warning(f"Falha ao baixar recursos NLTK: {str(e)}")

    def _setup_patterns(self):
        """Configura padrões de busca com pesos"""
        self.padroes_contabeis = [
            # Impostos e obrigações (alto peso)
            (r'\b(icms|ipi|iss|pis|cofins|csll|irpj)\b', 3),
            (r'\b(sped|efd|dctf|dirf|DAS|darf)\b', 3),
            # Termos gerais (médio peso)
            (r'tribut[aá]r[ií][ao]|fiscaliza[cç][aã]o', 2),
            (r'receita\s+federal|sefaz|fazenda\s+nacional', 2),
            # Conceitos contábeis (baixo peso)
            (r'balan[cç]o\s+patrimonial|demonstra[cç][oõ]es\s+financeiras', 1)
        ]

        self.padroes_normas = [
            r'(?i)(Lei|Decreto|Portarias da SEFAZ |Instrução NormativaConvênios e Protocolos do CONFAZ|Resolução)\s+(?:n?[º°]?\s*)?(\d+[\.\/-]?\d*)',
            r'(?i)(Lei Complementar)\s+(n?[º°]?\s*)?(\d+)',
            r'(?i)(Medida Provisória)\s+(n?[º°]?\s*)?(\d+)'
        ]

    @transaction.atomic
    def processar_documento(self, documento: Documento) -> bool:
        """Processa um documento com tratamento robusto de erros"""
        logger.info(f"Iniciando processamento do documento ID {documento.id}")
        
        try:
            if not self._validar_documento(documento):
                return False

            texto = self._extrair_texto_com_fallback(documento.arquivo_pdf.path)
            if not texto:
                logger.error(f"Falha ao extrair texto do documento ID {documento.id}")
                return False

            relevante, detalhes = self.analisar_relevancia(texto)
            if not relevante:
                logger.info(f"Documento ID {documento.id} não é relevante")
                self._handle_documento_nao_relevante(documento)
                return False

            return self._processar_documento_relevante(documento, texto, detalhes)

        except Exception as e:
            logger.error(f"Erro crítico ao processar documento ID {documento.id}: {str(e)}\n{traceback.format_exc()}")
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
        with open(caminho_pdf, 'rb') as f:
            leitor = PyPDF2.PdfReader(f)
            for pagina in leitor.pages:
                texto += pagina.extract_text() or ""
        return self._limpar_texto(texto)

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

    def _extrair_com_fallback_alternativo(self, caminho_pdf: str) -> str:
        """Método alternativo para extração de texto - versão simplificada"""
        try:
            # Tenta ler como texto puro (para PDFs que são na verdade arquivos de texto)
            with open(caminho_pdf, 'r', encoding='utf-8', errors='ignore') as f:
                texto = f.read(5000)  # Lê apenas os primeiros 5KB para verificação
                if "PDF" not in texto[:20]:  # Se não parece ser um PDF binário
                    return self._limpar_texto(texto)
        except:
            pass
            
        return None

    def _extrair_texto_com_fallback(self, caminho_pdf: str) -> Optional[str]:
        """Extrai texto com múltiplas estratégias de fallback"""
        strategies = [
            self._extrair_com_pypdf2,
            self._extrair_com_pdfminer,
            self._extrair_com_fallback_alternativo
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

    def _limpar_texto(self, texto: str) -> str:
        """Normaliza o texto extraído"""
        if not texto:
            return ""
            
        texto = re.sub(r'\s+', ' ', texto)
        texto = re.sub(r'-\n', '', texto)
        texto = re.sub(r'[^\w\sáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ.,;:!?()\-º°%$]', '', texto)
        return texto.strip()

    def analisar_relevancia(self, texto: str) -> Tuple[bool, Dict]:
        """Analisa a relevância contábil com pontuação detalhada"""
        if not texto:
            return False, {}
            
        texto = texto.lower()
        detalhes = {
            'pontuacao': 0,
            'termos': {},
            'normas': []
        }

        for padrao, peso in self.padroes_contabeis:
            matches = re.findall(padrao, texto)
            if matches:
                termo = matches[0] if isinstance(matches[0], str) else matches[0][0]
                detalhes['termos'][termo] = detalhes['termos'].get(termo, 0) + len(matches)
                detalhes['pontuacao'] += peso * len(matches)

        normas = self.extrair_normas(texto)
        detalhes['normas'] = normas
        detalhes['pontuacao'] += len(normas) * 2

        relevante = detalhes['pontuacao'] >= self.limite_relevancia
        return relevante, detalhes

    def extrair_normas(self, texto: str) -> List[Tuple[str, str]]:
        """Extrai normas com validação rigorosa"""
        normas = []
        for padrao in self.padroes_normas:
            for match in re.finditer(padrao, texto, re.IGNORECASE):
                try:
                    tipo = self._normalizar_tipo_norma(match.group(1))
                    numero = self._normalizar_numero_norma(match.group(2))
                    if tipo and numero:
                        normas.append((tipo, numero))
                except (IndexError, AttributeError):
                    continue
                    
        seen = set()
        return [n for n in normas if not (n in seen or seen.add(n))]

    def _normalizar_tipo_norma(self, tipo: str) -> str:
        """Normaliza o tipo de norma"""
        if not tipo:
            return ""
            
        tipo = tipo.upper().strip()
        mapeamento = {
            'LEI COMPLEMENTAR': 'LC',
            'MEDIDA PROVISÓRIA': 'MP',
            'INSTRUÇÃO NORMATIVA': 'IN',
            'RESOLUÇÃO': 'RES'
        }
        return mapeamento.get(tipo, tipo.split()[0])

    def _normalizar_numero_norma(self, numero: str) -> str:
        """Normaliza o número da norma"""
        if not numero:
            return ""
            
        numero = re.sub(r'[^\d\/]', '', numero)
        return numero.strip()

    def _processar_documento_relevante(self, documento: Documento, texto: str, detalhes: Dict) -> bool:
        """Processa um documento considerado relevante"""
        try:
            documento.texto_completo = texto
            documento.resumo = self._gerar_resumo(texto, detalhes)
            documento.relevante_contabil = True
            documento.processado = True
            
            for tipo, numero in detalhes.get('normas', []):
                norma, _ = NormaVigente.objects.get_or_create(
                    tipo=tipo,
                    numero=numero,
                    defaults={'situacao': 'A VERIFICAR', 'fonte': 'DIARIO_OFICIAL'}
                )
                documento.normas_relacionadas.add(norma)
            
            documento.save()
            logger.info(f"Documento ID {documento.id} processado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Falha ao processar documento relevante ID {documento.id}: {str(e)}")
            return False

    def _gerar_resumo(self, texto: str, detalhes: Dict) -> str:
        """Gera um resumo inteligente do documento"""
        partes = []
        
        if detalhes.get('normas'):
            normas_str = ", ".join(f"{tipo} {numero}" for tipo, numero in detalhes['normas'][:3])
            partes.append(f" Normas mencionadas: {normas_str}")
        
        if detalhes.get('termos'):
            termos_str = ", ".join(f"{termo} ({count}x)" for termo, count in detalhes['termos'].items())
            partes.append(f" Termos contábeis: {termos_str}")
        
        trechos = self._extrair_trechos_relevantes(texto)
        if trechos:
            partes.append(" Trechos destacados:")
            partes.extend(trechos)
        
        return "\n\n".join(partes)[:2000]

    def _extrair_trechos_relevantes(self, texto: str) -> List[str]:
        """Extrai trechos relevantes do texto"""
        sentences = sent_tokenize(texto, language='portuguese')
        relevantes = []
        
        for sent in sentences:
            if len(relevantes) >= 3:
                break
                
            for padrao, _ in self.padroes_contabeis:
                if re.search(padrao, sent, re.IGNORECASE):
                    relevantes.append(sent.strip())
                    break
                    
        return relevantes

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