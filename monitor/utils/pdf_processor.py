# monitor/utils/pdf_processor.py
import os
import re
import logging
import traceback
from io import StringIO
from typing import Tuple, List, Dict, Optional
import spacy
from spacy.matcher import Matcher
from spacy.language import Language
import PyPDF2
from pdfminer.high_level import extract_text as extract_text_to_fp
from pdfminer.layout import LAParams
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from django.db.models import Q
from monitor.models import Documento, NormaVigente, TermoMonitorado
from django.utils import timezone
from collections import defaultdict
from datetime import datetime, date

logger = logging.getLogger(__name__)

@Language.component("norma_matcher")
def norma_matcher_component(doc):
    """Componente de pipeline spaCy para identificar normas"""
    return doc

class PDFProcessor:
    def __init__(self):
        self.nlp = None
        self.matcher = None

        # Tenta configurar o spaCy e o matcher imediatamente
        try:
            self._setup_spacy()
        except Exception as e:
            logger.critical(f"Falha CRÍTICA na inicialização de PDFProcessor: {e}", exc_info=True)
            raise 

        self.limite_relevancia = 4
        self.max_retries = 3
        self.timeout = 30
        
        # Mapeamento corrigido para os tipos de norma
        self.norma_type_choices_map = {
            'lei': 'LEI',
            'leis': 'LEI',
            'lei complementar': 'LEI',
            'lc': 'LEI',
            'decreto': 'DECRETO',
            'decretos': 'DECRETO',
            'decreto-lei': 'DECRETO',
            'decreto lei': 'DECRETO',
            'ato normativo': 'ATO_NORMATIVO',
            'resolução': 'RESOLUCAO',
            'resolucao': 'RESOLUCAO',
            'resolucões': 'RESOLUCAO',
            'instrução normativa': 'INSTRUCAO_NORMATIVA',
            'instrucao normativa': 'INSTRUCAO_NORMATIVA',
            'in': 'INSTRUCAO_NORMATIVA',
            'portaria': 'PORTARIA',
            'portarias': 'PORTARIA',
            'emenda constitucional': 'OUTROS',
            'ec': 'OUTROS',
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

    def _configure_matchers(self):
        """Configura os matchers para identificação de normas."""
        self.matcher = Matcher(self.nlp.vocab)
        
        # Padrão para "LEI [COMPLEMENTAR] [Nº] [NÚMERO]"
        self.matcher.add("LEI_PADRAO", [
            [{"LOWER": {"IN": ["lei", "leis", "lc"]}}, {"LOWER": "complementar", "OP": "?"}, 
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
            [{"LOWER": {"IN": ["resolucao", "resoluções", "resolução"]}}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        # Padrão para "INSTRUCAO [NORMATIVA] [Nº] [NÚMERO]"
        self.matcher.add("INSTRUCAO_PADRAO", [
            [{"LOWER": {"IN": ["instrucao", "instruções", "instrução", "in"]}}, {"LOWER": "normativa", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        logger.info("Matchers spaCy configurados com sucesso.")

    def _padronizar_numero_norma(self, numero: str) -> str:
        """Padroniza números de normas mantendo pontos decimais"""
        if not numero:
            return ""
            
        # Remove caracteres não numéricos exceto pontos, barras e hífens
        numero_limpo = re.sub(r'[^\d./-]', '', str(numero))
        
        # Tratamento especial para números com pontos (como 21.866)
        if '.' in numero_limpo:
            partes = numero_limpo.split('.')
            # Mantém a formatação original para números como "21.866"
            if len(partes) == 2 and len(partes[1]) == 3:  # Formato típico: XX.XXX
                return numero_limpo
            else:
                # Para outros casos, remove zeros à esquerda
                numero_limpo = f"{partes[0]}.{''.join(partes[1:])}"
        else:
            # Remove zeros à esquerda para números sem ponto
            numero_limpo = numero_limpo.lstrip('0') or '0'
        
        return numero_limpo

    def _get_norma_type_for_model(self, extracted_type_string: str) -> str:
        """Mapeia o tipo extraído para o tipo aceito pelo modelo"""
        tipo_limpo = extracted_type_string.lower().strip()
        return self.norma_type_choices_map.get(tipo_limpo, 'OUTROS')

    def extrair_normas(self, texto: str, data_publicacao_documento: Optional[date] = None) -> List[Tuple[str, str, Optional[int]]]:
        """Extrai normas do texto usando regex melhorado e termos específicos"""
        normas_encontradas = []
        ano_base_documento = data_publicacao_documento.year if data_publicacao_documento else None
        
        # 1. Regex principal para capturar normas gerais
        padrao_norma = re.compile(
            r'\b(lei\s+complementar|lc|lei|decreto(?:\s*-?\s*lei)?|ato\s+normativo|portaria|instrução\s+normativa|instrucao\s+normativa|in|emenda\s+constitucional|ec|resolução|resolucao)\b'
            r'[\s:]*(?:n[º°o.]?\s*)?'
            r'(\d+(?:[\.\-\/]\d+)*)'
            r'(?:[\s]*[\/\-][\s]*((?:19|20)?\d{2}))?'
            , re.IGNORECASE | re.MULTILINE
        )
        
        logger.debug(f"=== INICIANDO EXTRAÇÃO DE NORMAS ===")
        logger.debug(f"Texto tem {len(texto)} caracteres")
        
        # Busca com regex principal
        matches_found = 0
        for match in padrao_norma.finditer(texto):
            matches_found += 1
            tipo_extraido = match.group(1).strip()
            numero_extraido = match.group(2).strip()
            ano_str_extraido = match.group(3).strip() if match.group(3) else None

            numero_padronizado = self._padronizar_numero_norma(numero_extraido)
            ano_convertido = self._converter_ano_para_4_digitos(ano_str_extraido, ano_base_documento)
            
            logger.debug(f"REGEX GERAL - Match: '{tipo_extraido}' '{numero_extraido}' -> '{tipo_extraido}' '{numero_padronizado}' (ano: {ano_convertido})")
            normas_encontradas.append((tipo_extraido, numero_padronizado, ano_convertido))

        logger.debug(f"REGEX GERAL encontrou {matches_found} matches")

        # 2. Busca específica usando termos monitorados do tipo NORMA
        try:
            termos_normas = TermoMonitorado.objects.filter(ativo=True, tipo='NORMA')
            logger.debug(f"Verificando {termos_normas.count()} termos específicos de NORMA")
            
            for termo_obj in termos_normas:
                logger.debug(f"Analisando termo: '{termo_obj.termo}' com variações: {termo_obj.variacoes}")
                
                # Lista de termos para buscar (principal + variações)
                termos_para_buscar = [termo_obj.termo]
                if termo_obj.variacoes:
                    if isinstance(termo_obj.variacoes, str):
                        variacoes_lista = [v.strip() for v in termo_obj.variacoes.split(',')]
                    else:
                        variacoes_lista = termo_obj.variacoes
                    termos_para_buscar.extend(variacoes_lista)
                
                # Busca cada termo/variação
                for termo_busca in termos_para_buscar:
                    if not termo_busca.strip():
                        continue
                        
                    termo_busca = termo_busca.strip()
                    logger.debug(f"Buscando termo específico: '{termo_busca}'")
                    
                    # Busca exata primeiro
                    if re.search(rf'\b{re.escape(termo_busca)}\b', texto, re.IGNORECASE):
                        logger.debug(f"TERMO ESPECÍFICO ENCONTRADO (exato): {termo_busca}")
                        
                        # Extrai tipo e número do termo
                        partes = termo_busca.split()
                        if len(partes) >= 2:
                            tipo_termo = partes[0]
                            numero_termo = ' '.join(partes[1:])
                            numero_padronizado = self._padronizar_numero_norma(numero_termo)
                            
                            # Remove prefixos como "nº" do número se existirem
                            numero_limpo = re.sub(r'^n[º°.]?\s*', '', numero_padronizado, flags=re.IGNORECASE)
                            
                            logger.debug(f"Extraído: tipo='{tipo_termo}', numero='{numero_limpo}'")
                            normas_encontradas.append((tipo_termo, numero_limpo, None))
                    
                    # Busca flexível para casos como "decreto 21.866" vs "decreto nº 21.866"
                    partes_termo = termo_busca.split()
                    if len(partes_termo) >= 2:
                        tipo_busca = partes_termo[0]
                        numero_busca = ' '.join(partes_termo[1:])
                        
                        # Remove prefixos do número
                        numero_busca_limpo = re.sub(r'^n[º°.]?\s*', '', numero_busca, flags=re.IGNORECASE)
                        numero_so_digitos = re.sub(r'[^\d]', '', numero_busca_limpo)
                        
                        # Padrões flexíveis
                        padroes_flexiveis = [
                            # Tipo + número (com ou sem pontuação)
                            rf'\b{re.escape(tipo_busca)}\s+{re.escape(numero_busca_limpo)}\b',
                            rf'\b{re.escape(tipo_busca)}\s+n[º°.]?\s*{re.escape(numero_busca_limpo)}\b',
                            # Versão sem pontuação
                            rf'\b{re.escape(tipo_busca)}\s+{numero_so_digitos}\b',
                            rf'\b{re.escape(tipo_busca)}\s+n[º°.]?\s*{numero_so_digitos}\b',
                        ]
                        
                        for padrao_flex in padroes_flexiveis:
                            matches_flex = list(re.finditer(padrao_flex, texto, re.IGNORECASE))
                            if matches_flex:
                                logger.debug(f"TERMO ESPECÍFICO ENCONTRADO (flexível): {tipo_busca} {numero_busca_limpo} via padrão {padrao_flex}")
                                normas_encontradas.append((tipo_busca, numero_busca_limpo, None))
                                break

        except Exception as e:
            logger.error(f"Erro ao buscar termos monitorados específicos: {e}")

        # 3. Remove duplicatas mantendo a primeira ocorrência
        normas_unicas = []
        normas_vistas = set()
        
        for tipo, numero, ano in normas_encontradas:
            # Normaliza para comparação
            tipo_norm = tipo.upper().strip()
            numero_norm = numero.strip()
            chave_unica = (tipo_norm, numero_norm, ano)
            
            if chave_unica not in normas_vistas:
                normas_unicas.append((tipo, numero, ano))
                normas_vistas.add(chave_unica)
                logger.debug(f"Norma única adicionada: {tipo} {numero} (ano: {ano})")
        
        logger.debug(f"=== RESULTADO FINAL ===")
        logger.debug(f"Total de normas únicas encontradas: {len(normas_unicas)}")
        for tipo, numero, ano in normas_unicas:
            logger.debug(f"  - {tipo} {numero}" + (f" ({ano})" if ano else ""))
        
        return normas_unicas

    def is_relevante_contabil(self, texto: str) -> bool:
        """Verifica se o documento contém termos monitorados ativos"""
        try:
            # Converte para lowercase para comparações case-insensitive
            texto_lower = texto.lower()
            
            # Remove acentos e caracteres especiais para busca mais flexível
            import unicodedata
            texto_normalizado = unicodedata.normalize('NFD', texto_lower)
            texto_sem_acentos = ''.join(c for c in texto_normalizado if unicodedata.category(c) != 'Mn')
            
            # Busca todos os termos monitorados ativos
            termos_monitorados = TermoMonitorado.objects.filter(ativo=True)
            logger.debug(f"Verificando relevância com {termos_monitorados.count()} termos monitorados")
            
            for termo_obj in termos_monitorados:
                # Normaliza o termo principal
                termo_principal = termo_obj.termo.lower().strip()
                termo_sem_acentos = unicodedata.normalize('NFD', termo_principal)
                termo_sem_acentos = ''.join(c for c in termo_sem_acentos if unicodedata.category(c) != 'Mn')
                
                # Busca o termo principal
                if termo_principal in texto_lower or termo_sem_acentos in texto_sem_acentos:
                    logger.debug(f"Termo principal encontrado: {termo_obj.termo}")
                    return True
                    
                # Verifica variações se existirem
                if termo_obj.variacoes:
                    # Se variacoes é uma string, tenta fazer split por vírgula
                    if isinstance(termo_obj.variacoes, str):
                        variacoes_lista = [v.strip() for v in termo_obj.variacoes.split(',')]
                    else:
                        # Se é uma lista (dependendo do seu modelo)
                        variacoes_lista = termo_obj.variacoes
                    
                    for variacao in variacoes_lista:
                        if not variacao:
                            continue
                            
                        variacao_limpa = variacao.lower().strip()
                        variacao_sem_acentos = unicodedata.normalize('NFD', variacao_limpa)
                        variacao_sem_acentos = ''.join(c for c in variacao_sem_acentos if unicodedata.category(c) != 'Mn')
                        
                        if variacao_limpa in texto_lower or variacao_sem_acentos in texto_sem_acentos:
                            logger.debug(f"Variação encontrada: {variacao}")
                            return True
                
                # Para normas, busca mais flexível e específica
                if termo_obj.tipo == 'NORMA':
                    if self._buscar_norma_especifica(texto_lower, termo_obj):
                        logger.debug(f"Norma encontrada: {termo_obj.termo}")
                        return True
            
            logger.debug("Nenhum termo monitorado encontrado - documento não relevante")
            return False
            
        except Exception as e:
            logger.error(f"Erro ao verificar relevância contábil: {e}")
            return False

    def _buscar_norma_especifica(self, texto_lower: str, termo_obj) -> bool:
        """Busca específica para normas com padrões flexíveis"""
        termo_principal = termo_obj.termo.lower()
        
        # Lista de todos os termos a buscar (principal + variações)
        termos_para_buscar = [termo_principal]
        if termo_obj.variacoes:
            if isinstance(termo_obj.variacoes, str):
                variacoes_lista = [v.strip().lower() for v in termo_obj.variacoes.split(',')]
            else:
                variacoes_lista = [v.lower() for v in termo_obj.variacoes]
            termos_para_buscar.extend(variacoes_lista)
        
        for termo in termos_para_buscar:
            if not termo:
                continue
                
            # Busca exata primeiro
            if termo in texto_lower:
                return True
            
            # Para termos como "decreto 21.866", criar padrões flexíveis
            partes = termo.split()
            if len(partes) >= 2:
                tipo_norma = partes[0]  # "decreto"
                numero_norma = ' '.join(partes[1:])  # "21.866"
                
                # Remove pontuação do número para busca mais flexível
                numero_limpo = re.sub(r'[^\d]', '', numero_norma)
                
                # Padrões flexíveis para busca
                padroes = [
                    # Decreto 21.866
                    rf'\b{re.escape(tipo_norma)}\s+{re.escape(numero_norma)}\b',
                    # Decreto nº 21.866
                    rf'\b{re.escape(tipo_norma)}\s+n[º°.]\s*{re.escape(numero_norma)}\b',
                    # Decreto 21866 (sem ponto)
                    rf'\b{re.escape(tipo_norma)}\s+{numero_limpo}\b',
                    # Decreto nº 21866
                    rf'\b{re.escape(tipo_norma)}\s+n[º°.]\s*{numero_limpo}\b',
                ]
                
                for padrao in padroes:
                    if re.search(padrao, texto_lower, re.IGNORECASE):
                        return True
        
        return False

    def process_document(self, documento: Documento) -> Dict[str, any]:
        """Processa um documento completo"""
        logger.info(f"Processando documento ID: {documento.id}, Título: {documento.titulo[:50]}...")
        
        if not documento.texto_completo:
            logger.warning(f"Documento ID {documento.id} não possui texto completo. Pulando processamento.")
            documento.processado = True
            documento.save()
            return {'status': 'FALHA', 'message': 'Texto completo ausente.'}

        try:
            texto = documento.texto_completo
            
            # 1. Verificar relevância
            relevante_contabil = self.is_relevante_contabil(texto)
            documento.relevante_contabil = relevante_contabil
            documento.assunto = "Contábil/Fiscal" if relevante_contabil else "Geral"
            
            logger.info(f"Documento ID {documento.id} - Relevante: {relevante_contabil}")

            if not relevante_contabil:
                documento.processado = True 
                documento.save()
                logger.info(f"Documento ID {documento.id} marcado como irrelevante e processado.")
                return {'status': 'IGNORADO_IRRELEVANTE', 'message': 'Documento não relevante para contabilidade/fiscal.'}

            # 2. Extrair Normas
            normas_encontradas = self.extrair_normas(texto, documento.data_publicacao)
            normas_objs_para_relacionar = []
            normas_strings_para_resumo = []

            logger.info(f"Normas encontradas para documento {documento.id}: {len(normas_encontradas)}")

            for tipo_extraido_raw, numero_norma_extraido, ano_extraido in normas_encontradas:
                # Mapeia o tipo para o formato aceito pelo modelo
                tipo_para_db = self._get_norma_type_for_model(tipo_extraido_raw)
                
                try:
                    # Cria ou busca a norma no banco
                    norma_obj, created = NormaVigente.objects.get_or_create(
                        tipo=tipo_para_db,
                        numero=numero_norma_extraido,
                        defaults={
                            'data_ultima_mencao': documento.data_publicacao,
                            'ano': ano_extraido
                        }
                    )
                    
                    if not created:
                        # Atualiza a data da última menção se for mais recente
                        if documento.data_publicacao and (not norma_obj.data_ultima_mencao or documento.data_publicacao > norma_obj.data_ultima_mencao):
                            norma_obj.data_ultima_mencao = documento.data_publicacao
                            norma_obj.save(update_fields=['data_ultima_mencao'])
                    
                    normas_objs_para_relacionar.append(norma_obj)
                    normas_strings_para_resumo.append(f"{tipo_para_db} {numero_norma_extraido}")
                    
                    logger.debug(f"Norma processada: {tipo_para_db} {numero_norma_extraido} ({'criada' if created else 'existente'})")
                    
                except Exception as e:
                    logger.error(f"Erro ao criar/buscar norma {tipo_para_db} {numero_norma_extraido}: {e}")

            # 3. Gerar Resumo
            resumo = texto[:500] + "..." if len(texto) > 500 else texto
            documento.resumo = resumo

            # 4. Atualizar o Documento
            documento.processado = True
            documento.data_processamento = timezone.now()
            documento.save()
            
            # Relacionar as normas encontradas
            if normas_objs_para_relacionar:
                documento.normas_relacionadas.set(normas_objs_para_relacionar)
                logger.info(f"Documento {documento.id} relacionado com {len(normas_objs_para_relacionar)} normas")
            
            logger.info(f"Documento ID {documento.id} processado com sucesso. Normas encontradas: {len(normas_strings_para_resumo)}")
            
            return {
                'status': 'SUCESSO',
                'message': 'Documento processado com sucesso.',
                'relevante_contabil': relevante_contabil,
                'normas_extraidas': normas_strings_para_resumo,
                'total_normas': len(normas_strings_para_resumo)
            }

        except Exception as e:
            logger.error(f"Erro ao processar documento ID {documento.id}: {e}", exc_info=True)
            documento.processado = True
            documento.save()
            return {'status': 'ERRO', 'message': str(e), 'traceback': traceback.format_exc()}

    def _converter_ano_para_4_digitos(self, ano_str: Optional[str], ano_base_documento: Optional[int] = None) -> Optional[int]:
        """Converte ano de 2 dígitos para 4 dígitos"""
        if not ano_str or not ano_str.isdigit():
            return None
        
        try:
            ano_num = int(ano_str)
        except ValueError:
            return None

        if len(ano_str) == 4:
            # Valida intervalo razoável para anos de 4 dígitos
            if 1800 <= ano_num <= (datetime.now().year + 5):
                return ano_num
            else:
                return None
                
        elif len(ano_str) == 2:
            ano_atual = datetime.now().year
            limite_curto = (ano_atual % 100) + 5

            if ano_base_documento:
                seculo_doc = (ano_base_documento // 100) * 100
                ano_convertido = seculo_doc + ano_num
                
                if ano_convertido > (ano_base_documento + 10) and seculo_doc >= 2000:
                    ano_convertido = (seculo_doc - 100) + ano_num
                
                if ano_convertido > (ano_atual + 5):
                    return (seculo_doc - 100 + ano_num) if (seculo_doc - 100 + ano_num) < ano_convertido else ano_convertido

                return ano_convertido
            else:
                # Fallback sem ano base do documento
                if ano_num <= limite_curto:
                    return 2000 + ano_num
                else:
                    return 1900 + ano_num
        
        return None

    def _identificar_relevancia_geral(self, texto: str) -> int:
        """Identifica a relevância do documento com base em palavras-chave"""
        if self.nlp is None or self.matcher is None:
            logger.error("NLP model or Matcher not initialized")
            return 0

        try:
            doc = self.nlp(texto[:10000])  # Limita o texto para performance
            matches = self.matcher(doc)
            return len(matches)
        except Exception as e:
            logger.error(f"Erro ao identificar relevância geral: {e}")
            return 0