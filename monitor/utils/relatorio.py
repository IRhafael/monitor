import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Tuple
import re
from django.conf import settings
from django.db.models import Count, Q, Max, Min, Avg, F, Case, When, Value, CharField
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from openpyxl.drawing.image import Image
from monitor.models import Documento, NormaVigente, TermoMonitorado, RelatorioGerado


# Importações para IA gratuita
try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
    IA_DISPONIVEL = True
except ImportError:
    IA_DISPONIVEL = False
    print("⚠️ Bibliotecas de IA não instaladas. Para usar IA gratuita, instale: pip install transformers torch")

from monitor.models import Documento, NormaVigente

logger = logging.getLogger(__name__)

class IAGratuita:
    """Classe para integração com modelos de IA gratuitos"""
    
    def __init__(self):
        self.resumidor = None
        self.analisador_sentimento = None
        self.extrator_keywords = None
        self._inicializar_modelos()
    
    def _inicializar_modelos(self):
        """Inicializa os modelos de IA gratuitos"""
        if not IA_DISPONIVEL:
            logger.warning("Bibliotecas de IA não disponíveis. Funcionalidades limitadas.")
            return
        
        try:
            # Modelo para resumos em português (leve e eficiente)
            self.resumidor = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",  # Modelo em inglês, mas funciona bem
                tokenizer="facebook/bart-large-cnn",
                device=-1  # CPU (use 0 para GPU se disponível)
            )
            
            # Alternativa em português (se disponível)
            # self.resumidor = pipeline("summarization", model="pierreguillou/gpt2-small-portuguese")
            
            # Analisador de sentimento
            self.analisador_sentimento = pipeline(
                "sentiment-analysis",
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
                device=-1
            )
            
            logger.info("✅ Modelos de IA inicializados com sucesso")
            
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar modelos de IA: {e}")
            self.resumidor = None
            self.analisador_sentimento = None
    
    def gerar_resumo_inteligente(self, texto, max_length=150):
        """Gera resumo inteligente usando IA gratuita"""
        if not self.resumidor or not texto:
            return self._resumo_fallback(texto, max_length)
        
        try:
            # Limpa e prepara o texto
            texto_limpo = self._limpar_texto_para_ia(texto)
            
            # Se o texto for muito curto, retorna como está
            if len(texto_limpo.split()) < 20:
                return texto_limpo
            
            # Gera resumo com IA
            resultado = self.resumidor(
                texto_limpo,
                max_length=max_length,
                min_length=30,
                do_sample=False,
                truncation=True
            )
            
            resumo = resultado[0]['summary_text']
            
            # Pós-processamento
            resumo = self._pos_processar_resumo(resumo)
            
            logger.debug(f"✅ Resumo IA gerado: {len(resumo)} chars")
            return resumo
            
        except Exception as e:
            logger.error(f"❌ Erro na geração de resumo IA: {e}")
            return self._resumo_fallback(texto, max_length)
    
    def extrair_palavras_chave_ia(self, texto, num_palavras=10):
        """Extrai palavras-chave usando técnicas de IA"""
        if not texto:
            return []
        
        try:
            # Método 1: TF-IDF simples (sempre disponível)
            palavras_chave = self._extrair_tfidf(texto, num_palavras)
            
            # Método 2: Se IA disponível, refinamento com análise semântica
            if self.resumidor:
                palavras_chave = self._refinar_palavras_chave_ia(texto, palavras_chave)
            
            return palavras_chave[:num_palavras]
            
        except Exception as e:
            logger.error(f"❌ Erro na extração de palavras-chave: {e}")
            return self._extrair_palavras_chave_basico(texto)
    
    def analisar_sentimento_documento(self, texto):
        """Analisa o sentimento/tom do documento"""
        if not self.analisador_sentimento or not texto:
            return {"sentimento": "neutro", "confianca": 0.5}
        
        try:
            # Pega uma amostra do texto (modelos têm limite de tokens)
            amostra = texto[:500]
            
            resultado = self.analisador_sentimento(amostra)
            
            # Mapeia labels para português
            mapeamento = {
                'POSITIVE': 'positivo',
                'NEGATIVE': 'negativo', 
                'NEUTRAL': 'neutro',
                'LABEL_0': 'negativo',
                'LABEL_1': 'neutro',
                'LABEL_2': 'positivo'
            }
            
            sentimento = mapeamento.get(resultado[0]['label'], 'neutro')
            confianca = resultado[0]['score']
            
            return {
                "sentimento": sentimento,
                "confianca": confianca,
                "interpretacao": self._interpretar_sentimento_contabil(sentimento, confianca)
            }
            
        except Exception as e:
            logger.error(f"❌ Erro na análise de sentimento: {e}")
            return {"sentimento": "neutro", "confianca": 0.5, "interpretacao": "Análise não disponível"}
    
    def gerar_insights_automaticos(self, documentos, normas):
        """Gera insights automáticos usando IA"""
        insights = []
        
        try:
            # Insight 1: Análise temporal de assuntos
            insights.append(self._analisar_tendencia_assuntos(documentos))
            
            # Insight 2: Padrões em normas
            insights.append(self._analisar_padroes_normas(normas))
            
            # Insight 3: Análise de compliance
            insights.append(self._analisar_compliance_inteligente(normas))
            
            # Insight 4: Recomendações contextuais
            insights.extend(self._gerar_recomendacoes_contextuais(documentos, normas))
            
            return [i for i in insights if i]  # Remove insights vazios
            
        except Exception as e:
            logger.error(f"❌ Erro na geração de insights: {e}")
            return []
    
    # Métodos auxiliares
    def _limpar_texto_para_ia(self, texto):
        """Limpa e prepara texto para processamento de IA"""
        if not texto:
            return ""
        
        # Remove caracteres especiais excessivos
        texto = re.sub(r'[^\w\s\.\,\;\:\!\?\-]', ' ', texto)
        
        # Remove espaços múltiplos
        texto = re.sub(r'\s+', ' ', texto)
        
        # Limita tamanho (modelos têm limite de tokens)
        palavras = texto.split()
        if len(palavras) > 500:  # ~400 tokens aprox
            texto = ' '.join(palavras[:500])
        
        return texto.strip()
    
    def _pos_processar_resumo(self, resumo):
        """Pós-processa o resumo gerado pela IA"""
        if not resumo:
            return ""
        
        # Capitaliza primeira letra
        resumo = resumo[0].upper() + resumo[1:] if len(resumo) > 1 else resumo.upper()
        
        # Remove frases incompletas no final
        if not resumo.endswith('.'):
            ultima_frase = resumo.rfind('.')
            if ultima_frase > len(resumo) * 0.7:  # Se há uma frase quase completa
                resumo = resumo[:ultima_frase + 1]
            else:
                resumo += "."
        
        return resumo
    
    def _resumo_fallback(self, texto, max_length):
        """Sistema de resumo alternativo quando IA não disponível"""
        if not texto:
            return "Texto não disponível para resumo."
        
        # Pega as primeiras frases até atingir o limite
        frases = re.split(r'[.!?]+', texto)
        resumo = ""
        
        for frase in frases:
            frase_limpa = frase.strip()
            if len(resumo + frase_limpa) < max_length:
                resumo += frase_limpa + ". "
            else:
                break
        
        return resumo.strip() or texto[:max_length] + "..."
    
    def _extrair_tfidf(self, texto, num_palavras):
        """Extração de palavras-chave usando TF-IDF simplificado"""
        from collections import Counter
        import math
        
        # Remove stop words
        stop_words = {
            'de', 'da', 'do', 'das', 'dos', 'em', 'na', 'no', 'nas', 'nos',
            'para', 'por', 'com', 'sem', 'sobre', 'entre', 'até', 'desde',
            'que', 'como', 'quando', 'onde', 'porque', 'se', 'mas', 'ou',
            'e', 'a', 'o', 'as', 'os', 'um', 'uma', 'uns', 'umas', 'é', 'são',
            'foi', 'foram', 'será', 'serão', 'tem', 'têm', 'teve', 'tiveram'
        }
        
        # Extrai palavras
        palavras = re.findall(r'\b\w{3,}\b', texto.lower())
        palavras_filtradas = [p for p in palavras if p not in stop_words and len(p) > 3]
        
        # Calcula frequência
        freq = Counter(palavras_filtradas)
        
        # Ordena por relevância (frequência e tamanho)
        palavras_relevantes = sorted(
            freq.items(), 
            key=lambda x: x[1] * len(x[0]) * 0.1, 
            reverse=True
        )
        
        return [palavra for palavra, _ in palavras_relevantes[:num_palavras]]
    
    def _refinar_palavras_chave_ia(self, texto, palavras_iniciais):
        """Refina palavras-chave usando contexto de IA"""
        # Aqui você pode implementar refinamento mais sofisticado
        # Por ora, retorna as palavras iniciais com algum filtro
        
        # Filtra palavras muito comuns em documentos legais
        filtros_contextuais = {'artigo', 'inciso', 'paragrafo', 'lei', 'decreto', 'portaria'}
        palavras_refinadas = [p for p in palavras_iniciais if p not in filtros_contextuais]
        
        return palavras_refinadas
    
    def _extrair_palavras_chave_basico(self, texto):
        """Método básico para extração quando IA não disponível"""
        return self._extrair_tfidf(texto, 5)
    
    def _interpretar_sentimento_contabil(self, sentimento, confianca):
        """Interpreta sentimento no contexto contábil"""
        if confianca < 0.6:
            return "Neutro - baixa confiança na análise"
        
        interpretacoes = {
            'positivo': "Documento com tom regulamentador/orientativo",
            'negativo': "Documento com tom restritivo/punitivo", 
            'neutro': "Documento com tom informativo/técnico"
        }
        
        return interpretacoes.get(sentimento, "Tom não identificado")
    
    def _analisar_tendencia_assuntos(self, documentos):
        """Analisa tendências nos assuntos usando IA"""
        if not documentos:
            return None
        
        # Agrupa assuntos por período
        assuntos_recentes = []
        data_limite = datetime.now() - timedelta(days=90)
        
        for doc in documentos:
            if doc.data_publicacao >= data_limite and doc.assunto:
                assuntos_recentes.append(doc.assunto)
        
        if not assuntos_recentes:
            return None
        
        # Extrai temas emergentes
        texto_combinado = ". ".join(assuntos_recentes)
        palavras_chave = self.extrair_palavras_chave_ia(texto_combinado, 5)
        
        return {
            "tipo": "TENDÊNCIA",
            "titulo": "Temas Emergentes Identificados",
            "descricao": f"Análise dos últimos 90 dias identificou tendências em: {', '.join(palavras_chave[:3])}",
            "relevancia": "alta" if len(palavras_chave) >= 3 else "média"
        }
    
    def _analisar_padroes_normas(self, normas):
        """Analisa padrões nas normas usando IA"""
        if not normas:
            return None
        
        # Analisa distribuição de tipos
        tipos_freq = Counter([n.tipo for n in normas if n.tipo])
        tipo_dominante = tipos_freq.most_common(1)[0] if tipos_freq else None
        
        if not tipo_dominante:
            return None
        
        return {
            "tipo": "PADRÃO",
            "titulo": f"Predominância de {tipo_dominante[0]}",
            "descricao": f"Identificadas {tipo_dominante[1]} normas do tipo {tipo_dominante[0]}, representando {tipo_dominante[1]/len(normas)*100:.1f}% do total",
            "relevancia": "alta" if tipo_dominante[1] > len(normas) * 0.4 else "média"
        }
    
    def _analisar_compliance_inteligente(self, normas):
        """Análise inteligente de compliance"""
        if not normas:
            return None
        
        problematicas = len([n for n in normas if n.situacao in ['REVOGADA', 'NÃO ENCONTRADA']])
        total = len(normas)
        percentual_problema = (problematicas / total * 100) if total > 0 else 0
        
        if percentual_problema > 15:
            return {
                "tipo": "RISCO",
                "titulo": "Alto Risco de Compliance Detectado",
                "descricao": f"{percentual_problema:.1f}% das normas apresentam problemas de vigência",
                "relevancia": "crítica"
            }
        
        return None
    
    def _gerar_recomendacoes_contextuais(self, documentos, normas):
        """Gera recomendações baseadas no contexto atual"""
        recomendacoes = []
        
        # Recomendação baseada em processamento
        nao_processados = len([d for d in documentos if not d.processado])
        if nao_processados > len(documentos) * 0.2:  # Mais de 20% não processados
            recomendacoes.append({
                "tipo": "PROCESSAMENTO",
                "titulo": "Acelerar Processamento de Documentos",
                "descricao": f"{nao_processados} documentos aguardam processamento completo",
                "relevancia": "alta"
            })
        
        # Recomendação baseada em verificação de normas
        nao_verificadas = len([n for n in normas if not n.data_verificacao])
        if nao_verificadas > 0:
            recomendacoes.append({
                "tipo": "VERIFICAÇÃO",
                "titulo": "Implementar Verificação Sistemática",
                "descricao": f"{nao_verificadas} normas precisam de verificação de status",
                "relevancia": "média"
            })
        
        return recomendacoes


