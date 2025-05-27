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

   
    # Método corrigido para is_relevante_contabil() em PDFProcessor
    def is_relevante_contabil(self, texto: str) -> bool:
        """Verifica se o documento contém termos monitorados ativos (TEXTO ou NORMA)"""
        from monitor.models import TermoMonitorado
        
        # Converte para lowercase para comparações case-insensitive
        texto_lower = texto.lower()
        
        # 1. Verificar termos do tipo TEXTO
        termos_texto = TermoMonitorado.objects.filter(ativo=True, tipo='TEXTO')
        for termo_obj in termos_texto:
            # Verifica o termo principal
            if termo_obj.termo.lower() in texto_lower:
                return True
                
            # Verifica variações
            if termo_obj.variacoes:
                for variacao in termo_obj.variacoes.split(','):
                    if variacao.strip().lower() in texto_lower:
                        return True
        
        # 2. Verificar termos do tipo NORMA
        termos_norma = TermoMonitorado.objects.filter(ativo=True, tipo='NORMA')
        for termo_obj in termos_norma:
            # Verifica o termo principal de forma exata
            if termo_obj.termo.lower() in texto_lower:
                return True
                
            # Verifica variações exatas
            if termo_obj.variacoes:
                for variacao in termo_obj.variacoes.split(','):
                    if variacao.strip().lower() in texto_lower:
                        return True
            
            # Para normas, precisamos de busca mais flexível
            # Extrai partes do termo (exemplo: "DECRETO 21.866" -> tipo="DECRETO", numero="21.866")
            partes = termo_obj.termo.split()
            if len(partes) >= 2:
                tipo_norma = partes[0].lower()  # "decreto"
                numero_norma = ' '.join(partes[1:]).lower()  # "21.866"
                
                # Cria padrão regex para busca flexível
                # Aceita variações como "Decreto nº 21.866", "DECRETO N. 21.866", "Decreto 21.866"
                padrao = rf'{tipo_norma}\s+(?:n[º°.]?\s*)?{re.escape(numero_norma)}'
                if re.search(padrao, texto_lower, re.IGNORECASE):
                    return True
                
                # Busca mais permissiva para números com pontuação
                numero_sem_pontuacao = re.sub(r'[^\d]', '', numero_norma)
                if numero_sem_pontuacao:
                    # Cria um padrão que aceita o número com ou sem pontuação
                    padrao_num_flex = rf'{tipo_norma}\s+(?:n[º°.]?\s*)?(?:\d+[.\s]*)+{numero_sem_pontuacao[-4:]}'
                    if re.search(padrao_num_flex, texto_lower, re.IGNORECASE):
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
            
            relevante_contabil = self.is_relevante_contabil(texto)
            documento.relevante_contabil = relevante_contabil
            documento.assunto = "Contábil/Fiscal" if relevante_contabil else "Geral"

            if not relevante_contabil:
                documento.processado = True 
                documento.save()
                logger.info(f"Documento ID {documento.id} marcado como irrelevante e processado.")
                return {'status': 'IGNORADO_IRRELEVANTE', 'message': 'Documento não relevante para contabilidade/fiscal.'}

            # 2. Extrair Normas
            normas_encontradas = self.extrair_normas(texto) 
            normas_objs_para_relacionar = [] 
            normas_strings_para_resumo = [] # Para o log e resumo

            for tipo_norma_modelo, numero in normas_encontradas:
                # O 'tipo_norma_modelo' já vem mapeado e correto para o campo `tipo` de `NormaVigente`.
                norma_obj, created = NormaVigente.objects.get_or_create(
                    tipo=tipo_norma_modelo, # Usa o tipo já mapeado (ex: 'LEI', 'DECRETO')
                    numero=numero,
                    defaults={'data_ultima_mencao': documento.data_publicacao}
                )
                if not created:
                    # Atualiza a data da última menção se for mais recente
                    if documento.data_publicacao and (not norma_obj.data_ultima_mencao or documento.data_publicacao > norma_obj.data_ultima_mencao):
                        norma_obj.data_ultima_mencao = documento.data_publicacao
                        norma_obj.save(update_fields=['data_ultima_mencao'])
                
                normas_objs_para_relacionar.append(norma_obj)
                normas_strings_para_resumo.append(f"{tipo_norma_modelo} {numero}")

            # 3. Gerar Resumo (simplificado para o exemplo)
            resumo = texto[:500] + "..." if len(texto) > 500 else texto
            documento.resumo = resumo

            # 4. Atualizar o Documento
            documento.processado = True
            documento.data_processamento = timezone.now() 
            
            documento.save() # Salva o documento antes de manipular o ManyToMany
            documento.normas_relacionadas.set(normas_objs_para_relacionar) # Atribui os objetos NormaVigente
            
            documento.save() # Salva quaisquer outras alterações no documento
            
            logger.info(f"Documento ID {documento.id} processado com sucesso.")
            return {
                'status': 'SUCESSO',
                'message': 'Documento processado com sucesso.',
                'relevante_contabil': relevante_contabil,
                'normas_extraidas': normas_strings_para_resumo 
            }

        except Exception as e:
            logger.error(f"Erro ao processar documento ID {documento.id}: {e}", exc_info=True)
            documento.processado = True # Marcar como processado para evitar reprocessamento em loop (ou False para retry)
            documento.save()
            return {'status': 'ERRO', 'message': str(e), 'traceback': traceback.format_exc()}