# monitor/utils/pdf_processor.py
import os
import re
import logging
import traceback
# Remova requests se não for mais usado diretamente aqui
from io import StringIO # Se ainda for usada em algum lugar
from typing import Tuple, List, Dict, Optional
from datetime import datetime
import spacy
from spacy.matcher import Matcher
from spacy.language import Language
# Remova PyPDF2 se não for usado aqui e sim no scraper
from pdfminer.high_level import extract_text as extract_text_to_fp # Verifique se é este ou o extract_text do scraper
from pdfminer.layout import LAParams
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation, ValidationError # Adicionado ValidationError
from django.db import transaction
from django.db.models import Q
from monitor.models import Documento, NormaVigente, TermoMonitorado
from django.utils import timezone
from collections import defaultdict

# Importe a biblioteca da Anthropic
import anthropic # Importe a biblioteca da Anthropic
import time # Para retries

logger = logging.getLogger(__name__)

# Remova as constantes MISTRAL_API_KEY e MISTRAL_API_URL

class ClaudeProcessor:
    def extrair_paragrafos_relevantes_local(self, texto: str) -> str:
        """
        Fallback usando modelo local HuggingFace Transformers para seleção de parágrafos relevantes.
        Seleciona os parágrafos mais prováveis de conter termos contábeis/fiscais monitorados.
        """
        try:
            from transformers import pipeline
        except ImportError:
            logger.warning("Pacote transformers não instalado. Usando fallback por termos monitorados.")
            return self.extrair_paragrafos_relevantes_termos(texto)

        termos = TermoMonitorado.objects.filter(ativo=True)
        termos_busca = set(termo.termo.lower() for termo in termos)
        paragrafos_texto = [p.strip() for p in re.split(r'\n{2,}', texto) if p.strip()]

        # Cria um prompt para cada parágrafo
        perguntas = [
            f"Este parágrafo é relevante para contabilidade/fiscal? Termos: {', '.join(termos_busca)}\nParágrafo: {p}" for p in paragrafos_texto
        ]

        # Usa zero-shot-classification
        try:
            classifier = pipeline("zero-shot-classification", model="pierreguillou/bert-base-cased-pt-br")
        except Exception as e:
            logger.warning(f"Erro ao carregar modelo local transformers: {e}. Usando fallback por termos.")
            return self.extrair_paragrafos_relevantes_termos(texto)

        candidate_labels = ["relevante", "irrelevante"]
        resultados = []
        for pergunta, paragrafo in zip(perguntas, paragrafos_texto):
            try:
                output = classifier(pergunta, candidate_labels)
                score_relevante = output['scores'][output['labels'].index("relevante")]
                resultados.append((score_relevante, paragrafo))
            except Exception as e:
                resultados.append((0, paragrafo))

        # Seleciona os 5 parágrafos mais relevantes
        relevantes = [p for _, p in sorted(resultados, key=lambda x: x[0], reverse=True)[:5]]
        return "\n\n".join(relevantes)[:10000]

    def extrair_paragrafos_relevantes_termos(self, texto: str) -> str:
        """
        Fallback simples por termos monitorados.
        """
        termos = TermoMonitorado.objects.filter(ativo=True)
        termos_busca = set(termo.termo.lower() for termo in termos)
        paragrafos_texto = [p.strip() for p in re.split(r'\n{2,}', texto) if p.strip()]
        relevantes = [p for p in paragrafos_texto if any(termo in p.lower() for termo in termos_busca)]
        if not relevantes:
            relevantes = sorted(paragrafos_texto, key=len, reverse=True)[:5]
        return "\n\n".join(relevantes)[:10000]
    def __init__(self):
        try:
            api_key = getattr(settings, 'ANTHROPIC_API_KEY', os.environ.get("ANTHROPIC_API_KEY"))
            if not api_key:
                raise ValueError("Chave da API Anthropic (Claude) não encontrada nas configurações ou variáveis de ambiente.")
            self.client = anthropic.Anthropic(api_key=api_key)
        except Exception as e:
            logger.error(f"Erro ao inicializar o cliente Anthropic Claude: {e}")
            self.client = None

        self.default_model = "claude-3-haiku-20240307"
        self.default_temperature = 0.2
        self.default_max_tokens = 2048

    def _call_claude(self, system_prompt: str, user_prompt: str, model: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Optional[str]:
        # ... (lógica de _call_claude com retries permanece a mesma que na versão anterior)
        if not self.client:
            logger.error("Cliente Anthropic Claude não inicializado. Verifique a chave da API.")
            return "Erro: Cliente Anthropic Claude não configurado."

        placeholders_de_chave_comuns = ["sk-ant-api03-xxxx", "COLOQUE_SUA_CHAVE_AQUI_CLAUDE"] #
        if self.client.api_key and any(placeholder in self.client.api_key for placeholder in placeholders_de_chave_comuns if "xxxx" in placeholder): #
             logger.warning(
                f"Chave da API Claude parece ser um placeholder genérico."
            )

        max_retries = 2
        base_wait_time = 5
        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=model or self.default_model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    temperature=temperature if temperature is not None else self.default_temperature,
                    max_tokens=max_tokens or self.default_max_tokens
                )
                if response.content and isinstance(response.content, list) and len(response.content) > 0:
                    block = response.content[0]
                    if hasattr(block, 'text'):
                        content = block.text
                        logger.debug(f"Resposta da API Claude: {content[:200]}...")
                        return content
                elif response.content and isinstance(response.content, str):
                    logger.debug(f"Resposta da API Claude: {response.content[:200]}...")
                    return response.content
                else:
                    logger.error("Resposta inesperada da API Claude.")
                    return None
            except Exception as e:
                logger.error(f"Erro ao chamar Claude API (tentativa {attempt+1}/{max_retries}): {e}")
                time.sleep(base_wait_time * (attempt + 1))
        logger.error("Falha ao obter resposta da API Claude após múltiplas tentativas.")
        return "Erro API Claude"

    def gerar_resumo_contabil(self, texto_relevante: str, termos_monitorados: Optional[List[str]] = None) -> str:
        # Prioriza parágrafos relevantes por termos
        relevantes_termos = self.extrair_paragrafos_relevantes_termos(texto_relevante)
        if relevantes_termos and len(relevantes_termos.strip()) > 0:
            texto_para_analise = relevantes_termos[:15000]
        else:
            # Se não houver por termos, tenta IA Claude
            if self.client:
                texto_para_analise = texto_relevante[:15000]
                termos_foco_str = ", ".join(termos_monitorados) if termos_monitorados else "aspectos fiscais e contábeis gerais relevantes para empresas no Piauí, incluindo ICMS, PIS, COFINS, IRPJ, CSLL, Simples Nacional, substituição tributária, e obrigações acessórias (SPED, EFD)."
                system_prompt = (
                    "Você é um Contador Sênior e Consultor Tributário altamente experiente..."
                )
                user_prompt = (
                    f"Com base nos parágrafos MAIS RELEVANTES do documento oficial fornecido abaixo, elabore um RESUMO TÉCNICO CONTÁBIL/FISCAL..."
                    f"DESTAQUE OBRIGATORIAMENTE OS SEGUINTES PONTOS (se presentes e relevantes no texto fornecido):\n"
                    f"1.  **Normas Referenciadas e Natureza da Mudança:** Liste as principais normas mencionadas (Leis, Decretos, Portarias, INs, etc.) com seus números e anos. Especifique se o documento institui uma nova norma, altera uma existente (quais artigos/seções), revoga, ou regulamenta.\n"
                    f"2.  **Alterações Legais Relevantes:** Descreva as modificações de regras mais significativas que o documento introduz.\n"
                    f"3.  **Principais Impactos Contábeis e Fiscais:** Detalhe os efeitos práticos para as empresas e para a apuração de tributos (ex: mudanças em alíquotas, base de cálculo, crédito/débito, novas obrigações, isenções, regimes especiais).\n"
                    f"4.  **Prazos e Obrigações Importantes:** Se houver menção a prazos para cumprimento de novas obrigações, adaptação a novas regras, ou para usufruir de benefícios, liste-os claramente.\n"
                    f"5.  **Consequências Práticas e Ações Recomendadas (se explícito no texto):** Se o texto sugerir ações, mencione-as brevemente.\n\n"
                    f"CONCENTRE-SE PARTICULARMENTE em como o documento se relaciona com os seguintes termos/conceitos, se mencionados: {termos_foco_str}.\n\n"
                    f"PRIORIZE: Precisão, relevância para a prática contábil/fiscal, e clareza. Evite especulações ou informações não contidas explicitamente no texto. Não adicione introduções ou conclusões genéricas.\n"
                    f"Se o documento não contiver informações diretamente relevantes para os pontos acima, responda: 'Nenhuma informação contábil/fiscal crítica identificada no escopo solicitado neste documento.'\n\n"
                    f"Texto (parágrafos mais relevantes) para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
                    f"Resumo Técnico Contábil/Fiscal Estruturado:"
                )
                resposta_ia = self._call_claude(system_prompt, user_prompt, max_tokens=700, temperature=0.25)
                if resposta_ia and "Erro API Claude" not in resposta_ia and "Erro: Cliente Anthropic Claude" not in resposta_ia:
                    return resposta_ia
                else:
                    logger.warning(f"Falha ao gerar resumo pela API Claude ou API retornou erro: {resposta_ia}. Usando IA local ou texto bruto.")
                    return self.extrair_paragrafos_relevantes_local(texto_relevante)[:700] + "..."
            else:
                # Fallback IA local
                return self.extrair_paragrafos_relevantes_local(texto_relevante)[:700] + "..."
        # Se chegou aqui, retorna o texto analisado por termos
        return texto_para_analise

    def analisar_sentimento_contabil(self, texto_relevante: str) -> str:
        # Prioriza parágrafos relevantes por termos
        relevantes_termos = self.extrair_paragrafos_relevantes_termos(texto_relevante)
        texto_para_analise = relevantes_termos[:4000] if relevantes_termos and len(relevantes_termos.strip()) > 0 else texto_relevante[:4000]

        categorias_validas = ["POSITIVO", "NEGATIVO", "NEUTRO", "CAUTELA"]

        if self.client:
            system_prompt = (
                "Você é um analista regulatório sênior..."
            )
            user_prompt = (
                f"Analise os parágrafos MAIS RELEVANTES do documento oficial abaixo exclusivamente sob a perspectiva contábil/fiscal..."
                f"Classifique o impacto geral do documento para as empresas/contadores em UMA ÚNICA PALAVRA das seguintes categorias:\n"
                f"-   **POSITIVO**: (Se o documento predominantemente simplifica processos, reduz carga tributária de forma clara, oferece benefícios ou incentivos fiscais significativos, ou facilita o compliance de maneira notável).\n"
                f"-   **NEGATIVO**: (Se o documento predominantemente introduz novas obrigações complexas ou onerosas, aumenta a carga tributária de forma clara, impõe restrições significativas, ou eleva consideravelmente o risco de penalidades).\n"
                f"-   **NEUTRO**: (Se o documento é majoritariamente informativo, mantém o status quo, as alterações são meramente técnicas/procedimentais sem grande alteração de ônus, ou os impactos fiscais/contábeis são mínimos).\n"
                f"-   **CAUTELA**: (Se o documento introduz ambiguidades legais significativas, aumenta substancialmente a complexidade interpretativa da legislação, ou se os impactos são incertos mas potencialmente relevantes e exigem uma análise aprofundada e cuidadosa antes de qualquer ação).\n\n"
                f"Texto (parágrafos mais relevantes) para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
                f"Responda APENAS com UMA das quatro categorias listadas (POSITIVO, NEGATIVO, NEUTRO, CAUTELA), em letras maiúsculas. NÃO inclua nenhuma outra palavra, pontuação, explicação ou frase adicional."
            )
            sentimento_resposta = self._call_claude(system_prompt, user_prompt, model="claude-3-haiku-20240307", max_tokens=10, temperature=0.05)
            if sentimento_resposta and "Erro API Claude" not in sentimento_resposta and "Erro: Cliente Anthropic Claude" not in sentimento_resposta:
                sentimento_limpo = sentimento_resposta.upper().strip().replace(".", "").replace(",", "")
                if sentimento_limpo in categorias_validas:
                    return sentimento_limpo
                else:
                    for cat in categorias_validas:
                        if sentimento_limpo.startswith(cat):
                            logger.warning(f"Resposta de sentimento '{sentimento_resposta}' não foi exata, mas '{cat}' foi encontrada.")
                            return cat
                    logger.warning(f"Resposta inesperada da API Claude para sentimento: '{sentimento_resposta}'. Retornando NEUTRO.")
                    return "NEUTRO"
            else:
                logger.warning(f"Falha ao obter sentimento da API Claude. Resposta: {sentimento_resposta}. Usando IA local ou NEUTRO.")
                return "NEUTRO (Falha na Análise IA)"
        # Fallback: NEUTRO
        return "NEUTRO"

    def identificar_impacto_fiscal(self, texto_relevante: str, termos_monitorados: Optional[List[str]] = None) -> str:
        # Prioriza parágrafos relevantes por termos
        relevantes_termos = self.extrair_paragrafos_relevantes_termos(texto_relevante)
        texto_para_analise = relevantes_termos[:8000] if relevantes_termos and len(relevantes_termos.strip()) > 0 else texto_relevante[:8000]

        if self.client:
            termos_foco_str = ", ".join(termos_monitorados) if termos_monitorados else "ICMS, PIS, COFINS, IRPJ, CSLL, Simples Nacional, Substituição Tributária, SPED (EFD Contribuições, EFD ICMS/IPI, ECD, ECF), eSocial, DCTFWeb, e notas fiscais eletrônicas."
            system_prompt = (
                "Você é um Consultor Fiscal Sênior altamente experiente..."
            )
            user_prompt = (
                f"Com base nos parágrafos MAIS RELEVANTES do documento oficial abaixo, identifique e liste em TÓPICOS (usando '-' para cada tópico) os principais IMPACTOS FISCAIS diretos..."
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
                f"Texto (parágrafos mais relevantes) para análise:\n\"\"\"\n{texto_para_analise}\n\"\"\"\n\n"
                f"Principais Impactos Fiscais (em tópicos, use '-' para cada):"
            )
            impacto = self._call_claude(system_prompt, user_prompt, max_tokens=700, temperature=0.2)
            if impacto and "Erro API Claude" not in impacto and "Erro: Cliente Anthropic Claude" not in impacto:
                return impacto
            else:
                logger.warning(f"Falha ao identificar impacto fiscal pela API Claude ou API retornou erro: {impacto}. Usando IA local ou texto bruto.")
                return self.extrair_paragrafos_relevantes_local(texto_relevante)[:700] + "..."
        # Fallback IA local
        return self.extrair_paragrafos_relevantes_local(texto_relevante)[:700] + "..."


    def _extrair_paragrafos_relevantes(self, texto: str) -> str:
        # 1. Busca por termos monitorados
        relevantes_termos = self.extrair_paragrafos_relevantes_termos(texto)
        if relevantes_termos and len(relevantes_termos.strip()) > 0:
            logger.info("Parágrafos relevantes encontrados por termos monitorados.")
            return relevantes_termos

        # 2. Tenta IA Claude
        if self.client:
            texto_para_analise = texto[:10000]
            system_prompt = "Você é um especialista em seleção de conteúdo jurídico-fiscal relevante para contabilidade, com foco em documentos do Piauí."
            user_prompt = (
                "Analise o texto completo fornecido abaixo. Identifique e retorne APENAS os 5 (cinco) parágrafos que você considera os MAIS RELEVANTES para um contador ou analista fiscal, "
                "focando em menções a: nomes de tributos (ICMS, ISS, PIS, COFINS, IRPJ, CSLL, etc.), alíquotas, bases de cálculo, obrigações acessórias (SPED, EFD, DCTF, etc.), prazos, penalidades, benefícios fiscais, "
                "ou qualquer alteração direta na legislação tributária ou contábil do Piauí. "
                "Não adicione introduções, conclusões ou qualquer texto seu. Apenas os parágrafos selecionados, separados por uma linha em branco dupla (uma quebra de linha extra entre eles).\n\n"
                f"Texto:\n{texto_para_analise}"
            )
            paragrafos_selecionados = self._call_claude(system_prompt, user_prompt, temperature=0.1, max_tokens=2000)
            if paragrafos_selecionados and "Erro API Claude" not in paragrafos_selecionados and "Erro: Cliente Anthropic Claude" not in paragrafos_selecionados:
                logger.info("Parágrafos relevantes encontrados pela IA Claude.")
                return paragrafos_selecionados
            else:
                logger.error(f"Erro ao extrair parágrafos relevantes com API Claude: {paragrafos_selecionados}. Tentando IA local.")

        # 3. Fallback IA local
        logger.info("Nenhum parágrafo relevante encontrado por termos ou IA Claude. Usando IA local.")
        return self.extrair_paragrafos_relevantes_local(texto)


