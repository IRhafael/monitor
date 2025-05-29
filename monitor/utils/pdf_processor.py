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
from django.db.models import Q  # ✅ isso é o correto
from monitor.models import Documento, NormaVigente, TermoMonitorado
from django.utils import timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    from transformers import pipeline
    IA_DISPONIVEL = True
except ImportError:
    IA_DISPONIVEL = False

class IAGratuita:
    def __init__(self):
        if IA_DISPONIVEL:
            self.resumidor = pipeline("summarization", model="facebook/bart-large-cnn")
            self.sentimento = pipeline("sentiment-analysis", model="cardiffnlp/twitter-roberta-base-sentiment-latest")
        else:
            self.resumidor = None
            self.sentimento = None

    def gerar_resumo(self, texto, max_length=150):
        if not self.resumidor or not texto:
            return texto[:max_length] + "..."
        try:
            resultado = self.resumidor(texto, max_length=max_length, min_length=30, do_sample=False)
            return resultado[0]['summary_text']
        except Exception:
            return texto[:max_length] + "..."

    def analisar_sentimento(self, texto):
        if not self.sentimento or not texto:
            return "desconhecido"
        try:
            resultado = self.sentimento(texto)
            return resultado[0]['label']
        except Exception:
            return "erro"

@Language.component("norma_matcher")
def norma_matcher_component(doc):
    """Componente de pipeline spaCy para identificar normas"""
    return doc