class AnaliseIA:
    """Classe responsável por análises avançadas com IA dos documentos e normas"""
    
    def __init__(self):
        self.ia_gratuita = IAGratuita()
    
    @staticmethod
    def analisar_tendencias_normativas(documentos):
        """Analisa tendências nas normas mencionadas nos documentos"""
        tendencias = {
            'normas_mais_citadas': [],
            'tipos_normas_frequentes': {},
            'evolucao_temporal': {},
            'assuntos_emergentes': [],
            'correlacoes_normas': {}
        }
        
        # Análise de frequência de normas
        normas_freq = defaultdict(int)
        tipos_freq = defaultdict(int)
        assuntos_por_mes = defaultdict(list)
        
        for doc in documentos:
            mes_ano = doc.data_publicacao.strftime('%Y-%m')
            assuntos_por_mes[mes_ano].append(doc.assunto or '')
            
            for norma in doc.normas_relacionadas.all():
                norma_key = f"{norma.tipo} {norma.numero}"
                normas_freq[norma_key] += 1
                tipos_freq[norma.tipo] += 1
        
        # Top normas mais citadas
        tendencias['normas_mais_citadas'] = sorted(
            normas_freq.items(), key=lambda x: x[1], reverse=True
        )[:10]
        
        # Tipos mais frequentes
        tendencias['tipos_normas_frequentes'] = dict(tipos_freq)
        
        # Evolução temporal
        tendencias['evolucao_temporal'] = dict(assuntos_por_mes)
        
        # Identificar assuntos emergentes usando análise de keywords
        assuntos_emergentes = AnaliseIA._identificar_assuntos_emergentes(assuntos_por_mes)
        tendencias['assuntos_emergentes'] = assuntos_emergentes
        
        return tendencias
    
    @staticmethod
    def _identificar_assuntos_emergentes(assuntos_por_mes):
        """Identifica assuntos que estão crescendo em frequência"""
        palavras_chave = defaultdict(lambda: defaultdict(int))
        
        # Análise de palavras-chave por mês
        for mes, assuntos in assuntos_por_mes.items():
            for assunto in assuntos:
                if assunto:
                    palavras = re.findall(r'\b\w{4,}\b', assunto.lower())
                    for palavra in palavras:
                        palavras_chave[palavra][mes] += 1
        
        # Identificar tendências crescentes
        emergentes = []
        meses_ordenados = sorted(assuntos_por_mes.keys())
        
        for palavra, freq_mensal in palavras_chave.items():
            if len(freq_mensal) >= 3:  # Pelo menos 3 meses de dados
                frequencias = [freq_mensal.get(mes, 0) for mes in meses_ordenados[-6:]]
                if len(frequencias) >= 3:
                    # Calcular tendência (crescimento)
                    crescimento = sum(frequencias[-3:]) - sum(frequencias[:3])
                    if crescimento > 0:
                        emergentes.append((palavra, crescimento))
        
        return sorted(emergentes, key=lambda x: x[1], reverse=True)[:10]
    
    def gerar_resumo_executivo(self, documentos, normas):
        """Gera resumo executivo inteligente dos dados com IA"""
        total_docs = len(documentos)
        total_normas = len(normas)
        
        # Análise temporal
        if documentos:
            doc_mais_recente = max(documentos, key=lambda d: d.data_publicacao)
            doc_mais_antigo = min(documentos, key=lambda d: d.data_publicacao)
            periodo = (doc_mais_recente.data_publicacao - doc_mais_antigo.data_publicacao).days
        else:
            periodo = 0
        
        # Análise de relevância contábil
        docs_contabeis = [d for d in documentos if d.relevante_contabil]
        taxa_relevancia = (len(docs_contabeis) / total_docs * 100) if total_docs > 0 else 0
        
        # Análise de normas
        normas_vigentes = [n for n in normas if n.situacao == 'VIGENTE']
        normas_revogadas = [n for n in normas if n.situacao == 'REVOGADA']
        normas_nao_encontradas = [n for n in normas if n.situacao == 'NÃO ENCONTRADA']
        
        # Análise de fontes
        fontes_confirmacao = Counter([n.fonte_confirmacao for n in normas if n.fonte_confirmacao])
        
        # 🆕 Análises com IA Gratuita
        insights_ia = self.ia_gratuita.gerar_insights_automaticos(documentos, normas)
        
        # 🆕 Análise de sentimento dos documentos
        sentimentos = []
        for doc in documentos[:10]:  # Analisa uma amostra
            if doc.resumo or doc.titulo:
                sentimento = self.ia_gratuita.analisar_sentimento_documento(doc.resumo or doc.titulo)
                sentimentos.append(sentimento)
        
        # 🆕 Resumo inteligente dos principais assuntos
        principais_assuntos = [doc.assunto for doc in documentos if doc.assunto][:5]
        resumo_assuntos = ""
        if principais_assuntos:
            texto_assuntos = ". ".join(principais_assuntos)
            resumo_assuntos = self.ia_gratuita.gerar_resumo_inteligente(texto_assuntos, 100)
        
        resumo = {
            'periodo_analise': f"{periodo} dias" if periodo > 0 else "N/A",
            'total_documentos': total_docs,
            'documentos_contabeis': len(docs_contabeis),
            'taxa_relevancia_contabil': f"{taxa_relevancia:.1f}%",
            'total_normas': total_normas,
            'normas_vigentes': len(normas_vigentes),
            'normas_revogadas': len(normas_revogadas),
            'normas_problematicas': len(normas_nao_encontradas),
            'fontes_principais': dict(fontes_confirmacao.most_common(3)),
            'risco_compliance': self._calcular_risco_compliance(normas),
            'recomendacoes': self._gerar_recomendacoes(documentos, normas),
            
            # 🆕 Campos com IA
            'insights_ia': insights_ia,
            'analise_sentimento': self._processar_sentimentos(sentimentos),
            'resumo_assuntos_ia': resumo_assuntos,
            'palavras_chave_periodo': self.ia_gratuita.extrair_palavras_chave_ia(resumo_assuntos, 8) if resumo_assuntos else []
        }
        
        return resumo
    
    def _processar_sentimentos(self, sentimentos):
        """Processa análise de sentimentos dos documentos"""
        if not sentimentos:
            return {"predominante": "neutro", "distribuicao": {}, "interpretacao": "Análise não disponível"}
        
        # Conta distribuição
        distribuicao = Counter([s['sentimento'] for s in sentimentos])
        predominante = distribuicao.most_common(1)[0][0] if distribuicao else "neutro"
        
        # Calcula confiança média
        confianca_media = sum([s['confianca'] for s in sentimentos]) / len(sentimentos)
        
        return {
            "predominante": predominante,
            "distribuicao": dict(distribuicao),
            "confianca_media": f"{confianca_media:.2f}",
            "interpretacao": f"Tom predominante: {predominante} (confiança: {confianca_media:.1%})"
        }
    
    @staticmethod
    def _calcular_risco_compliance(normas):
        """Calcula score de risco de compliance baseado no status das normas"""
        if not normas:
            return "BAIXO"
        
        total = len(normas)
        problematicas = len([n for n in normas if n.situacao in ['NÃO ENCONTRADA', 'REVOGADA']])
        nao_verificadas = len([n for n in normas if not n.data_verificacao])
        
        score_problema = (problematicas / total) * 100
        score_verificacao = (nao_verificadas / total) * 100
        
        risco_total = score_problema + (score_verificacao * 0.5)
        
        if risco_total > 30:
            return "ALTO"
        elif risco_total > 15:
            return "MÉDIO"
        else:
            return "BAIXO"
    
    @staticmethod
    def _gerar_recomendacoes(documentos, normas):
        """Gera recomendações baseadas na análise dos dados"""
        recomendacoes = []
        
        # Análise de normas problemáticas
        normas_problema = [n for n in normas if n.situacao in ['NÃO ENCONTRADA', 'REVOGADA']]
        if normas_problema:
            recomendacoes.append({
                'tipo': 'CRÍTICO',
                'titulo': 'Normas Problemáticas Identificadas',
                'descricao': f"Encontradas {len(normas_problema)} normas com status problemático que requerem atenção imediata",
                'acao': 'Revisar e atualizar referências normativas'
            })
        
        # Análise de verificação
        nao_verificadas = [n for n in normas if not n.data_verificacao]
        if nao_verificadas:
            recomendacoes.append({
                'tipo': 'IMPORTANTE',
                'titulo': 'Normas Não Verificadas',
                'descricao': f"{len(nao_verificadas)} normas ainda não foram verificadas",
                'acao': 'Implementar processo de verificação sistemática'
            })
        
        # Análise de documentos não processados
        nao_processados = [d for d in documentos if not d.processado]
        if nao_processados:
            recomendacoes.append({
                'tipo': 'MELHORIA',
                'titulo': 'Documentos Pendentes',
                'descricao': f"{len(nao_processados)} documentos aguardam processamento",
                'acao': 'Acelerar processamento de documentos pendentes'
            })
        
        return recomendacoes