@Language.component("norma_matcher")
def norma_matcher_component(doc):
    return doc

class PDFProcessor:
    def processar_apenas_dois_documentos(self):
        """
        Função temporária para testes: processa apenas dois documentos e exibe as normas extraídas.
        """
        from monitor.models import Documento
        docs = Documento.objects.all()[:1]
        resultados = []
        for doc in docs:
            print(f"Processando documento ID: {doc.id}, Título: {doc.titulo}")
            normas = self.extrair_normas(doc.texto_completo or "")
            print(f"Normas extraídas: {normas}")
            resultado = self.process_document(doc)
            resultados.append(resultado)
        print("Resultados do processamento:", resultados)
        return resultados
    def __init__(self):
        self.nlp = None
        self.matcher = None
        self.claude_processor = ClaudeProcessor()
        try:
            self._setup_spacy()
        except Exception as e:
            logger.critical(f"Falha CRÍTICA na inicialização de PDFProcessor: {e}", exc_info=True)
            self.nlp = None
        self.norma_type_choices_map = self._get_norma_type_choices_map()


    def _setup_spacy(self): #
        try: #
            self.nlp = spacy.load("pt_core_news_sm") #
            self._configure_matchers() #
            logger.info("Modelo spaCy 'pt_core_news_sm' carregado com sucesso para uso.") #
        except OSError: #
            logger.warning("Modelo spaCy 'pt_core_news_sm' não encontrado. Baixando...") #
            spacy.cli.download("pt_core_news_sm") #
            self.nlp = spacy.load("pt_core_news_sm") #
            self._configure_matchers() #
            logger.info("Modelo spaCy 'pt_core_news_sm' baixado e carregado com sucesso para uso.") #
        except Exception as e: #
            logger.error(f"Erro ao carregar ou configurar spaCy: {e}", exc_info=True) #
            self.nlp = None #

    def _get_norma_type_choices_map(self): #
        mapping = defaultdict(lambda: 'OUTROS') #
        map_data = { #
            'lei': 'LEI', 'leis': 'LEI', 'lei complementar': 'LEI', #
            'leis complementares': 'LEI', 'lc': 'LEI', #
            'decreto': 'DECRETO', 'decretos': 'DECRETO', 'decreto-lei': 'DECRETO', #
            'portaria': 'PORTARIA', 'portarias': 'PORTARIA', #
            'resolucao': 'RESOLUCAO', 'resolucoes': 'RESOLUCAO', 'resolução': 'RESOLUCAO', #
            'instrucao normativa': 'INSTRUCAO', 'instrução normativa': 'INSTRUCAO', #
            'instrucao': 'INSTRUCAO', 'in': 'INSTRUCAO', #
            'ato normativo': 'ATO_NORMATIVO' #
        } #
        for key, value in map_data.items(): #
            mapping[key] = value #

        for choice_key, _ in NormaVigente.TIPO_CHOICES: #
            mapping[choice_key.lower()] = choice_key #
        return mapping #
    
    def _get_norma_type_for_model(self, extracted_type_string: str) -> str: # Não usado no código atual, mas mantido.
        return self.norma_type_choices_map.get(extracted_type_string.lower().strip(), 'OUTROS') #

    def _configure_matchers(self): #
        if not self.nlp: #
            logger.warning("spaCy (nlp) não está carregado. Matchers não serão configurados.") #
            self.matcher = None #
            return #
            
        self.matcher = Matcher(self.nlp.vocab) #
        logger.info("Matchers spaCy configurados (ou tentativa de configurar, se padrões fossem adicionados).") #

    def _padronizar_numero_norma(self, numero: str) -> str: #
        numero_input = str(numero) #
        numero_limpo = re.sub(r'[^\d./-]', '', numero_input) #

        if not numero_limpo or not re.search(r'\d', numero_limpo): #
            return "" #

        parts = re.split(r'([./-])', numero_limpo) #
        final_parts = [] #
        for part in parts: #
            if part.isdigit(): #
                stripped_part = part.lstrip('0') #
                final_parts.append(stripped_part if stripped_part else '0') #
            elif part in ('/', '.', '-'): #
                final_parts.append(part) #
        
        numero_processado = "".join(final_parts) #
        numero_final = numero_processado.strip('./-') #
        return numero_final #
    
    def _extrair_ano_norma(self, numero_norma: str) -> Optional[int]: #
        match_ano_4_digitos = re.search(r'/(\d{4})\b', numero_norma) #
        if match_ano_4_digitos: #
            return int(match_ano_4_digitos.group(1)) #
        
        match_ano_2_digitos = re.search(r'/(\d{2})\b', numero_norma) #
        if match_ano_2_digitos: #
            ano_curto = int(match_ano_2_digitos.group(1)) #
            return 2000 + ano_curto if ano_curto < 50 else 1900 + ano_curto #
        return None #



    def extrair_normas(self, texto: str) -> List[Tuple[str, str]]:
        normas_encontradas_set = set()
        
        # Regex ajustado para melhor separação de tipo e número
        # group(1) = tipo da norma
        # group(2) = número completo da norma, incluindo ano se junto
        padrao_norma = re.compile(
            r'(?i)\b(lei\scomplementar|lei\sordin[áa]ria|lei|decreto-lei|decreto|portaria|resolu[cç][ãa]o|instru[cç][ãa]o\snormativa|ato\snormativo|IN\b|LC\b|EC\b|MP\b|ADE\b)\s+'
            r'(?:n[º°\.\s]*|n[º°]?\s*)?' # Permite "nº ", "n. ", "n ", ou só o número
            r'([\d]+(?:[\.,\/\-]\d+)*[\w]*)', # Número: dígitos, pontos, barras, hífens, opcionalmente terminando com letra
            re.IGNORECASE
        )
        for match in padrao_norma.finditer(texto):
            tipo_bruto = match.group(1).strip()
            numero_bruto = match.group(2).strip()
            tipo_normalizado = self.norma_type_choices_map.get(tipo_bruto.lower(), 'OUTROS')
            numero_padronizado = self._padronizar_numero_norma(numero_bruto)
            ano_norma = self._extrair_ano_norma(numero_padronizado)
            valid_tipos = [choice[0] for choice in NormaVigente.TIPO_CHOICES]
            if tipo_normalizado not in valid_tipos:
                logger.warning(f"Tipo de norma '{tipo_bruto}' normalizado para '{tipo_normalizado}' não é um TIPO_CHOICES válido. Marcando como OUTROS ou ignorando. Número: {numero_padronizado}")
            if numero_padronizado:
                # Remove ano duplicado do número se já estiver presente
                # Corrige duplicidade de ano: só adiciona o ano se não estiver presente no final
                if ano_norma:
                    # Se o número já termina com /ano, não adiciona novamente
                    if re.search(rf'/({ano_norma})$', numero_padronizado):
                        normas_encontradas_set.add((tipo_normalizado, numero_padronizado))
                    else:
                        # Remove qualquer ano no final antes de adicionar
                        numero_sem_ano = re.sub(r'/\d{4}$', '', numero_padronizado)
                        normas_encontradas_set.add((tipo_normalizado, f"{numero_sem_ano}/{ano_norma}"))
                else:
                    normas_encontradas_set.add((tipo_normalizado, numero_padronizado))
            else:
                logger.warning(f"Número de norma '{numero_bruto}' resultou em vazio após padronização para tipo '{tipo_normalizado}'.")

        # ... (resto da lógica com TermoMonitorado permanece igual)
        termos_normas_db = TermoMonitorado.objects.filter(ativo=True, tipo='NORMA') #
        for termo_db in termos_normas_db: #
            if termo_db.variacoes: #
                numeros_especificos = [self._padronizar_numero_norma(n.strip()) for n in termo_db.variacoes.split(',')] #
                for num_esp in numeros_especificos: #
                    if not num_esp: continue #
                    padrao_especifico = rf'(?i)\b{re.escape(num_esp)}\b' #
                    if re.search(padrao_especifico, texto): #
                        # Garante que o tipo do TermoMonitorado seja um tipo válido do modelo
                        tipo_termo_normalizado = self.norma_type_choices_map.get(termo_db.termo.lower(), 'OUTROS')
                        normas_encontradas_set.add((tipo_termo_normalizado, num_esp))
        
        logger.info(f"Extração por regex encontrou {len(normas_encontradas_set)} normas únicas.") #
        return list(normas_encontradas_set) #



    def is_relevante_contabil(self, texto: str, termos_monitorados: Optional[List[str]] = None) -> bool:
        """
        Verifica se o texto é relevante usando explicitamente os termos monitorados como parâmetro.
        Se não fornecido, busca os termos monitorados ativos do banco.
        """
        texto_lower = texto.lower()
        if termos_monitorados is None:
            termos_objs = TermoMonitorado.objects.filter(ativo=True, tipo='TEXTO')
            termos_monitorados = [termo.termo for termo in termos_objs]
            variacoes = []
            for termo in termos_objs:
                if termo.variacoes:
                    variacoes.extend([v.strip() for v in termo.variacoes.split(",") if v.strip()])
            termos_monitorados.extend(variacoes)

        # Busca direta por termos monitorados e variações
        for termo in termos_monitorados:
            if termo.lower() in texto_lower:
                logger.debug(f"Documento relevante encontrado pelo termo monitorado: {termo}")
                return True

        # Fallback IA
        if self.claude_processor and self.claude_processor.client:
            logger.debug("Nenhum termo monitorado encontrado. Consultando IA (Claude)...")
            system_prompt_relevancia = "Você é um classificador especialista em identificar a relevância de documentos para as áreas contábil e fiscal."
            termos_str = ', '.join(termos_monitorados)
            user_prompt_relevancia = (
                f"Analise se o texto a seguir é relevante para as áreas de contabilidade ou fiscal de empresas no Brasil, especialmente no estado do Piauí. "
                f"Considere os seguintes termos monitorados: {termos_str}. "
                "Responda APENAS com 'SIM' ou 'NÃO'.\n\n"
                f"Texto (primeiros 8000 caracteres para análise rápida):\n {texto[:8000]}"
            )
            resposta = self.claude_processor._call_claude(system_prompt_relevancia, user_prompt_relevancia, model="claude-3-haiku-20240307", temperature=0.1, max_tokens=5)
            if resposta and "SIM" in resposta.upper():
                logger.debug(f"IA (Claude) classificou como relevante. Resposta: {resposta}")
                return True
            logger.debug(f"IA (Claude) classificou como NÃO relevante ou houve erro. Resposta: {resposta}")
        return False

    def _extrair_paragrafos_relevantes(self, texto: str) -> str:
        """
        Chama o método de extração de parágrafos relevantes da instância ClaudeProcessor.
        """
        return self.claude_processor._extrair_paragrafos_relevantes(texto)

    def process_document(self, documento: Documento) -> Dict[str, any]:
        # ... (a lógica de process_document com as correções anteriores para ValidationError e UnboundLocalError)
        # ... (e as chamadas corretas para self.claude_processor)
        logger.info(f"Processando documento ID: {documento.id}, Título: {documento.titulo[:50]}...") #

        if not documento.texto_completo: #
            logger.warning(f"Documento ID {documento.id} não possui texto completo. Pulando processamento.") #
            documento.processado = True #
            documento.relevante_contabil = False #
            documento.resumo_ia = "Texto completo ausente, não foi possível processar." #
            documento.sentimento_ia = "NEUTRO" #
            documento.impacto_fiscal = "Não aplicável." #
            documento.save(update_fields=['processado', 'relevante_contabil', 'resumo_ia', 'sentimento_ia', 'impacto_fiscal']) #
            return {'status': 'FALHA', 'message': 'Texto completo ausente.'} #

        try: #
            texto = documento.texto_completo #
            normas_extraidas_tuplas = self.extrair_normas(texto) #
            normas_objs_para_relacionar = [] #
            normas_strings_para_resumo = [] #

            for tipo_norma_ext, numero_norma_processado in normas_extraidas_tuplas: #
                if not numero_norma_processado or len(numero_norma_processado) < 1: #
                    logger.warning(f"Norma ignorada (em process_document) por número inválido ou muito curto: tipo={tipo_norma_ext}, numero='{numero_norma_processado}'") #
                    continue #
                ano_norma = self._extrair_ano_norma(numero_norma_processado) #
                valid_tipos = [choice[0] for choice in NormaVigente.TIPO_CHOICES] #
                tipo_final = tipo_norma_ext if tipo_norma_ext in valid_tipos else 'OUTROS' #
                ementa_modelo_default_field = NormaVigente._meta.get_field('ementa') #
                ementa_para_defaults = ementa_modelo_default_field.default #
                if callable(ementa_para_defaults): #
                    ementa_para_defaults = ementa_para_defaults() #
                try: #
                    norma_obj = NormaVigente.objects.filter( #
                        tipo=tipo_final, #
                        numero=numero_norma_processado, #
                        ano=ano_norma #
                    ).first() #
                    if not norma_obj: #
                        norma_obj = NormaVigente.objects.create( #
                            tipo=tipo_final, #
                            numero=numero_norma_processado, #
                            ano=ano_norma, #
                            data_ultima_mencao=documento.data_publicacao, #
                            ementa=ementa_para_defaults, #
                            situacao='A_VERIFICAR' #
                        ) #
                        norma_obj.ementa = f"Extraída do documento '{documento.titulo}'" #
                        norma_obj.save(update_fields=['ementa']) #
                    elif documento.data_publicacao: #
                        if not norma_obj.data_ultima_mencao or documento.data_publicacao > norma_obj.data_ultima_mencao: #
                            norma_obj.data_ultima_mencao = documento.data_publicacao #
                            norma_obj.save(update_fields=['data_ultima_mencao']) #
                    normas_objs_para_relacionar.append(norma_obj) #
                    normas_strings_para_resumo.append(f"{norma_obj.get_tipo_display()} {norma_obj.numero}" + (f"/{norma_obj.ano}" if norma_obj.ano else "")) #
                except ValidationError as e_val: #
                    logger.error(f"Erro de VALIDAÇÃO ao criar/obter NormaVigente para tipo={tipo_final}, numero={numero_norma_processado}, ano={ano_norma}: {e_val.message_dict if hasattr(e_val, 'message_dict') else e_val}", exc_info=False) #
                    continue #
                except Exception as e_norma:  #
                    logger.error(f"Erro GENÉRICO ao criar/obter NormaVigente para tipo={tipo_final}, numero={numero_norma_processado}, ano={ano_norma}: {e_norma}", exc_info=True) #
                    continue #



            termos_monitorados_ativos = list(TermoMonitorado.objects.filter(ativo=True, tipo='TEXTO').values_list('termo', flat=True))
            relevante_contabil = self.is_relevante_contabil(texto, termos_monitorados_ativos)
            documento.relevante_contabil = relevante_contabil
            documento.assunto = "Contábil/Fiscal" if relevante_contabil else "Geral"

            if relevante_contabil:
                logger.info(f"Documento ID {documento.id} é relevante. Prosseguindo com análise IA detalhada.")
                paragrafos_relevantes = self._extrair_paragrafos_relevantes(texto)
                documento.resumo_ia = self.claude_processor.gerar_resumo_contabil(paragrafos_relevantes, termos_monitorados_ativos)
                documento.sentimento_ia = self.claude_processor.analisar_sentimento_contabil(paragrafos_relevantes)
                impacto_fiscal_texto = self.claude_processor.identificar_impacto_fiscal(paragrafos_relevantes, termos_monitorados_ativos)
                # Limpeza e corte inteligente para campo impacto_fiscal
                def limpar_e_cortar_impacto(texto, limite=500):
                    # Remove cabeçalhos e repetições comuns
                    texto = re.sub(r'(?i)\b(DECRETOS?|PORTARIAS?|_DECRETOS_|_PORTARIAS_|LEIS|_LEIS_)\b\s*', '', texto)
                    # Remove transcrições administrativas e notas de rodapé
                    texto = re.sub(r'\(Transcrição da nota.*?\)', '', texto, flags=re.IGNORECASE)
                    # Remove nomes de servidores e matrículas (padrão comum)
                    texto = re.sub(r'(Policial Penal|Agente de Polícia Civil|SD PM|Sargento QPPM|Professor Adjunto|Comunicadora Social|Assistente Social|Secretária Municipal|Secretaria da Justiça|Secretaria da Segurança Pública|Secretaria de Estado da Educação|Fundação Universidade Estadual|Hospital Getúlio Vargas|Secretaria do Desenvolvimento e Assistência Social|Secretaria de Comunicação Social|Secretaria de Estado da Saúde|Assembleia Legislativa do Estado do Piauí|Gabinete da Deputada Ana Paula|CB PM|RGPM|CPF|Matrícula|Quadro de pessoal)[^\.\n]*[\.\n]', '', texto, flags=re.IGNORECASE)
                    # Remove linhas em caixa alta que não sejam normas
                    texto = re.sub(r'^[A-Z\s]{8,}$', '', texto, flags=re.MULTILINE)
                    # Remove múltiplas quebras de linha
                    texto = re.sub(r'\n{2,}', '\n', texto)
                    # Prioriza trechos que mencionam termos fiscais
                    termos_fiscais = r'(ICMS|CFOP|benefício fiscal|crédito fiscal|apuração|tributação|imposto|EFD|NF-e|Decreto|Portaria|Lei Complementar|Convênio ICMS|alíquota|base de cálculo|penalidade|incentivo fiscal|regulamentar|homologação|prazo|operações|apuração|tributos)'
                    paragrafos = [p.strip() for p in re.split(r'\n{1,}', texto) if p.strip()]
                    relevantes = [p for p in paragrafos if re.search(termos_fiscais, p, re.IGNORECASE)]
                    # Se não encontrar, pega os maiores
                    if not relevantes:
                        relevantes = sorted(paragrafos, key=len, reverse=True)[:3]
                    texto_final = '\n'.join(relevantes)
                    # Corta no final de frase ou parágrafo mais próximo do limite
                    if len(texto_final) > limite:
                        corte = max(texto_final.rfind('.', 0, limite), texto_final.rfind('\n', 0, limite))
                        if corte > 0:
                            texto_final = texto_final[:corte+1]
                        else:
                            texto_final = texto_final[:limite]
                        texto_final = texto_final.rstrip() + '...'
                    return texto_final.strip()
                documento.impacto_fiscal = limpar_e_cortar_impacto(impacto_fiscal_texto) if impacto_fiscal_texto else None
                documento.metadata = {
                    'ia_modelo_usado': self.claude_processor.default_model,
                    'ia_relevancia_justificativa': "Analisado como relevante pela IA e/ou termos monitorados.",
                    'ia_pontos_criticos': ["Verificar detalhes no resumo e impacto fiscal gerados pela IA."]
                }
            else:
                logger.info(f"Documento ID {documento.id} NÃO é relevante. Análise IA detalhada pulada.")
                documento.resumo_ia = "Documento não classificado como relevante para análise contábil/fiscal detalhada."
                documento.sentimento_ia = "NEUTRO"
                documento.impacto_fiscal = "Não aplicável."
                documento.metadata = {'ia_relevancia_justificativa': "Analisado como não relevante após verificação inicial e/ou IA."}

            documento.processado = True #
            documento.data_processamento = timezone.now() #
            documento.save() #

            if normas_objs_para_relacionar: #
                documento.normas_relacionadas.set(normas_objs_para_relacionar) #
            
            logger.info(f"Documento ID {documento.id} processado. Relevante: {relevante_contabil}. Normas relacionadas: {len(normas_objs_para_relacionar)}") #
            return { #
                'status': 'SUCESSO' if relevante_contabil else 'IGNORADO_IRRELEVANTE', #
                'message': 'Documento processado.', #
                'relevante_contabil': relevante_contabil, #
                'normas_extraidas': normas_strings_para_resumo, #
                'resumo_ia': documento.resumo_ia, #
                'sentimento_ia': documento.sentimento_ia, #
                'impacto_fiscal': documento.impacto_fiscal, #
            } #

        except Exception as e: #
            logger.error(f"Erro crítico ao processar documento ID {documento.id}: {e}", exc_info=True) #
            documento.processado = True #
            documento.relevante_contabil = False #
            documento.resumo_ia = f"Erro durante o processamento: {str(e)}" #
            documento.sentimento_ia = "ERRO_PROCESSAMENTO" #
            documento.impacto_fiscal = f"Erro: {str(e)}" #
            documento.save(update_fields=['processado', 'relevante_contabil', 'resumo_ia', 'sentimento_ia', 'impacto_fiscal']) #
            return {'status': 'ERRO', 'message': str(e), 'traceback': traceback.format_exc()} #