class PDFProcessor:
    def __init__(self):
        self.nlp = None
        self.matcher = None # Inicializa o matcher como None, garantindo que o atributo exista

        # Tenta configurar o spaCy e o matcher imediatamente
        try:
            self._setup_spacy()
        except Exception as e:
            logger.critical(f"Falha CRÍTICA na inicialização de PDFProcessor: {e}", exc_info=True)
            # Re-lança a exceção para que o código que instanciou PDFProcessor saiba da falha
            raise 

        self.limite_relevancia = 4
        self.max_retries = 3
        self.timeout = 30
        self.norma_type_choices_map = {
                'lei': 'LEI',
                'decreto': 'DECRETO',
                'ato normativo': 'ATO_NORMATIVO',
                'resolução': 'RESOLUCAO',
                'instrução normativa': 'INSTRUCAO_NORMATIVA',
                'portaria': 'PORTARIA',
                'outros': 'OUTROS',
            }


    def _setup_spacy(self):
        """Configura o pipeline NLP com spaCy"""
        try:
            self.nlp = spacy.load("pt_core_news_sm")
            self._configure_matchers()
            logger.info("Modelo spaCy 'pt_core_news_sm' carregado com sucesso para uso.")
        except OSError:
            logger.warning("Modelo spaCy 'pt_core_news_sm' não encontrado. Baixando...")
            spacy.cli.download("pt_core_news_sm")
            self.nlp = spacy.load("pt_core_news_sm")
            self._configure_matchers()
            logger.info("Modelo spaCy 'pt_core_news_sm' baixado e carregado com sucesso para uso.")
        except Exception as e:
            logger.error(f"Erro ao carregar ou configurar spaCy: {e}", exc_info=True)
            raise

    def _get_norma_type_choices_map(self):
        """
        Define um dicionário de mapeamento para os tipos de norma aceitos pelo modelo NormaVigente.
        Isso mapeia variações encontradas no texto para as chaves internas do Django.
        """
        mapping = defaultdict(lambda: 'OUTROS') # Valor padrão se não houver mapeamento
        
        # Mapeamentos flexíveis para LEI
        mapping['lei'] = 'LEI'
        mapping['leis'] = 'LEI'
        mapping['lei complementar'] = 'LEI'
        mapping['leis complementares'] = 'LEI'

        # Mapeamentos para DECRETO
        mapping['decreto'] = 'DECRETO'
        mapping['decretos'] = 'DECRETO'
        mapping['decreto-lei'] = 'DECRETO'

        # Mapeamentos para PORTARIA
        mapping['portaria'] = 'PORTARIA'
        mapping['portarias'] = 'PORTARIA'

        # Mapeamentos para RESOLUCAO
        mapping['resolucao'] = 'RESOLUCAO'
        mapping['resolucoes'] = 'RESOLUCAO'

        # Mapeamentos para INSTRUCAO NORMATIVA
        mapping['instrucao normativa'] = 'INSTRUCAO'
        mapping['instrução normativa'] = 'INSTRUCAO'
        mapping['instrucao'] = 'INSTRUCAO'

        # Adiciona os valores exatos dos choices como mapeamento para si mesmos (garante que funcionem)
        for choice_key, _ in NormaVigente.TIPO_CHOICES:
            mapping[choice_key.lower()] = choice_key
            
        return mapping
    
    def _get_norma_type_for_model(self, extracted_type_string: str) -> str:

        return self.norma_type_choices_map.get(extracted_type_string.lower().strip(), 'OUTROS')


    def _configure_matchers(self):
        """Configura os matchers para identificação de normas."""
        self.matcher = Matcher(self.nlp.vocab)
        # Padrões mais genéricos que serão usados para identificar o tipo e número da norma
        # Este é um exemplo, você pode precisar refinar os padrões
        
        # Padrão para "LEI [COMPLEMENTAR] [Nº] [NÚMERO]"
        self.matcher.add("LEI_PADRAO", [
            [{"LOWER": {"IN": ["lei", "leis"]}}, {"OP": "?"}, {"LOWER": "complementar", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        # Padrão para "DECRETO [LEI] [Nº] [NÚMERO]"
        self.matcher.add("DECRETO_PADRAO", [
            [{"LOWER": {"IN": ["decreto", "decretos"]}}, {"LOWER": "lei", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        # Padrão para "PORTARIA [Nº] [NÚMERO]"
        self.matcher.add("PORTARIA_PADRAO", [
            [{"LOWER": {"IN": ["portaria", "portarias"]}}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        # Padrão para "RESOLUCAO [Nº] [NÚMERO]"
        self.matcher.add("RESOLUCAO_PADRAO", [
            [{"LOWER": {"IN": ["resolucao", "resoluções"]}}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        # Padrão para "INSTRUCAO [NORMATIVA] [Nº] [NÚMERO]"
        self.matcher.add("INSTRUCAO_PADRAO", [
            [{"LOWER": {"IN": ["instrucao", "instruções"]}}, {"LOWER": "normativa", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        logger.info("Matchers spaCy configurados com sucesso.")

    def _padronizar_numero_norma(self, numero: str) -> str:
        """Padroniza números de normas mantendo pontos decimais"""
        # Remove caracteres não numéricos exceto pontos, barras e hífens
        numero = re.sub(r'[^\d./-]', '', str(numero))
        
        # Tratamento especial para números com pontos (como 21.866)
        if '.' in numero:
            partes = numero.split('.')
            # Mantém a parte inteira e remove zeros à esquerda das partes decimais
            numero = f"{partes[0]}.{''.join(partes[1:])}"
        else:
            # Remove zeros à esquerda para números sem ponto
            numero = numero.lstrip('0') or '0'
        
        return numero
    
   
    def _padronizar_numero_norma(self, numero: str) -> str:
        """Corrige a extração de números como '21.866'"""
        # Remove caracteres não numéricos exceto pontos, barras e hífens
        numero = re.sub(r'[^\d./-]', '', str(numero))
        
        # Mantém zeros significativos (como em "21.866")
        if '.' in numero:
            partes = numero.split('.')
            numero = '.'.join([partes[0]] + [p.lstrip('0') for p in partes[1:]])
        
        return numero


    def _extrair_normas_especificas(self, texto: str, termo_para_buscar: str) -> List[Tuple[str, str]]:
        normas = []
        patterns = []
        termo_lower = termo_para_buscar.lower()

        if 'lei' in termo_lower:
            patterns.append(r'(lei complementar|lei)')
        if 'decreto' in termo_lower:
            patterns.append(r'(decreto[\- ]?lei|decreto)')
        if 'portaria' in termo_lower:
            patterns.append(r'(portaria)')
        if 'resolucao' in termo_lower:
            patterns.append(r'(resolucao)')
        if 'instrucao' in termo_lower:
            patterns.append(r'(instrucao normativa|instrucao)')
        
        # Se não houver padrões específicos, não há o que buscar para este termo
        if not patterns:
            return []

        # Junta todos os padrões de tipo com OR (|)
        tipo_regex_part = '|'.join(patterns)
        
        # Regex final: (grupo 1: tipo de norma) (opcional 'Nº'/'N.') (grupo 2: numero da norma)
        padrao_regex = re.compile(
            rf'(?i)({tipo_regex_part})[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\\/]?\d*(?:[\\/]\\d+)*)', 
            re.IGNORECASE
        )
        for match in padrao_regex.finditer(texto):
            raw_type = match.group(1) # Ex: "lei complementar", "decreto", "portaria"
            numero_raw = match.group(2)
            numero_padronizado = self._padronizar_numero_norma(numero_raw)
            # Retorna o tipo como foi encontrado (raw) para que a função chamadora faça o mapeamento
            normas.append((raw_type, numero_padronizado))

        return normas

    def extrair_normas(self, texto: str) -> List[Tuple[str, str]]:
        normas_encontradas = []
        
        # Padrão regex melhorado para capturar números com pontos
        padrao_norma = re.compile(
            r'(?i)(lei complementar|lei|decreto[\- ]?lei|decreto|ato normativo|portaria|instrução normativa|in)[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\/\-]?\d*(?:[\/\-]\d+)*)',
            re.IGNORECASE
        )
        
        # Primeiro procura por normas usando o padrão geral
        for match in padrao_norma.finditer(texto):
            tipo = match.group(1).upper()
            numero = match.group(2)
            
            # Padroniza o número
            numero = self._padronizar_numero_norma(numero)
            normas_encontradas.append((tipo, numero))
        
        # Depois verifica termos monitorados do tipo NORMA
        termos_normas = TermoMonitorado.objects.filter(ativo=True, tipo='NORMA')
        for termo in termos_normas:
            # Cria um padrão específico para o termo
            termo_regex = re.compile(
                rf'(?i){re.escape(termo.termo)}[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\/\-]?\d*(?:[\/\-]\d+)*)',
                re.IGNORECASE
            )
            
            for match in termo_regex.finditer(texto):
                numero = match.group(1)
                numero = self._padronizar_numero_norma(numero)
                normas_encontradas.append((termo.termo.split()[0].upper(), numero))
        
        return list(set(normas_encontradas))  # Remove duplicatas




    def _identificar_relevancia_geral(self, texto: str) -> int:
        """Identifica a relevância do documento com base em palavras-chave e retorna uma pontuação."""
        if self.nlp is None or self.matcher is None:
            logger.error("NLP model or Matcher not initialized in _identificar_relevancia_geral. Cannot identify general relevance.")
            return 0 # Retorna 0 se não estiver inicializado

        doc = self.nlp(texto)
        score = 0
        
        # Usa os matchers para palavras-chave contábeis
        matches = self.matcher(doc)
        for match_id, start, end in matches:
            if self.nlp.vocab.strings[match_id].startswith("CONTABIL_KEYWORD"):
                score += 1

        # Adicione mais lógica de pontuação se necessário
        
        return score

   
    

    def is_relevante_contabil(self, texto: str) -> bool:
        """
        Verifica se o documento contém termos monitorados relevantes para contabilidade/fiscal,
        considerando termos e variações cadastrados no banco.
        """
        texto_lower = texto.lower()
        termos = TermoMonitorado.objects.filter(ativo=True)
        for termo in termos:
            # Checa o termo principal
            if termo.termo.lower() in texto_lower:
                return True
            # Checa variações (se houver)
            if termo.variacoes:
                for variacao in [v.strip() for v in termo.variacoes.split(",")]:
                    if variacao and variacao.lower() in texto_lower:
                        return True
        return False

    def process_document(self, documento: Documento) -> Dict[str, any]:
        logger.info(f"Processando documento ID: {documento.id}, Título: {documento.titulo[:50]}...")

        if not documento.texto_completo:
            logger.warning(f"Documento ID {documento.id} não possui texto completo. Pulando processamento.")
            documento.processado = True
            documento.save()
            return {'status': 'FALHA', 'message': 'Texto completo ausente.'}

        try:
            texto = documento.texto_completo

            # 1. Extrair Normas do texto COMPLETO
            normas_encontradas = self.extrair_normas(texto)
            normas_objs_para_relacionar = []
            normas_strings_para_resumo = []

            tipo_map = {
                'LEI': 'LEI',
                'LEI COMPLEMENTAR': 'LEI',
                'DECRETO': 'DECRETO',
                'DECRETO-LEI': 'DECRETO',
                'PORTARIA': 'PORTARIA',
                'RESOLUCAO': 'RESOLUCAO',
                'RESOLUÇÃO': 'RESOLUCAO',
                'INSTRUCAO': 'INSTRUCAO',
                'INSTRUÇÃO': 'INSTRUCAO',
                'INSTRUCAO NORMATIVA': 'INSTRUCAO',
                'INSTRUÇÃO NORMATIVA': 'INSTRUCAO',
            }

            for tipo_norma_modelo, numero in normas_encontradas:
                tipo_norma_modelo = tipo_norma_modelo.strip().upper()
                tipo_norma_modelo = tipo_map.get(tipo_norma_modelo, 'OUTROS')
                if not numero or len(str(numero)) < 3:
                    logger.warning(f"Norma ignorada por número muito curto: tipo={tipo_norma_modelo}, numero={numero}")
                    continue
                norma_obj, created = NormaVigente.objects.get_or_create(
                    tipo=tipo_norma_modelo,
                    numero=numero,
                    defaults={'data_ultima_mencao': documento.data_publicacao}
                )
                if not created:
                    if documento.data_publicacao and (not norma_obj.data_ultima_mencao or documento.data_publicacao > norma_obj.data_ultima_mencao):
                        norma_obj.data_ultima_mencao = documento.data_publicacao
                        norma_obj.save(update_fields=['data_ultima_mencao'])
                normas_objs_para_relacionar.append(norma_obj)
                normas_strings_para_resumo.append(f"{tipo_norma_modelo} {numero}")

            # 2. Selecionar parágrafos relevantes para o resumo (com contexto e palavras-chave de mudança)
            def paragrafos_relevantes_com_contexto(texto, normas_encontradas):
                # Limpeza agressiva de linhas irrelevantes
                linhas = texto.splitlines()
                linhas_limpa = []
                for linha in linhas:
                    l = linha.strip()
                    if not l or len(l) < 4:
                        continue
                    if re.match(r'^Página \d+/\d+', l) or l.upper() in ["SUMÁRIO", "ERRATAS", "EXTRATOS", "LEIS", "DECRETOS"]:
                        continue
                    if "DIÁRIO OFICIAL" in l.upper() or "DOE/PI" in l or "PALÁCIO DE KARNAK" in l or "Publicado:" in l or "Disponibilizado:" in l:
                        continue
                    if "contPageBreak" in l or "www.diario.pi.gov.br" in l or "e-mail:" in l:
                        continue
                    if "Assinado Eletronicamente" in l or "assinado eletronicamente" in l:
                        continue
                    if l.isdigit():
                        continue
                    if l.isupper() and len(l.split()) < 6:
                        continue
                    if set(l) <= set("-_ ."):
                        continue
                    if re.match(r'^SEI nº', l):
                        continue
                    if "Transcrição da nota" in l:
                        continue
                    if "Iniciado:" in l:
                        continue
                    if "Diário nº" in l:
                        continue
                    if "ANO" in l or "EDIÇÃO" in l or "REPÚBLICA" in l:
                        continue
                    # Remove cabeçalhos e aberturas comuns
                    if l.startswith("O GOVERNADOR") or l.startswith("R E S O L V E") or l.startswith("AUTORIZA") or l.startswith("DISPÕE"):
                        continue
                    linhas_limpa.append(l)

                texto_limpo = "\n".join(linhas_limpa)

                # Busca termos monitorados ativos e suas variações
                termos = TermoMonitorado.objects.filter(ativo=True)
                termos_busca = set()
                for termo in termos:
                    termos_busca.add(termo.termo.lower())
                    if termo.variacoes:
                        for variacao in [v.strip() for v in termo.variacoes.split(",")]:
                            if variacao:
                                termos_busca.add(variacao.lower())
                normas_busca = set()
                for tipo, numero in normas_encontradas:
                    if tipo and numero:
                        normas_busca.add(f"{tipo} {numero}".lower())
                        normas_busca.add(numero.lower())

                # Palavras-chave para mudanças legais
                palavras_chave = [
                    "altera", "revoga", "vigência", "vigencia", "acrescenta", "modifica", "fica alterado",
                    "fica revogado", "passa a vigorar", "nova redação", "inclui", "exclui", "prorroga",
                    "ratifica", "convalida", "alteração", "revogação", "prorrogado", "prorrogada", "prorrogadas"
                ]

                paragrafos = [p.strip() for p in re.split(r'\n{2,}', texto_limpo) if p.strip()]
                indices_relevantes = set()
                for idx, p in enumerate(paragrafos):
                    p_lower = p.lower()
                    if (
                        any(term in p_lower for term in termos_busca)
                        or any(norma in p_lower for norma in normas_busca)
                        or any(palavra in p_lower for palavra in palavras_chave)
                    ):
                        indices_relevantes.add(idx)
                        # Adiciona contexto só se o parágrafo for muito curto
                        if len(p) < 100:
                            if idx > 0:
                                indices_relevantes.add(idx - 1)
                            if idx < len(paragrafos) - 1:
                                indices_relevantes.add(idx + 1)
                paragrafos_finais = [paragrafos[i] for i in sorted(indices_relevantes)]
                # Se não encontrar nada, pega os maiores parágrafos após a primeira norma/termo
                if not paragrafos_finais:
                    for idx, p in enumerate(paragrafos):
                        p_lower = p.lower()
                        if any(term in p_lower for term in termos_busca) or any(norma in p_lower for norma in normas_busca):
                            paragrafos_finais = sorted(paragrafos[idx:], key=len, reverse=True)[:5]
                            break
                    else:
                        paragrafos_finais = sorted(paragrafos, key=len, reverse=True)[:5]
                return "\n\n".join(paragrafos_finais)[:6000]

            texto_para_resumo = paragrafos_relevantes_com_contexto(texto, normas_encontradas)

            ia = IAGratuita()
            try:
                resumo_ia = ia.gerar_resumo(texto_para_resumo, max_length=700)
            except Exception as e:
                logger.error(f"Erro ao gerar resumo IA: {e}", exc_info=True)
                resumo_ia = texto_para_resumo[:700] + "..."

            try:
                sentimento_ia = ia.analisar_sentimento(texto_para_resumo)
            except Exception as e:
                logger.error(f"Erro ao analisar sentimento IA: {e}", exc_info=True)
                sentimento_ia = "erro"

            relevante_contabil = self.is_relevante_contabil(texto)
            documento.relevante_contabil = relevante_contabil
            documento.assunto = "Contábil/Fiscal" if relevante_contabil else "Geral"
            documento.resumo_ia = resumo_ia
            documento.sentimento_ia = sentimento_ia

            if not relevante_contabil:
                documento.processado = True
                documento.save()
                logger.info(f"Documento ID {documento.id} marcado como irrelevante e processado.")
                return {'status': 'IGNORADO_IRRELEVANTE', 'message': 'Documento não relevante para contabilidade/fiscal.'}

            # 4. Atualizar o Documento
            documento.processado = True
            documento.data_processamento = timezone.now()
            documento.save()
            documento.normas_relacionadas.set(normas_objs_para_relacionar)
            documento.save()

            logger.info(f"Documento ID {documento.id} processado com sucesso.")
            return {
                'status': 'SUCESSO',
                'message': 'Documento processado com sucesso.',
                'relevante_contabil': relevante_contabil,
                'normas_extraidas': normas_strings_para_resumo,
                'resumo_ia': resumo_ia,
                'sentimento_ia': sentimento_ia,
            }

        except Exception as e:
            logger.error(f"Erro ao processar documento ID {documento.id}: {e}", exc_info=True)
            documento.processado = True
            documento.save()
            return {'status': 'ERRO', 'message': str(e), 'traceback': traceback.format_exc()}