# Resto do código permanece igual...
class RelatorioAvancado:
    """Gerador de relatórios avançados com análises de IA e visualizações"""
    
    def __init__(self):
        self.wb = None
        self.estilos = self._criar_estilos()
        self.ia_gratuita = IAGratuita()  # 🆕 Adiciona IA gratuita
    
    def _criar_estilos(self):
        """Cria estilos padronizados para as planilhas"""
        estilos = {}
        
        # Estilo do título principal
        estilos['titulo_principal'] = {
            'font': Font(size=16, bold=True, color="1F4E78"),
            'alignment': Alignment(horizontal='center', vertical='center'),
            'fill': PatternFill(start_color="E7F3FF", end_color="E7F3FF", fill_type="solid")
        }
        
        # Estilo do cabeçalho
        estilos['cabecalho'] = {
            'font': Font(color="FFFFFF", bold=True, size=11),
            'fill': PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid"),
            'border': Border(
                bottom=Side(border_style="medium", color="FFFFFF"),
                top=Side(border_style="thin", color="FFFFFF"),
                left=Side(border_style="thin", color="FFFFFF"),
                right=Side(border_style="thin", color="FFFFFF")
            ),
            'alignment': Alignment(horizontal='center', vertical='center', wrap_text=True)
        }
        
        # Estilo zebrado
        estilos['zebra'] = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
        
        # Estilo de alerta
        estilos['alerta'] = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
        
        # Estilo de sucesso
        estilos['sucesso'] = PatternFill(start_color="E6F3E6", end_color="E6F3E6", fill_type="solid")
        
        # Estilo de aviso
        estilos['aviso'] = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
        
        return estilos
    
    
    def gerar_relatorio_completo(self):
        """Gera relatório completo com todas as análises e dados"""
        try:
            logger.info("🚀 Iniciando geração de relatório completo...")
            
            # Busca dados
            documentos = list(Documento.objects.all().order_by('-data_publicacao'))
            normas = list(NormaVigente.objects.all().order_by('tipo', 'numero'))
            
            # Cria workbook
            self.wb = Workbook()
            
            # Remove planilha padrão
            if 'Sheet' in self.wb.sheetnames:
                self.wb.remove(self.wb['Sheet'])
            
            # Gera planilhas
            ws_resumo = self._criar_resumo_executivo(documentos, normas)
            ws_ia = self._criar_analise_ia(documentos, normas)
            self._criar_resumo_executivo(documentos, normas)
            self._criar_analise_documentos(documentos)
            self._criar_analise_normas(normas)
            self._criar_analise_compliance(normas)
            self._criar_tendencias_temporais(documentos)
            self._criar_analise_ia(documentos, normas)  # 🆕 Nova aba com IA
            self._criar_dashboard_visual(documentos, normas)
            self._adicionar_analise_contextual(documentos, normas, ws_resumo)
            self._adicionar_impacto_regulatorio(normas, ws_resumo)
            #self._adicionar_resumos_especificos(documentos, ws_ia)
            #self._adicionar_termos_contabeis(documentos, ws_ia)
            
            # Salva arquivo
            nome_arquivo = f"relatorio_compliance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            caminho_arquivo = os.path.join(settings.MEDIA_ROOT, 'relatorios', nome_arquivo)
            
            # Cria diretório se não existir
            os.makedirs(os.path.dirname(caminho_arquivo), exist_ok=True)
            
            self.wb.save(caminho_arquivo)
            
            logger.info(f"✅ Relatório completo gerado: {nome_arquivo}")
            return caminho_arquivo
            
        except Exception as e:
            logger.error(f"❌ Erro na geração do relatório completo: {e}")
            raise


    def _adicionar_analise_contextual(self, documentos, normas, worksheet):
        """Adiciona análise contextual ao resumo executivo"""
        row = worksheet.max_row + 2
        
        # Análise contextual dos documentos
        worksheet[f'A{row}'] = "ANÁLISE CONTEXTUAL"
        self._aplicar_estilo(worksheet[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        # Resumo IA dos documentos mais relevantes
        docs_relevantes = [d for d in documentos if d.relevante_contabil][:5]
        texto_analise = ". ".join(d.resumo or d.titulo for d in docs_relevantes)
        resumo_contexto = self.ia_gratuita.gerar_resumo_inteligente(texto_analise, 150)
        
        worksheet[f'A{row}'] = "Contexto Regulatório"
        worksheet[f'B{row}'] = resumo_contexto
        worksheet[f'B{row}'].alignment = Alignment(wrap_text=True)
        row += 1
        
        # Mudanças desde o último relatório
        ultimo_relatorio = RelatorioGerado.objects.order_by('-data_criacao').first()
        if ultimo_relatorio:
            worksheet[f'A{row}'] = "Principais Mudanças"
            mudancas = self._analisar_mudancas(documentos, normas, ultimo_relatorio)
            worksheet[f'B{row}'] = mudances
            worksheet[f'B{row}'].alignment = Alignment(wrap_text=True)



    def _adicionar_impacto_regulatorio(self, normas, worksheet):
        """Adiciona análise de impacto regulatório"""
        normas_vigentes = [n for n in normas if n.situacao == 'VIGENTE']
        normas_novas = [n for n in normas_vigentes 
                       if n.data_verificacao and (timezone.now() - n.data_verificacao).days < 30]
        
        if normas_novas:
            row = worksheet.max_row + 2
            worksheet[f'A{row}'] = "IMPACTO REGULATÓRIO"
            self._aplicar_estilo(worksheet[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            worksheet[f'A{row}'] = "Novas Normas Vigentes"
            worksheet[f'B{row}'] = f"{len(normas_novas)} normas vigentes identificadas nos últimos 30 dias"
            
            # Análise de impacto das novas normas
            texto_normas = ". ".join(f"{n.tipo} {n.numero}: {n.ementa}" for n in normas_novas)
            impacto = self.ia_gratuita.gerar_resumo_inteligente(
                f"Análise de impacto contábil das seguintes normas: {texto_normas}", 
                200
            )
            row += 1
            worksheet[f'A{row}'] = "Análise de Impacto"
            worksheet[f'B{row}'] = impacto
            worksheet[f'B{row}'].alignment = Alignment(wrap_text=True)



    
    
    def _criar_resumo_executivo(self, documentos, normas):
        """Cria aba com resumo executivo"""
        ws = self.wb.create_sheet(title="📊 Resumo Executivo")
        
        # Gera análise IA
        analise_ia = AnaliseIA()
        resumo = analise_ia.gerar_resumo_executivo(documentos, normas)
        
        row = 1
        
        # Título principal
        ws.merge_cells(f'A{row}:H{row}')
        ws[f'A{row}'] = "RELATÓRIO EXECUTIVO DE COMPLIANCE CONTÁBIL"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['titulo_principal'])
        row += 2
        
        # Informações gerais
        ws[f'A{row}'] = "INFORMAÇÕES GERAIS"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        infos_gerais = [
            ("Período de Análise", resumo['periodo_analise']),
            ("Total de Documentos", resumo['total_documentos']),
            ("Documentos Contábeis", resumo['documentos_contabeis']),
            ("Taxa de Relevância Contábil", resumo['taxa_relevancia_contabil']),
            ("Total de Normas", resumo['total_normas']),
            ("Normas Vigentes", resumo['normas_vigentes']),
            ("Normas Revogadas", resumo['normas_revogadas']),
            ("Normas Problemáticas", resumo['normas_problematicas']),
            ("Risco de Compliance", resumo['risco_compliance'])
        ]
        
        for info, valor in infos_gerais:
            ws[f'A{row}'] = info
            ws[f'B{row}'] = valor
            
            # Coloração baseada no tipo de informação
            if "Risco" in info:
                if valor == "ALTO":
                    ws[f'B{row}'].fill = self.estilos['alerta']
                elif valor == "MÉDIO":
                    ws[f'B{row}'].fill = self.estilos['aviso']
                else:
                    ws[f'B{row}'].fill = self.estilos['sucesso']
            
            row += 1
        
        row += 2
        
        # 🆕 Seção de Análise com IA
        if resumo.get('insights_ia'):
            ws[f'A{row}'] = "INSIGHTS GERADOS POR IA"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            for insight in resumo['insights_ia']:
                ws[f'A{row}'] = f"🔍 {insight['titulo']}"
                ws[f'B{row}'] = insight['descricao']
                
                # Cor baseada na relevância
                if insight.get('relevancia') == 'crítica':
                    ws[f'A{row}'].fill = self.estilos['alerta']
                elif insight.get('relevancia') == 'alta':
                    ws[f'A{row}'].fill = self.estilos['aviso']
                
                row += 1
            
            row += 2
        
        # 🆕 Análise de Sentimento
        if resumo.get('analise_sentimento'):
            ws[f'A{row}'] = "ANÁLISE DE SENTIMENTO DOS DOCUMENTOS"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            sentimento = resumo['analise_sentimento']
            ws[f'A{row}'] = "Tom Predominante"
            ws[f'B{row}'] = sentimento['predominante'].upper()
            ws[f'C{row}'] = sentimento['interpretacao']
            row += 1
            
            row += 1
        
        # 🆕 Palavras-chave do Período
        if resumo.get('palavras_chave_periodo'):
            ws[f'A{row}'] = "PALAVRAS-CHAVE DO PERÍODO (IA)"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            palavras = ", ".join(resumo['palavras_chave_periodo'])
            ws[f'A{row}'] = "Temas Principais"
            ws[f'B{row}'] = palavras
            row += 2
        
        # Fontes principais
        if resumo['fontes_principais']:
            ws[f'A{row}'] = "FONTES DE CONFIRMAÇÃO PRINCIPAIS"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            for fonte, qtd in resumo['fontes_principais'].items():
                ws[f'A{row}'] = fonte
                ws[f'B{row}'] = qtd
                row += 1
            
            row += 2
        
        # Recomendações
        if resumo['recomendacoes']:
            ws[f'A{row}'] = "RECOMENDAÇÕES PRIORITÁRIAS"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            for rec in resumo['recomendacoes']:
                ws[f'A{row}'] = f"⚠️ {rec['titulo']}"
                ws[f'B{row}'] = rec['descricao']
                ws[f'C{row}'] = rec.get('acao', '')
                
                # Cor baseada no tipo
                if rec['tipo'] == 'CRÍTICO':
                    ws[f'A{row}'].fill = self.estilos['alerta']
                elif rec['tipo'] == 'IMPORTANTE':
                    ws[f'A{row}'].fill = self.estilos['aviso']
                
                row += 1
        
        # Ajusta largura das colunas
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 40


        return ws
    def _criar_analise_ia(self, documentos, normas):
        """🆕 Cria aba dedicada às análises de IA"""
        ws = self.wb.create_sheet(title="🤖 Análise IA")
        
        row = 1
        
        # Título
        ws.merge_cells(f'A{row}:E{row}')
        ws[f'A{row}'] = "ANÁLISES AVANÇADAS COM INTELIGÊNCIA ARTIFICIAL"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['titulo_principal'])
        row += 2
        
        # Seção 1: Resumos Inteligentes dos Documentos
        ws[f'A{row}'] = "RESUMOS INTELIGENTES DOS PRINCIPAIS DOCUMENTOS"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        # Cabeçalhos
        cabecalhos = ["Documento", "Resumo IA", "Palavras-chave", "Sentimento", "Relevância"]
        for col, cabecalho in enumerate(cabecalhos, 1):
            ws.cell(row, col, cabecalho)
            self._aplicar_estilo(ws.cell(row, col), self.estilos['cabecalho'])
        row += 1
        
        # Processa amostra de documentos
        documentos_amostra = documentos[:10] if len(documentos) > 10 else documentos
        
        for doc in documentos_amostra:
            texto_para_analise = doc.resumo or doc.titulo or doc.assunto or ""
            
            if texto_para_analise:
                # Gera resumo IA
                resumo_ia = self.ia_gratuita.gerar_resumo_inteligente(texto_para_analise, 100)
                
                # Extrai palavras-chave
                palavras_chave = self.ia_gratuita.extrair_palavras_chave_ia(texto_para_analise, 5)
                
                # Análise de sentimento
                sentimento = self.ia_gratuita.analisar_sentimento_documento(texto_para_analise)
                
                # Preenche linha
                ws[f'A{row}'] = doc.titulo[:50] + "..." if len(doc.titulo) > 50 else doc.titulo
                ws[f'B{row}'] = resumo_ia
                ws[f'C{row}'] = ", ".join(palavras_chave[:3])
                ws[f'D{row}'] = f"{sentimento['sentimento']} ({sentimento['confianca']:.1%})"
                ws[f'E{row}'] = "ALTA" if doc.relevante_contabil else "BAIXA"
                
                # Coloração baseada na relevância
                if doc.relevante_contabil:
                    ws[f'E{row}'].fill = self.estilos['sucesso']
                
                # Quebra linha no resumo
                ws[f'B{row}'].alignment = Alignment(wrap_text=True, vertical='top')
                
                row += 1
        
        row += 2
        
        # Seção 2: Análise de Tendências
        ws[f'A{row}'] = "TENDÊNCIAS IDENTIFICADAS PELA IA"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        # Análise de tendências
        analise_ia = AnaliseIA()
        tendencias = analise_ia.analisar_tendencias_normativas(documentos)
        
        # Normas mais citadas
        if tendencias['normas_mais_citadas']:
            ws[f'A{row}'] = "Top 5 Normas Mais Citadas"
            self._aplicar_estilo(ws[f'A{row}'], {'font': Font(bold=True)})
            row += 1
            
            for norma, freq in tendencias['normas_mais_citadas'][:5]:
                ws[f'A{row}'] = norma
                ws[f'B{row}'] = f"{freq} citações"
                row += 1
            
            row += 1
        
        # Assuntos emergentes
        if tendencias['assuntos_emergentes']:
            ws[f'A{row}'] = "Assuntos Emergentes Identificados"
            self._aplicar_estilo(ws[f'A{row}'], {'font': Font(bold=True)})
            row += 1
            
            for assunto, crescimento in tendencias['assuntos_emergentes'][:5]:
                ws[f'A{row}'] = assunto.title()
                ws[f'B{row}'] = f"Crescimento: +{crescimento}"
                ws[f'B{row}'].fill = self.estilos['sucesso'] if crescimento > 2 else self.estilos['aviso']
                row += 1
        
        # Seção 3: Insights Automáticos
        row += 2
        ws[f'A{row}'] = "INSIGHTS AUTOMÁTICOS GERADOS PELA IA"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        insights = self.ia_gratuita.gerar_insights_automaticos(documentos, normas)
        
        for insight in insights:
            ws[f'A{row}'] = f"📋 {insight['titulo']}"
            ws[f'B{row}'] = insight['descricao']
            ws[f'C{row}'] = insight.get('relevancia', 'média').upper()
            
            # Cor baseada na relevância
            if insight.get('relevancia') == 'crítica':
                ws[f'C{row}'].fill = self.estilos['alerta']
            elif insight.get('relevancia') == 'alta':
                ws[f'C{row}'].fill = self.estilos['aviso']
            else:
                ws[f'C{row}'].fill = self.estilos['sucesso']
            
            ws[f'B{row}'].alignment = Alignment(wrap_text=True, vertical='top')
            row += 1
        
        # Nota sobre IA
        row += 2
        ws.merge_cells(f'A{row}:E{row}')
        ws[f'A{row}'] = "ℹ️ Nota: As análises desta seção foram geradas automaticamente por modelos de IA gratuitos. Os resultados devem ser validados por análise humana."
        ws[f'A{row}'].alignment = Alignment(wrap_text=True)
        ws[f'A{row}'].fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
        
        # Ajusta largura das colunas
        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 50
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 20
        ws.column_dimensions['E'].width = 15
        
        # Define altura das linhas para melhor legibilidade
        for row_num in range(1, row + 1):
            ws.row_dimensions[row_num].height = 25
    
            return ws 

    def _criar_analise_documentos(self, documentos):
        """Cria aba com análise detalhada dos documentos"""
        ws = self.wb.create_sheet(title="📄 Documentos")
        
        # Cabeçalhos
        cabecalhos = [
            "Data", "Título", "Tipo", "Assunto", "Relevante", 
            "Processado", "Resumo IA", "Palavras-chave", "Fonte"
        ]
        
        for col, cabecalho in enumerate(cabecalhos, 1):
            ws.cell(1, col, cabecalho)
            self._aplicar_estilo(ws.cell(1, col), self.estilos['cabecalho'])
        
        # Dados
        for row, doc in enumerate(documentos, 2):
            # Gera resumo IA se não existir
            resumo_ia = ""
            palavras_chave = ""
            
            if doc.titulo or doc.resumo:
                texto = doc.resumo or doc.titulo
                resumo_ia = self.ia_gratuita.gerar_resumo_inteligente(texto, 80)
                palavras_chave = ", ".join(self.ia_gratuita.extrair_palavras_chave_ia(texto, 3))
            
            ws[f'A{row}'] = doc.data_publicacao.strftime('%d/%m/%Y')
            ws[f'B{row}'] = doc.titulo
            ws[f'C{row}'] = doc.tipo_documento or 'N/A'
            ws[f'D{row}'] = doc.assunto or 'N/A'
            ws[f'E{row}'] = "SIM" if doc.relevante_contabil else "NÃO"
            ws[f'F{row}'] = "SIM" if doc.processado else "NÃO"
            ws[f'G{row}'] = resumo_ia
            ws[f'H{row}'] = palavras_chave
            ws[f'I{row}'] = doc.fonte_documento or 'N/A'
            
            # Coloração
            if doc.relevante_contabil:
                ws[f'E{row}'].fill = self.estilos['sucesso']
            
            if not doc.processado:
                ws[f'F{row}'].fill = self.estilos['aviso']
            
            # Zebrado
            if row % 2 == 0:
                for col in range(1, len(cabecalhos) + 1):
                    ws.cell(row, col).fill = self.estilos['zebra']
        
        # Ajusta larguras
        larguras = [12, 40, 15, 30, 10, 12, 35, 25, 15]
        for col, largura in enumerate(larguras, 1):
            ws.column_dimensions[get_column_letter(col)].width = largura
    
    def _criar_analise_normas(self, normas):
        """Cria aba com análise das normas"""
        ws = self.wb.create_sheet(title="📋 Normas")
        
        # Cabeçalhos
        cabecalhos = [
            "Tipo", "Número", "Ementa", "Situação", "Última Verificação", 
            "Fonte Confirmação", "Data Vigência", "Observações"
        ]
        
        for col, cabecalho in enumerate(cabecalhos, 1):
            ws.cell(1, col, cabecalho)
            self._aplicar_estilo(ws.cell(1, col), self.estilos['cabecalho'])
        
        # Dados
        for row, norma in enumerate(normas, 2):
            ws[f'A{row}'] = norma.tipo
            ws[f'B{row}'] = norma.numero
            ws[f'C{row}'] = norma.ementa or 'N/A'
            ws[f'D{row}'] = norma.situacao
            ws[f'E{row}'] = norma.data_verificacao.strftime('%d/%m/%Y') if norma.data_verificacao else 'NUNCA'
            ws[f'F{row}'] = norma.fonte_confirmacao or 'N/A'
            ws[f'G{row}'] = norma.data_vigencia.strftime('%d/%m/%Y') if norma.data_vigencia else 'N/A'
            ws[f'H{row}'] = norma.observacoes or 'N/A'
            
            # Coloração baseada na situação
            if norma.situacao == 'VIGENTE':
                ws[f'D{row}'].fill = self.estilos['sucesso']
            elif norma.situacao == 'REVOGADA':
                ws[f'D{row}'].fill = self.estilos['alerta']
            elif norma.situacao == 'NÃO ENCONTRADA':
                ws[f'D{row}'].fill = self.estilos['aviso']
            
            # Coloração para verificação
            if not norma.data_verificacao:
                ws[f'E{row}'].fill = self.estilos['aviso']
            
            # Zebrado
            if row % 2 == 0:
                for col in range(1, len(cabecalhos) + 1):
                    ws.cell(row, col).fill = self.estilos['zebra']
        
        # Ajusta larguras
        larguras = [15, 15, 40, 15, 18, 20, 15, 30]
        for col, largura in enumerate(larguras, 1):
            ws.column_dimensions[get_column_letter(col)].width = largura
    
    def _criar_analise_compliance(self, normas):
        """Cria aba com análise de compliance"""
        ws = self.wb.create_sheet(title="⚖️ Compliance")
        
        row = 1
        
        # Título
        ws.merge_cells(f'A{row}:D{row}')
        ws[f'A{row}'] = "ANÁLISE DE COMPLIANCE"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['titulo_principal'])
        row += 2
        
        # Estatísticas gerais
        total_normas = len(normas)
        vigentes = len([n for n in normas if n.situacao == 'VIGENTE'])
        revogadas = len([n for n in normas if n.situacao == 'REVOGADA'])
        nao_encontradas = len([n for n in normas if n.situacao == 'NÃO ENCONTRADA'])
        nao_verificadas = len([n for n in normas if not n.data_verificacao])
        
        # Cria tabela de estatísticas
        stats = [
            ("Total de Normas", total_normas),
            ("Normas Vigentes", vigentes),
            ("Normas Revogadas", revogadas),
            ("Normas Não Encontradas", nao_encontradas),
            ("Normas Não Verificadas", nao_verificadas),
            ("Taxa de Compliance", f"{(vigentes/total_normas*100):.1f}%" if total_normas > 0 else "0%")
        ]
        
        ws[f'A{row}'] = "ESTATÍSTICAS GERAIS"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
        row += 1
        
        for desc, valor in stats:
            ws[f'A{row}'] = desc
            ws[f'B{row}'] = valor
            row += 1
        
        row += 2
        
        # Normas problemáticas
        normas_problematicas = [n for n in normas if n.situacao in ['REVOGADA', 'NÃO ENCONTRADA']]
        
        if normas_problematicas:
            ws[f'A{row}'] = "NORMAS PROBLEMÁTICAS (REQUER ATENÇÃO)"
            self._aplicar_estilo(ws[f'A{row}'], self.estilos['cabecalho'])
            row += 1
            
            # Cabeçalhos
            cabecalhos = ["Tipo", "Número", "Situação", "Última Verificação"]
            for col, cabecalho in enumerate(cabecalhos, 1):
                ws.cell(row, col, cabecalho)
                self._aplicar_estilo(ws.cell(row, col), self.estilos['cabecalho'])
            row += 1
            
            for norma in normas_problematicas:
                ws[f'A{row}'] = norma.tipo
                ws[f'B{row}'] = norma.numero
                ws[f'C{row}'] = norma.situacao
                ws[f'D{row}'] = norma.data_verificacao.strftime('%d/%m/%Y') if norma.data_verificacao else 'NUNCA'
                
                # Cor de alerta
                for col in range(1, 5):
                    ws.cell(row, col).fill = self.estilos['alerta']
                
                row += 1
        
        # Ajusta larguras
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 20
        ws.column_dimensions['D'].width = 20
    
    def _criar_tendencias_temporais(self, documentos):
        """Cria aba com análise de tendências temporais"""
        ws = self.wb.create_sheet(title="📈 Tendências")
        
        # Análise por mês
        documentos_por_mes = defaultdict(int)
        relevantes_por_mes = defaultdict(int)
        
        for doc in documentos:
            mes_ano = doc.data_publicacao.strftime('%Y-%m')
            documentos_por_mes[mes_ano] += 1
            if doc.relevante_contabil:
                relevantes_por_mes[mes_ano] += 1
        
        # Cabeçalhos
        ws['A1'] = "Mês/Ano"
        ws['B1'] = "Total Documentos"
        ws['C1'] = "Relevantes Contábil"
        ws['D1'] = "Taxa Relevância"
        
        for col in range(1, 5):
            self._aplicar_estilo(ws.cell(1, col), self.estilos['cabecalho'])
        
        # Dados
        meses_ordenados = sorted(documentos_por_mes.keys())
        for row, mes in enumerate(meses_ordenados, 2):
            total = documentos_por_mes[mes]
            relevantes = relevantes_por_mes[mes]
            taxa = (relevantes / total * 100) if total > 0 else 0
            
            ws[f'A{row}'] = mes
            ws[f'B{row}'] = total
            ws[f'C{row}'] = relevantes
            ws[f'D{row}'] = f"{taxa:.1f}%"
            
            # Coloração baseada na taxa
            if taxa > 70:
                ws[f'D{row}'].fill = self.estilos['sucesso']
            elif taxa > 40:
                ws[f'D{row}'].fill = self.estilos['aviso']
            else:
                ws[f'D{row}'].fill = self.estilos['alerta']
        
        # Ajusta larguras
        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 18
        ws.column_dimensions['D'].width = 15
    
    def _criar_dashboard_visual(self, documentos, normas):
        """Cria aba com dashboard visual"""
        ws = self.wb.create_sheet(title="📊 Dashboard")
        
        # Esta função pode ser expandida para incluir gráficos
        # usando openpyxl.chart
        
        row = 1
        ws.merge_cells(f'A{row}:F{row}')
        ws[f'A{row}'] = "DASHBOARD VISUAL DE COMPLIANCE"
        self._aplicar_estilo(ws[f'A{row}'], self.estilos['titulo_principal'])
        row += 3
        
        # Resumo visual
        total_docs = len(documentos)
        docs_relevantes = len([d for d in documentos if d.relevante_contabil])
        total_normas = len(normas)
        normas_vigentes = len([n for n in normas if n.situacao == 'VIGENTE'])
        
        # Cards de estatísticas
        cards = [
            ("📄 DOCUMENTOS", total_docs, "Total processados"),
            ("✅ RELEVANTES", docs_relevantes, "Relevância contábil"),
            ("📋 NORMAS", total_normas, "Total catalogadas"),
            ("⚖️ VIGENTES", normas_vigentes, "Status vigente")
        ]
        
        col_start = 1
        for i, (titulo, valor, desc) in enumerate(cards):
            col = col_start + (i * 2)
            
            # Título do card
            ws.merge_cells(f'{get_column_letter(col)}{row}:{get_column_letter(col+1)}{row}')
            ws[f'{get_column_letter(col)}{row}'] = titulo
            self._aplicar_estilo(ws[f'{get_column_letter(col)}{row}'], self.estilos['cabecalho'])
            
            # Valor
            ws.merge_cells(f'{get_column_letter(col)}{row+1}:{get_column_letter(col+1)}{row+1}')
            ws[f'{get_column_letter(col)}{row+1}'] = valor
            ws[f'{get_column_letter(col)}{row+1}'].font = Font(size=20, bold=True)
            ws[f'{get_column_letter(col)}{row+1}'].alignment = Alignment(horizontal='center')
            
            # Descrição
            ws.merge_cells(f'{get_column_letter(col)}{row+2}:{get_column_letter(col+1)}{row+2}')
            ws[f'{get_column_letter(col)}{row+2}'] = desc
            ws[f'{get_column_letter(col)}{row+2}'].alignment = Alignment(horizontal='center')
        
        # Ajusta larguras e alturas
        for col in range(1, 9):
            ws.column_dimensions[get_column_letter(col)].width = 15
        
        for r in range(row, row + 3):
            ws.row_dimensions[r].height = 30
    def _aplicar_estilo(self, cell, estilo):
        """Aplica estilo a uma célula"""
        if isinstance(estilo, dict):
            if 'font' in estilo:
                cell.font = estilo['font']
            if 'fill' in estilo:
                cell.fill = estilo['fill']
            if 'alignment' in estilo:
                cell.alignment = estilo['alignment']
            if 'border' in estilo:
                cell.border = estilo['border']
        else:
            # Se estilo for PatternFill direto
            cell.fill = estilo


    def _formatar_resumo_ia_com_termos(self, documento_obj):
        if not documento_obj:
            return "Documento não disponível"

        resumo_base = documento_obj.resumo or ""
        texto_para_analise = documento_obj.texto_completo or resumo_base

        # Formata o resumo base (como você já faz)
        resumo_formatado = re.sub(r'\n+', ' ', resumo_base).strip()
        if len(resumo_formatado) > 250: # Limite para o resumo principal
            resumo_truncado = resumo_formatado[:250]
            ultimo_ponto = resumo_truncado.rfind('.')
            if ultimo_ponto > 150:
                resumo_formatado = resumo_truncado[:ultimo_ponto + 1]
            else:
                resumo_formatado = resumo_truncado + "..."
        
        if not resumo_formatado:
            resumo_formatado = "Resumo não gerado ou indisponível."

        # Identifica termos monitorados encontrados
        termos_encontrados = []
        termos_monitorados_ativos = TermoMonitorado.objects.filter(ativo=True)
        for termo_obj in termos_monitorados_ativos:
            # Procura o termo principal e suas variações
            termos_para_buscar = [termo_obj.termo.lower()]
            if termo_obj.variacoes:
                termos_para_buscar.extend([v.strip().lower() for v in termo_obj.variacoes.split(',')])
            
            for t_busca in termos_para_buscar:
                if re.search(r'\b' + re.escape(t_busca) + r'\b', texto_para_analise.lower()):
                    if termo_obj.termo not in termos_encontrados: # Adiciona apenas o termo principal
                        termos_encontrados.append(termo_obj.termo)
                    break # Para de procurar variações se o termo principal ou uma variação foi encontrada

        output_final = resumo_formatado
        if termos_encontrados:
            output_final += f"\n\nTermos Relevantes Encontrados: {', '.join(termos_encontrados)}."
        
        return output_final

class AnaliseIA:
    """Classe para análises com Inteligência Artificial"""
    
    def __init__(self):
        self.ia_gratuita = IAGratuita()
    
    def gerar_resumo_executivo(self, documentos, normas):
        """Gera resumo executivo com insights de IA"""
        try:
            # Estatísticas básicas
            total_documentos = len(documentos)
            documentos_contabeis = len([d for d in documentos if d.relevante_contabil])
            taxa_relevancia = (documentos_contabeis / total_documentos * 100) if total_documentos > 0 else 0
            
            total_normas = len(normas)
            normas_vigentes = len([n for n in normas if n.situacao == 'VIGENTE'])
            normas_revogadas = len([n for n in normas if n.situacao == 'REVOGADA'])
            normas_problematicas = len([n for n in normas if n.situacao in ['REVOGADA', 'NÃO ENCONTRADA']])
            
            # Determina período de análise
            if documentos:
                data_inicio = min(d.data_publicacao for d in documentos)
                data_fim = max(d.data_publicacao for d in documentos)
                periodo_analise = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
            else:
                periodo_analise = "Sem dados"
            
            # Calcula risco de compliance
            if normas_problematicas / total_normas > 0.3 if total_normas > 0 else True:
                risco_compliance = "ALTO"
            elif normas_problematicas / total_normas > 0.1 if total_normas > 0 else False:
                risco_compliance = "MÉDIO"
            else:
                risco_compliance = "BAIXO"
            
            # Gera insights com IA
            insights_ia = self._gerar_insights_executivos(documentos, normas)
            
            # Análise de sentimento dos documentos
            analise_sentimento = self._analisar_sentimento_geral(documentos)
            
            # Extrai palavras-chave do período
            palavras_chave_periodo = self._extrair_palavras_chave_periodo(documentos)
            
            # Identifica fontes principais
            fontes_principais = self._identificar_fontes_principais(documentos)
            
            # Gera recomendações baseadas em IA
            recomendacoes = self._gerar_recomendacoes_ia(documentos, normas)
            
            return {
                'periodo_analise': periodo_analise,
                'total_documentos': total_documentos,
                'documentos_contabeis': documentos_contabeis,
                'taxa_relevancia_contabil': f"{taxa_relevancia:.1f}%",
                'total_normas': total_normas,
                'normas_vigentes': normas_vigentes,
                'normas_revogadas': normas_revogadas,
                'normas_problematicas': normas_problematicas,
                'risco_compliance': risco_compliance,
                'insights_ia': insights_ia,
                'analise_sentimento': analise_sentimento,
                'palavras_chave_periodo': palavras_chave_periodo,
                'fontes_principais': fontes_principais,
                'recomendacoes': recomendacoes
            }
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo executivo: {e}")
            return self._resumo_fallback(documentos, normas)
    
    def _gerar_insights_executivos(self, documentos, normas):
        """Gera insights executivos usando IA"""
        insights = []
        
        try:
            # Insight sobre evolução temporal
            if len(documentos) > 10:
                docs_recentes = [d for d in documentos if d.data_publicacao >= datetime.now().date() - timedelta(days=90)]
                if docs_recentes:
                    taxa_recente = len([d for d in docs_recentes if d.relevante_contabil]) / len(docs_recentes) * 100
                    
                    if taxa_recente > 70:
                        insights.append({
                            'titulo': 'Alta Atividade Regulatória Recente',
                            'descricao': f'Nos últimos 90 dias houve {len(docs_recentes)} publicações com {taxa_recente:.1f}% de relevância contábil.',
                            'relevancia': 'alta'
                        })
            
            # Insight sobre compliance
            normas_nao_verificadas = len([n for n in normas if not n.data_verificacao])
            if normas_nao_verificadas > len(normas) * 0.2:  # Mais de 20% não verificadas
                insights.append({
                    'titulo': 'Necessidade de Atualização de Normas',
                    'descricao': f'{normas_nao_verificadas} normas não foram verificadas recentemente.',
                    'relevancia': 'crítica'
                })
            
            # Insight sobre padrões identificados
            tipos_freq = defaultdict(int)
            for doc in documentos:
                if doc.tipo_documento:
                    tipos_freq[doc.tipo_documento] += 1
            
            if tipos_freq:
                tipo_mais_comum = max(tipos_freq.items(), key=lambda x: x[1])
                insights.append({
                    'titulo': f'Predominância de {tipo_mais_comum[0]}',
                    'descricao': f'O tipo de documento mais frequente é {tipo_mais_comum[0]} com {tipo_mais_comum[1]} ocorrências.',
                    'relevancia': 'média'
                })
            
            return insights
            
        except Exception as e:
            logger.error(f"Erro ao gerar insights executivos: {e}")
            return []
    
    def _analisar_sentimento_geral(self, documentos):
        """Analisa o sentimento geral dos documentos"""
        try:
            if not documentos:
                return None
            
            # Pega uma amostra de documentos para análise
            amostra = documentos[:20] if len(documentos) > 20 else documentos
            sentimentos = []
            
            for doc in amostra:
                texto = doc.resumo or doc.titulo or doc.assunto or ""
                if texto:
                    resultado = self.ia_gratuita.analisar_sentimento_documento(texto)
                    if resultado and 'sentimento' in resultado:
                        sentimentos.append(resultado['sentimento'])
            
            if sentimentos:
                # Conta os sentimentos
                contador = Counter(sentimentos)
                predominante = contador.most_common(1)[0][0]
                
                # Interpreta o resultado
                interpretacoes = {
                    'positivo': 'Documentos indicam cenário favorável e estável',
                    'neutro': 'Documentos apresentam tom técnico e informativo',
                    'negativo': 'Documentos indicam necessidade de atenção e ajustes'
                }
                
                return {
                    'predominante': predominante,
                    'interpretacao': interpretacoes.get(predominante, 'Tom não identificado'),
                    'distribuicao': dict(contador)
                }
            
        except Exception as e:
            logger.error(f"Erro na análise de sentimento: {e}")
        
        return None
    
    def _extrair_palavras_chave_periodo(self, documentos):
        """Extrai palavras-chave do período usando IA"""
        try:
            if not documentos:
                return []
            
            # Combina textos dos documentos mais recentes
            textos = []
            for doc in documentos[:30]:  # Últimos 30 documentos
                texto = ""
                if doc.titulo:
                    texto += doc.titulo + " "
                if doc.resumo:
                    texto += doc.resumo + " "
                if doc.assunto:
                    texto += doc.assunto + " "
                
                if texto.strip():
                    textos.append(texto.strip())
            
            if textos:
                texto_combinado = " ".join(textos)
                palavras_chave = self.ia_gratuita.extrair_palavras_chave_ia(texto_combinado, 10)
                return palavras_chave[:8]  # Retorna top 8
            
        except Exception as e:
            logger.error(f"Erro ao extrair palavras-chave: {e}")
        
        return []
    
    def _identificar_fontes_principais(self, documentos):
        """Identifica as fontes principais dos documentos"""
        try:
            fontes = defaultdict(int)
            for doc in documentos:
                if doc.fonte:
                    fontes[doc.fonte_documento] += 1
            
            # Retorna as 5 principais
            return dict(sorted(fontes.items(), key=lambda x: x[1], reverse=True)[:5])
            
        except Exception as e:
            logger.error(f"Erro ao identificar fontes: {e}")
            return {}
    
    def _gerar_recomendacoes_ia(self, documentos, normas):
        """Gera recomendações baseadas em análise IA"""
        recomendacoes = []
        
        try:
            # Recomendação sobre normas não verificadas
            nao_verificadas = len([n for n in normas if not n.data_verificacao])
            if nao_verificadas > 0:
                tipo = 'CRÍTICO' if nao_verificadas > len(normas) * 0.3 else 'IMPORTANTE'
                recomendacoes.append({
                    'titulo': 'Verificação de Normas Pendentes',
                    'descricao': f'{nao_verificadas} normas precisam ser verificadas quanto ao status atual.',
                    'tipo': tipo,
                    'acao': 'Realizar verificação sistemática das normas não atualizadas'
                })
            
            # Recomendação sobre documentos não processados
            nao_processados = len([d for d in documentos if not d.processado])
            if nao_processados > 0:
                recomendacoes.append({
                    'titulo': 'Processamento de Documentos Pendentes',
                    'descricao': f'{nao_processados} documentos estão aguardando processamento completo.',
                    'tipo': 'IMPORTANTE',
                    'acao': 'Finalizar análise e categorização dos documentos pendentes'
                })
            
            # Recomendação sobre baixa relevância contábil
            if documentos:
                taxa_relevancia = len([d for d in documentos if d.relevante_contabil]) / len(documentos)
                if taxa_relevancia < 0.3:  # Menos de 30% relevantes
                    recomendacoes.append({
                        'titulo': 'Revisão dos Critérios de Relevância',
                        'descricao': f'Apenas {taxa_relevancia:.1%} dos documentos foram classificados como relevantes contabilmente.',
                        'tipo': 'IMPORTANTE',
                        'acao': 'Revisar e ajustar critérios de classificação de relevância contábil'
                    })
            
            # Recomendação sobre diversificação de fontes
            if len(self._identificar_fontes_principais(documentos)) < 3:
                recomendacoes.append({
                    'titulo': 'Diversificação de Fontes',
                    'descricao': 'Poucas fontes de informação identificadas no sistema.',
                    'tipo': 'SUGESTÃO',
                    'acao': 'Considerar ampliação das fontes de monitoramento regulatório'
                })
            
            return recomendacoes
            
        except Exception as e:
            logger.error(f"Erro ao gerar recomendações: {e}")
            return []
    
    def analisar_tendencias_normativas(self, documentos):
        """Analisa tendências nas normas citadas"""
        try:
            # Extrai referências a normas dos documentos
            normas_citadas = defaultdict(int)
            assuntos_freq = defaultdict(int)
            
            for doc in documentos:
                # Busca padrões de normas no texto
                texto_completo = f"{doc.titulo or ''} {doc.resumo or ''} {doc.assunto or ''}"
                
                # Padrões básicos de normas (pode ser melhorado com regex mais sofisticado)
                import re
                padroes_normas = [
                    r'Lei\s+(?:nº\s*)?(\d+(?:/\d+)?)',
                    r'Decreto\s+(?:nº\s*)?(\d+(?:/\d+)?)',
                    r'Resolução\s+(?:nº\s*)?(\d+(?:/\d+)?)',
                    r'Instrução\s+Normativa\s+(?:nº\s*)?(\d+(?:/\d+)?)',
                    r'CPC\s+(\d+)',
                    r'NBC\s+([A-Z]+\s*\d+)'
                ]
                
                for padrao in padroes_normas:
                    matches = re.findall(padrao, texto_completo, re.IGNORECASE)
                    for match in matches:
                        tipo_norma = padrao.split('\\')[0].replace('(?:nº\\s*)?', '').strip()
                        norma_completa = f"{tipo_norma} {match}"
                        normas_citadas[norma_completa] += 1
                
                # Analisa assuntos
                if doc.assunto:
                    palavras_assunto = doc.assunto.lower().split()
                    for palavra in palavras_assunto:
                        if len(palavra) > 3:  # Ignora palavras muito pequenas
                            assuntos_freq[palavra] += 1
            
            # Identifica assuntos emergentes (simplificado)
            assuntos_emergentes = []
            if len(documentos) > 10:
                docs_recentes = documentos[:len(documentos)//2]  # Primeira metade (mais recentes)
                docs_antigos = documentos[len(documentos)//2:]   # Segunda metade (mais antigos)
                
                assuntos_recentes = defaultdict(int)
                assuntos_antigos = defaultdict(int)
                
                for doc in docs_recentes:
                    if doc.assunto:
                        for palavra in doc.assunto.lower().split():
                            if len(palavra) > 3:
                                assuntos_recentes[palavra] += 1
                
                for doc in docs_antigos:
                    if doc.assunto:
                        for palavra in doc.assunto.lower().split():
                            if len(palavra) > 3:
                                assuntos_antigos[palavra] += 1
                
                # Calcula crescimento
                for assunto, freq_recente in assuntos_recentes.items():
                    freq_antiga = assuntos_antigos.get(assunto, 0)
                    if freq_antiga > 0:
                        crescimento = ((freq_recente - freq_antiga) / freq_antiga) * 100
                        if crescimento > 50:  # Crescimento significativo
                            assuntos_emergentes.append((assunto, int(crescimento)))
                    elif freq_recente > 2:  # Novo assunto com frequência relevante
                        assuntos_emergentes.append((assunto, 100))  # 100% novo
            
            return {
                'normas_mais_citadas': sorted(normas_citadas.items(), key=lambda x: x[1], reverse=True),
                'assuntos_emergentes': sorted(assuntos_emergentes, key=lambda x: x[1], reverse=True),
                'assuntos_frequentes': sorted(assuntos_freq.items(), key=lambda x: x[1], reverse=True)
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de tendências: {e}")
            return {
                'normas_mais_citadas': [],
                'assuntos_emergentes': [],
                'assuntos_frequentes': []
            }
    
    def _resumo_fallback(self, documentos, normas):
        """Retorna resumo básico em caso de erro na IA"""
        total_documentos = len(documentos)
        documentos_contabeis = len([d for d in documentos if d.relevante_contabil])
        total_normas = len(normas)
        normas_vigentes = len([n for n in normas if n.situacao == 'VIGENTE'])
        
        return {
            'periodo_analise': 'Não disponível',
            'total_documentos': total_documentos,
            'documentos_contabeis': documentos_contabeis,
            'taxa_relevancia_contabil': f"{(documentos_contabeis/total_documentos*100):.1f}%" if total_documentos > 0 else "0%",
            'total_normas': total_normas,
            'normas_vigentes': normas_vigentes,
            'normas_revogadas': 0,
            'normas_problematicas': 0,
            'risco_compliance': 'NÃO CALCULADO',
            'insights_ia': [],
            'analise_sentimento': None,
            'palavras_chave_periodo': [],
            'fontes_principais': {},
            'recomendacoes': []
        }


class IAGratuita:
    """Classe para integração com serviços de IA gratuitos"""
    
    def __init__(self):
        # Aqui você pode configurar APIs gratuitas como Hugging Face, etc.
        pass
    
    def gerar_resumo_inteligente(self, texto, max_palavras=100):
        """Gera resumo inteligente do texto (versão simplificada)"""
        try:
            if not texto or len(texto.strip()) == 0:
                return "Texto não disponível para resumo"
            
            # Implementação simplificada - em produção, use uma API de IA
            frases = texto.split('.')
            frases = [f.strip() for f in frases if f.strip()]
            
            if len(frases) <= 2:
                return texto[:max_palavras*7]  # Aproximadamente 7 chars por palavra
            
            # Pega as primeiras e últimas frases mais relevantes
            resumo_frases = []
            if frases:
                resumo_frases.append(frases[0])  # Primeira frase
                if len(frases) > 2:
                    resumo_frases.append(frases[len(frases)//2])  # Frase do meio
                if len(frases) > 1:
                    resumo_frases.append(frases[-1])  # Última frase
            
            resumo = '. '.join(resumo_frases)
            
            # Trunca se necessário
            palavras = resumo.split()
            if len(palavras) > max_palavras:
                resumo = ' '.join(palavras[:max_palavras]) + '...'
            
            return resumo
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {e}")
            return "Erro na geração do resumo"
    
    def extrair_palavras_chave_ia(self, texto, quantidade=5):
        """Extrai palavras-chave do texto (versão simplificada)"""
        try:
            if not texto:
                return []
            
            # Implementação simplificada - em produção, use TF-IDF ou NLP
            import re
            from collections import Counter
            
            # Remove pontuação e converte para minúsculas
            texto_limpo = re.sub(r'[^\w\s]', ' ', texto.lower())
            palavras = texto_limpo.split()
            
            # Remove palavras muito comuns (stop words básicas)
            stop_words = {
                'a', 'o', 'e', 'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na', 'nos', 'nas',
                'por', 'para', 'com', 'sem', 'sob', 'sobre', 'entre', 'que', 'se', 'é', 'são',
                'foi', 'será', 'ter', 'tem', 'sua', 'seu', 'seus', 'suas', 'este', 'esta',
                'isto', 'esse', 'essa', 'isso', 'aquele', 'aquela', 'aquilo', 'um', 'uma',
                'uns', 'umas', 'como', 'quando', 'onde', 'porque', 'assim', 'mais', 'menos',
                'muito', 'pouco', 'bem', 'mal', 'já', 'ainda', 'também', 'só', 'apenas'
            }
            
            # Filtra palavras relevantes
            palavras_relevantes = [
                palavra for palavra in palavras 
                if len(palavra) > 3 and palavra not in stop_words
            ]
            
            # Conta frequência
            contador = Counter(palavras_relevantes)
            
            # Retorna as mais frequentes
            return [palavra for palavra, freq in contador.most_common(quantidade)]
            
        except Exception as e:
            logger.error(f"Erro ao extrair palavras-chave: {e}")
            return []
    
    def analisar_sentimento_documento(self, texto):
        """Analisa sentimento do documento (versão simplificada)"""
        try:
            if not texto:
                return {'sentimento': 'neutro', 'confianca': 0.5}
            
            # Implementação simplificada baseada em palavras-chave
            palavras_positivas = {
                'aprovado', 'aprovação', 'benefício', 'melhoria', 'otimização', 'eficiência',
                'crescimento', 'desenvolvimento', 'sucesso', 'adequado', 'conforme', 'regular',
                'estável', 'favorável', 'positivo', 'satisfatório', 'cumprido'
            }
            
            palavras_negativas = {
                'problema', 'erro', 'falha', 'inadequado', 'irregular', 'pendente', 'atraso',
                'risco', 'atenção', 'cuidado', 'revisão', 'correção', 'ajuste', 'não conforme',
                'violação', 'infração', 'multa', 'penalidade', 'descumprimento', 'crítico'
            }
            
            texto_lower = texto.lower()
            
            score_positivo = sum(1 for palavra in palavras_positivas if palavra in texto_lower)
            score_negativo = sum(1 for palavra in palavras_negativas if palavra in texto_lower)
            
            if score_positivo > score_negativo:
                sentimento = 'positivo'
                confianca = min(0.8, 0.5 + (score_positivo - score_negativo) * 0.1)
            elif score_negativo > score_positivo:
                sentimento = 'negativo'
                confianca = min(0.8, 0.5 + (score_negativo - score_positivo) * 0.1)
            else:
                sentimento = 'neutro'
                confianca = 0.6
            
            return {
                'sentimento': sentimento,
                'confianca': confianca,
                'score_positivo': score_positivo,
                'score_negativo': score_negativo
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de sentimento: {e}")
            return {'sentimento': 'neutro', 'confianca': 0.5}
    
    def gerar_insights_automaticos(self, documentos, normas):
        """Gera insights automáticos baseados nos dados"""
        insights = []
        
        try:
            # Insight sobre volume de documentos
            if len(documentos) > 100:
                insights.append({
                    'titulo': 'Alto Volume de Documentos',
                    'descricao': f'Sistema processou {len(documentos)} documentos, indicando alta atividade regulatória.',
                    'relevancia': 'alta'
                })
            
            # Insight sobre compliance
            normas_vigentes = len([n for n in normas if n.situacao == 'VIGENTE'])
            if normas_vigentes / len(normas) > 0.8 if normas else False:
                insights.append({
                    'titulo': 'Boa Taxa de Compliance',
                    'descricao': f'{(normas_vigentes/len(normas)*100):.1f}% das normas estão vigentes.',
                    'relevancia': 'média'
                })
            
            # Insight sobre processamento
            nao_processados = len([d for d in documentos if not d.processado])
            if nao_processados > len(documentos) * 0.1:  # Mais de 10%
                insights.append({
                    'titulo': 'Documentos Aguardando Processamento',
                    'descricao': f'{nao_processados} documentos ainda não foram totalmente processados.',
                    'relevancia': 'crítica'
                })
            
            return insights
            
        except Exception as e:
            logger.error(f"Erro ao gerar insights automáticos: {e}")
            return []