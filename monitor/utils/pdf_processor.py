# monitor/utils/pdf_processor.py
import os
import re
import logging
import traceback
import requests
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
from django.db.models import Q
from monitor.models import Documento, NormaVigente, TermoMonitorado
from django.utils import timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

MISTRAL_API_KEY = "AaODvu2cz9KAi55Jxal8NhjvpT1VyjBO"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

class MistralAI:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}", # MISTRAL_API_KEY definida globalmente
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.default_model = "mistral-small-latest" # Ou "mistral-medium-latest" para mais capacidade
        self.default_temperature = 0.2 # Para respostas mais factuais

   # Dentro da classe MistralAI no seu pdf_processor.py

    def _call_mistral(self, messages: List[Dict[str, str]], model: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Optional[str]:
        """
        Método interno para fazer a chamada à API da Mistral usando requests.
        Permite especificar max_tokens para a resposta.
        """
        # Verificação se a chave é um placeholder genérico OU se não foi definida
        # Remova sua chave real desta lista de placeholders!
        placeholders_de_chave_comuns = ["SuaChaveAqui", "COLOQUE_SUA_CHAVE_AQUI", "YOUR_MISTRAL_API_KEY", "CONFIGURE_API_KEY"]
        
        # MISTRAL_API_KEY deve ser a variável global definida no topo do seu arquivo,
        # ou self.api_key_to_use se você a armazenou como um atributo de instância no __init__.
        # Para este exemplo, vou assumir que MISTRAL_API_KEY é a variável global.
        
        if not MISTRAL_API_KEY or MISTRAL_API_KEY in placeholders_de_chave_comuns:
            logger.error(
                f"Chave da API Mistral não configurada corretamente ou é um placeholder. Valor atual: '{MISTRAL_API_KEY if MISTRAL_API_KEY else 'Não Definida'}'"
            )
            return "Erro: Chave da API Mistral não configurada ou é inválida."

        data = {
            "model": model or self.default_model, # Use self.default_model se definido no __init__
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature, # Use self.default_temperature
            "stream": False
        }
        if max_tokens:
            data["max_tokens"] = max_tokens

        try:
            # self.headers deve ser definido no __init__ da classe MistralAI
            response = requests.post(MISTRAL_API_URL, headers=self.headers, json=data, timeout=60) # MISTRAL_API_URL global
            response.raise_for_status()

            response_json = response.json()
            if response_json.get("choices") and len(response_json["choices"]) > 0:
                content = response_json["choices"][0].get("message", {}).get("content")
                if content:
                    logger.debug(f"Resposta da Mistral API: {content[:200]}...")
                    return content.strip()
                else:
                    logger.warning(f"Resposta da Mistral API não continha 'content' esperado: {response_json}")
                    return "Resposta da IA não continha conteúdo."
            else:
                logger.warning(f"Resposta da Mistral API não continha 'choices' esperados: {response_json}")
                return "Resposta da IA com formato inesperado."

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"Erro HTTP ao chamar Mistral API: {http_err} - Resposta: {response.text if 'response' in locals() else 'N/A'}", exc_info=True)
            status_code = http_err.response.status_code if http_err.response is not None else "N/A"
            return f"Erro HTTP {status_code} ao comunicar com a API. Verifique sua chave e o modelo solicitado."
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de requisição ao chamar Mistral API: {e}", exc_info=True)
            return f"Erro de comunicação com a API: {e}"
        except Exception as e:
            logger.error(f"Erro inesperado ao processar chamada da Mistral API: {e}", exc_info=True)
            return f"Erro inesperado ao processar resposta da IA: {e}"

    def gerar_resumo_contabil(self, texto: str, termos_monitorados: Optional[List[str]] = None) -> str:
        """
        Gera um resumo técnico contábil/fiscal do texto, destacando normas, alterações,
        impactos, prazos e consequências, com foco nos termos monitorados.
        """
        if not texto:
            return "Texto não fornecido para resumo."

        # Limita o tamanho do texto que será efetivamente incluído no prompt
        # Os modelos têm um limite de contexto total (prompt + resposta).
        # Para "mistral-small-latest", o contexto é de 32k tokens. 15000 caracteres são ~3k-4k tokens.
        texto_para_analise = texto[:14000] # Deixa ~1k tokens para o prompt e a resposta.

        termos_foco_str = ", ".join(termos_monitorados) if termos_monitorados else "aspectos fiscais e contábeis gerais relevantes para empresas no Piauí, incluindo ICMS, PIS, COFINS, IRPJ, CSLL, Simples Nacional, substituição tributária, e obrigações acessórias (SPED, EFD)."

        # Persona da IA (System Prompt)
        system_prompt = (
            "Você é um Contador Sênior e Consultor Tributário altamente experiente, com mais de 25 anos de atuação "
            "na interpretação e aplicação da legislação fiscal e contábil brasileira. Você possui profundo conhecimento das "
            "normativas do estado do Piauí e suas implicações para as empresas. Sua especialidade é analisar documentos "
            "oficiais complexos (Diários Oficiais, Leis, Decretos, Portarias, Atos Normativos) e transformá-los em "
            "informações claras, objetivas e acionáveis para outros profissionais da área. "
            "Sua linguagem deve ser técnica, precisa, mas compreensível para contadores e gestores fiscais."
        )

        # Instruções para o Usuário (User Prompt)
        user_prompt = (
            f"Com base no texto do documento oficial fornecido abaixo, elabore um RESUMO TÉCNICO CONTÁBIL/FISCAL. "
            f"O resumo deve ser conciso e direto, idealmente estruturado em TÓPICOS (bullet points usando '-') ou parágrafos curtos e numerados, "
            f"com um tamanho total MÁXIMO de 350 palavras (aproximadamente 1400-1700 caracteres). Foque exclusivamente no conteúdo do texto fornecido.\n\n"
            f"DESTAQUE OBRIGATORIAMENTE OS SEGUINTES PONTOS (se presentes e relevantes no texto fornecido):\n"
            f"1.  **Normas Referenciadas e Natureza da Mudança:** Liste as principais normas mencionadas (Leis, Decretos, Portarias, INs, etc.) com seus números e anos. Especifique se o documento institui uma nova norma, altera uma existente (quais artigos/seções), revoga, ou regulamenta.\n"
            f"2.  **Alterações Legais Relevantes:** Descreva as modificações de regras mais significativas que o documento introduz.\n"
            f"3.  **Principais Impactos Contábeis e Fiscais:** Detalhe os efeitos práticos para as empresas e para a apuração de tributos (ex: mudanças em alíquotas, base de cálculo, crédito/débito, novas obrigações, isenções, regimes especiais).\n"
            f"4.  **Prazos e Obrigações Importantes:** Se houver menção a prazos para cumprimento de novas obrigações, adaptação a novas regras, ou para usufruir de benefícios, liste-os claramente.\n"
            f"5.  **Consequências Práticas e Ações Recomendadas (se explícito no texto):** Se o texto sugerir ações, mencione-as brevemente.\n\n"
            f"CONCENTRE-SE PARTICULARMENTE em como o documento se relaciona com os seguintes termos/conceitos, se mencionados: {termos_foco_str}.\n\n"
            f"PRIORIZE: Precisão, relevância para a prática contábil/fiscal, e clareza. Evite especulações ou informações não contidas explicitamente no texto. Não adicione introduções ou conclusões genéricas.\n"
            f"Se o documento não contiver informações diretamente relevantes para os pontos acima, responda: 'Nenhuma informação contábil/fiscal crítica identificada no escopo solicitado neste documento.'\n\n"
            f"Texto para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
            f"Resumo Técnico Contábil/Fiscal Estruturado:"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # max_tokens para a resposta. Se esperamos ~350 palavras, e cada token ~0.75 palavras,
        # então ~470 tokens. Damos uma folga.
        resposta_ia = self._call_mistral(messages, max_tokens=600, temperature=0.25) # Ajuste temperature se necessário

        # Fallback básico se a IA não retornar nada ou der erro
        if not resposta_ia or "Erro" in resposta_ia:
            logger.warning(f"Falha ao gerar resumo pela IA ou IA retornou erro: {resposta_ia}. Usando fallback.")
            return texto[:700] + "..." if len(texto) > 700 else texto # Limite original do seu prompt
        return resposta_ia

    def analisar_sentimento_contabil(self, texto: str) -> str:
        """
        Analisa o sentimento do documento do ponto de vista contábil/fiscal,
        retornando uma das categorias especificadas de forma concisa.
        """
        if not texto:
            return "NEUTRO" # Ou "INDETERMINADO"

        # Limita o texto para a análise de sentimento, que geralmente não precisa do documento inteiro.
        texto_para_analise = texto[:4000]

        system_prompt = (
            "Você é um analista regulatório sênior, especializado em interpretar o impacto prático de novas normativas fiscais e contábeis "
            "para empresas e profissionais da contabilidade no Brasil, com foco no Piauí. Sua tarefa é classificar o 'sentimento' ou 'impacto geral primário' de um documento."
        )
        user_prompt = (
            f"Analise o texto do documento oficial abaixo exclusivamente sob a perspectiva contábil/fiscal. "
            f"Classifique o impacto geral do documento para as empresas/contadores em UMA ÚNICA PALAVRA das seguintes categorias:\n"
            f"-   **POSITIVO**: (Se o documento predominantemente simplifica processos, reduz carga tributária de forma clara, oferece benefícios ou incentivos fiscais significativos, ou facilita o compliance de maneira notável).\n"
            f"-   **NEGATIVO**: (Se o documento predominantemente introduz novas obrigações complexas ou onerosas, aumenta a carga tributária de forma clara, impõe restrições significativas, ou eleva consideravelmente o risco de penalidades).\n"
            f"-   **NEUTRO**: (Se o documento é majoritariamente informativo, mantém o status quo, as alterações são meramente técnicas/procedimentais sem grande alteração de ônus, ou os impactos fiscais/contábeis são mínimos).\n"
            f"-   **CAUTELA**: (Se o documento introduz ambiguidades legais significativas, aumenta substancialmente a complexidade interpretativa da legislação, ou se os impactos são incertos mas potencialmente relevantes e exigem uma análise aprofundada e cuidadosa antes de qualquer ação).\n\n"
            f"Texto para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
            f"Responda APENAS com UMA das quatro categorias listadas (POSITIVO, NEGATIVO, NEUTRO, CAUTELA), em letras maiúsculas. NÃO inclua nenhuma outra palavra, pontuação, explicação ou frase adicional."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        sentimento_resposta = self._call_mistral(messages, model="mistral-tiny", max_tokens=10, temperature=0.05) # Modelo menor e temperatura baixa para resposta restrita

        if sentimento_resposta and "Erro" not in sentimento_resposta:
            sentimento_limpo = sentimento_resposta.upper().strip().replace(".", "").replace(",", "")
            categorias_validas = ["POSITIVO", "NEGATIVO", "NEUTRO", "CAUTELA"]
            # Verifica se a resposta EXATA é uma das categorias
            if sentimento_limpo in categorias_validas:
                return sentimento_limpo
            else:
                # Tenta um match mais flexível se a IA não seguiu 100% (mas isso é menos ideal)
                for cat in categorias_validas:
                    if cat in sentimento_limpo: # Cuidado com substrings, ex: "NÃO POSITIVO"
                        # Para ser mais seguro, poderia verificar se a resposta *começa* com a categoria
                        if sentimento_limpo.startswith(cat):
                             logger.warning(f"Resposta de sentimento '{sentimento_resposta}' não foi exata, mas '{cat}' foi encontrada.")
                             return cat
                logger.warning(f"Resposta inesperada da Mistral para sentimento: '{sentimento_resposta}'. Retornando NEUTRO.")
                return "NEUTRO" # Fallback se a resposta não for uma das categorias
        
        logger.warning(f"Falha ao obter sentimento da IA. Resposta: {sentimento_resposta}")
        return "NEUTRO (Falha na Análise IA)"

    def identificar_impacto_fiscal(self, texto: str, termos_monitorados: Optional[List[str]] = None) -> str:
        """
        Identifica e lista os principais impactos fiscais, agindo como um consultor fiscal sênior.
        Retorna uma string com os impactos listados em tópicos.
        """
        if not texto:
            return "Texto não fornecido para identificar impactos."

        texto_para_analise = texto[:7000]

        termos_foco_str = ""
        if termos_monitorados:
            termos_foco_str = ", ".join(termos_monitorados)
        else:
            termos_foco_str = "ICMS, PIS, COFINS, IRPJ, CSLL, Simples Nacional, Substituição Tributária, SPED (EFD Contribuições, EFD ICMS/IPI, ECD, ECF), eSocial, DCTFWeb, e notas fiscais eletrônicas."

        system_prompt = (
            "Você é um Consultor Fiscal Sênior altamente experiente, com especialização em legislação tributária brasileira e do Piauí. "
            "Sua principal função é analisar documentos normativos e identificar de forma clara e concisa os impactos fiscais práticos para as empresas."
        )
        user_prompt = (
            f"Com base no texto do documento oficial abaixo, identifique e liste em TÓPICOS (usando '-' para cada tópico) os principais IMPACTOS FISCAIS diretos. "
            f"Seja específico e técnico. Concentre-se em:\n"
            f"1.  Mudanças em alíquotas ou bases de cálculo de tributos (especificar quais tributos e qual a mudança).\n"
            f"2.  Criação, alteração ou extinção de obrigações acessórias (ex: novas declarações, mudanças em leiautes SPED, novas informações a serem prestadas, alterações no eSocial ou EFD-Reinf).\n"
            f"3.  Alterações em prazos para recolhimento de tributos ou entrega de declarações.\n"
            f"4.  Modificações em regimes especiais de tributação, no Simples Nacional, ou em regras de substituição tributária.\n"
            f"5.  Instituição, alteração ou extinção de benefícios fiscais, isenções, créditos presumidos, ou incentivos fiscais.\n"
            f"6.  Novas penalidades ou alterações em multas fiscais relevantes.\n"
            f"7.  Qualquer outro impacto direto na apuração, pagamento ou escrituração de tributos.\n"
            f"Dê atenção especial a impactos relacionados aos termos: {termos_foco_str}.\n\n"
            f"Se nenhum impacto fiscal direto e relevante for identificado no texto fornecido, responda apenas com a frase: 'Nenhum impacto fiscal direto identificado neste documento.'\n\n"
            f"Texto para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
            f"Principais Impactos Fiscais (em tópicos, use '-' para cada):"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # max_tokens para a lista de impactos
        impacto = self._call_mistral(messages, max_tokens=600, temperature=0.2)
        
        if not impacto or "Erro" in impacto:
            logger.warning(f"Falha ao identificar impacto fiscal pela IA ou IA retornou erro: {impacto}.")
            return "Não foi possível identificar os impactos fiscais específicos pela IA."
        return impacto


@Language.component("norma_matcher")
def norma_matcher_component(doc):
    """Componente de pipeline spaCy para identificar normas"""
    return doc

class PDFProcessor:
    def __init__(self):
        self.nlp = None
        self.matcher = None
        self.mistral = MistralAI()
        
        try:
            self._setup_spacy()
        except Exception as e:
            logger.critical(f"Falha CRÍTICA na inicialização de PDFProcessor: {e}", exc_info=True)
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
        mapping = defaultdict(lambda: 'OUTROS')
        mapping['lei'] = 'LEI'
        mapping['leis'] = 'LEI'
        mapping['lei complementar'] = 'LEI'
        mapping['leis complementares'] = 'LEI'
        mapping['decreto'] = 'DECRETO'
        mapping['decretos'] = 'DECRETO'
        mapping['decreto-lei'] = 'DECRETO'
        mapping['portaria'] = 'PORTARIA'
        mapping['portarias'] = 'PORTARIA'
        mapping['resolucao'] = 'RESOLUCAO'
        mapping['resolucoes'] = 'RESOLUCAO'
        mapping['instrucao normativa'] = 'INSTRUCAO'
        mapping['instrução normativa'] = 'INSTRUCAO'
        mapping['instrucao'] = 'INSTRUCAO'

        for choice_key, _ in NormaVigente.TIPO_CHOICES:
            mapping[choice_key.lower()] = choice_key
            
        return mapping
    
    def _get_norma_type_for_model(self, extracted_type_string: str) -> str:
        return self.norma_type_choices_map.get(extracted_type_string.lower().strip(), 'OUTROS')

    def _configure_matchers(self):
        """Configura os matchers para identificação de normas."""
        self.matcher = Matcher(self.nlp.vocab)
        
        self.matcher.add("LEI_PADRAO", [
            [{"LOWER": {"IN": ["lei", "leis"]}}, {"OP": "?"}, {"LOWER": "complementar", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        self.matcher.add("DECRETO_PADRAO", [
            [{"LOWER": {"IN": ["decreto", "decretos"]}}, {"LOWER": "lei", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        self.matcher.add("PORTARIA_PADRAO", [
            [{"LOWER": {"IN": ["portaria", "portarias"]}}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        self.matcher.add("RESOLUCAO_PADRAO", [
            [{"LOWER": {"IN": ["resolucao", "resoluções"]}}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        self.matcher.add("INSTRUCAO_PADRAO", [
            [{"LOWER": {"IN": ["instrucao", "instruções"]}}, {"LOWER": "normativa", "OP": "?"}, 
             {"LOWER": {"IN": ["n", "nº", "n°"]}, "OP": "?"}, {"IS_DIGIT": True}]
        ])
        
        logger.info("Matchers spaCy configurados com sucesso.")

    def _padronizar_numero_norma(self, numero: str) -> str:
        numero = re.sub(r'[^\d./-]', '', str(numero))
        
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
        
        if not patterns:
            return []

        tipo_regex_part = '|'.join(patterns)
        
        padrao_regex = re.compile(
            rf'(?i)({tipo_regex_part})[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\\/]?\d*(?:[\\/]\\d+)*)', 
            re.IGNORECASE
        )
        
        for match in padrao_regex.finditer(texto):
            raw_type = match.group(1)
            numero_raw = match.group(2)
            numero_padronizado = self._padronizar_numero_norma(numero_raw)
            normas.append((raw_type, numero_padronizado))

        return normas

    def extrair_normas(self, texto: str) -> List[Tuple[str, str]]:
        normas_encontradas = []
        
        padrao_norma = re.compile(
            r'(?i)(lei complementar|lei|decreto[\- ]?lei|decreto|ato normativo|portaria|instrução normativa|in)[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\/\-]?\d*(?:[\/\-]\d+)*)',
            re.IGNORECASE
        )
        
        for match in padrao_norma.finditer(texto):
            tipo = match.group(1).upper()
            numero = match.group(2)
            numero = self._padronizar_numero_norma(numero)
            normas_encontradas.append((tipo, numero))
        
        termos_normas = TermoMonitorado.objects.filter(ativo=True, tipo='NORMA')
        for termo in termos_normas:
            termo_regex = re.compile(
                rf'(?i){re.escape(termo.termo)}[\s:]*(?:n[º°o.]?\s*)?(\d+[\.,\/\-]?\d*(?:[\/\-]\d+)*)',
                re.IGNORECASE
            )
            
            for match in termo_regex.finditer(texto):
                numero = match.group(1)
                numero = self._padronizar_numero_norma(numero)
                normas_encontradas.append((termo.termo.split()[0].upper(), numero))
        
        return list(set(normas_encontradas))

    def _identificar_relevancia_geral(self, texto: str) -> int:
        if self.nlp is None or self.matcher is None:
            logger.error("NLP model or Matcher not initialized in _identificar_relevancia_geral.")
            return 0

        doc = self.nlp(texto)
        score = 0
        
        matches = self.matcher(doc)
        for match_id, start, end in matches:
            if self.nlp.vocab.strings[match_id].startswith("CONTABIL_KEYWORD"):
                score += 1
        
        return score

    def is_relevante_contabil(self, texto: str) -> bool:
        texto_lower = texto.lower()
        termos = TermoMonitorado.objects.filter(ativo=True)
        
        for termo in termos:
            if termo.termo.lower() in texto_lower:
                return True
            if termo.variacoes:
                for variacao in [v.strip() for v in termo.variacoes.split(",")]:
                    if variacao and variacao.lower() in texto_lower:
                        return True
        
        # Verificação adicional com Mistral para documentos limítrofes
        try:
            prompt = (
                "Analise se o texto a seguir é relevante para contabilidade/fiscal. "
                "Considere termos técnicos, menções a normas tributárias e impactos financeiros. "
                "Responda apenas com 'SIM' ou 'NÃO'.\n\n"
                f"Texto: {texto[:5000]}"  # Limita o tamanho para a chamada de API
            )
            
            messages = [
                {"role": "system", "content": "Você é um classificador de documentos contábeis."},
                {"role": "user", "content": prompt}
            ]
            
            resposta = self.mistral._call_mistral(messages, model="mistral-tiny", temperature=0.1)
            return resposta.strip().upper() == "SIM"
        except Exception:
            return False

    def _extrair_paragrafos_relevantes(self, texto: str) -> str:
        """Seleciona os parágrafos mais relevantes usando Mistral para priorização"""
        try:
            prompt = (
                "Identifique os 5 parágrafos mais relevantes do texto abaixo para contabilidade/fiscal, "
                "considerando:\n"
                "1. Menções a normas tributárias\n"
                "2. Alterações em obrigações acessórias\n"
                "3. Modificações em alíquotas ou regimes\n"
                "4. Novas exigências ou benefícios fiscais\n\n"
                "Retorne APENAS os parágrafos selecionados, sem comentários ou formatação adicional.\n\n"
                f"Texto:\n{texto[:10000]}"  # Limita o tamanho para a chamada de API
            )
            
            messages = [
                {"role": "system", "content": "Você é um especialista em seleção de conteúdo relevante para contabilidade."},
                {"role": "user", "content": prompt}
            ]
            
            return self.mistral._call_mistral(messages, temperature=0.2)
        except Exception as e:
            logger.error(f"Erro ao extrair parágrafos relevantes com Mistral: {e}")
            # Fallback: pega os maiores parágrafos contendo termos monitorados
            termos = TermoMonitorado.objects.filter(ativo=True)
            termos_busca = set(termo.termo.lower() for termo in termos)
            
            paragrafos = [p.strip() for p in re.split(r'\n{2,}', texto) if p.strip()]
            relevantes = []
            
            for p in paragrafos:
                p_lower = p.lower()
                if any(termo in p_lower for termo in termos_busca):
                    relevantes.append(p)
            
            if not relevantes:
                relevantes = sorted(paragrafos, key=len, reverse=True)[:5]
            
            return "\n\n".join(relevantes)[:6000]

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

            # 2. Extrair parágrafos relevantes com Mistral
            texto_para_resumo = self._extrair_paragrafos_relevantes(texto)

            # 3. Gerar resumo técnico com Mistral
            try:
                resumo_ia = self.mistral.gerar_resumo_contabil(texto_para_resumo)
                sentimento_ia = self.mistral.analisar_sentimento_contabil(texto_para_resumo)
                impacto_fiscal = self.mistral.identificar_impacto_fiscal(texto_para_resumo)
            except Exception as e:
                logger.error(f"Erro ao chamar Mistral API: {e}", exc_info=True)
                resumo_ia = texto_para_resumo[:700] + "..."
                sentimento_ia = "ERRO"
                impacto_fiscal = "Não foi possível analisar os impactos fiscais."

            relevante_contabil = self.is_relevante_contabil(texto)
            documento.relevante_contabil = relevante_contabil
            documento.assunto = "Contábil/Fiscal" if relevante_contabil else "Geral"
            documento.resumo_ia = resumo_ia
            documento.sentimento_ia = sentimento_ia
            documento.impacto_fiscal = impacto_fiscal[:1000]  # Limita o tamanho para o campo no banco

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
                'impacto_fiscal': impacto_fiscal,
            }

        except Exception as e:
            logger.error(f"Erro ao processar documento ID {documento.id}: {e}", exc_info=True)
            documento.processado = True
            documento.save()
            return {'status': 'ERRO', 'message': str(e), 'traceback': traceback.format_exc()}