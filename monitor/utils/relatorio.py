import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Tuple
import re
import requests # Usado pela sua classe MistralAI
from urllib.parse import urlparse # Para extrair domínio da URL, se necessário

from django.conf import settings
from django.db.models import Count, Q, Max, Min, Avg, F, Case, When, Value, CharField
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from openpyxl.drawing.image import Image
from datetime import datetime, timedelta, date # <--- ADICIONE 'date' AQUI
from django.utils import timezone # Você já deve ter esta
from .pdf_processor import MistralAI
from monitor.models import Documento, NormaVigente, TermoMonitorado, RelatorioGerado # Adicionado TermoMonitorado e RelatorioGerado

logger = logging.getLogger(__name__)

# --- INÍCIO DA CLASSE MistralAI (COPIADA DO SEU PDF_PROCESSOR.PY PARA CONTEXTO) ---
# Se esta classe estiver em pdf_processor.py, você não precisa redefini-la aqui,
# apenas certifique-se de que RelatorioAvancado possa instanciá-la ou receber uma instância.
# Para este exemplo, vou incluir uma versão simplificada dela aqui para o código rodar.
# No seu projeto real, a classe MistralAI definida em pdf_processor.py seria usada.

MISTRAL_API_KEY_RELATORIO = os.environ.get("MISTRAL_API_KEY", "AaODvu2cz9KAi55Jxal8NhjvpT1VyjBO") # Carregue de forma segura!
MISTRAL_API_URL_RELATORIO = "https://api.mistral.ai/v1/chat/completions"

class MistralAIRelatorioAdapter: # Renomeado para evitar conflito se você importar de pdf_processor
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY_RELATORIO}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.default_model = "mistral-small-latest"
        self.default_temperature = 0.2
        if not MISTRAL_API_KEY_RELATORIO or MISTRAL_API_KEY_RELATORIO == "AaODvu2cz9KAi55Jxal8NhjvpT1VyjBO": # Exemplo de verificação
             logger.warning("Chave da API Mistral para Relatório não parece ser uma chave de produção.")
        # Não há um self.client aqui na sua implementação original, você usa requests.post diretamente


    def _call_mistral(self, messages: List[Dict[str, str]], model: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Optional[str]:
        if not MISTRAL_API_KEY_RELATORIO or MISTRAL_API_KEY_RELATORIO in ["SuaChaveAqui", "COLOQUE_SUA_CHAVE_AQUI"]:
            logger.error("Chave da API Mistral não configurada corretamente para Relatório.")
            return "Erro: Chave da API Mistral (Relatório) não configurada."
        data = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "stream": False
        }
        if max_tokens: data["max_tokens"] = max_tokens

        max_retries = 5
        for tentativa in range(max_retries):
            try:
                response = requests.post(MISTRAL_API_URL_RELATORIO, headers=self.headers, json=data, timeout=60)
                if response.status_code == 429:
                    wait_time = 2 ** tentativa
                    logger.warning(f"Rate limit atingido (429). Tentativa {tentativa+1}/{max_retries}. Aguardando {wait_time}s antes de tentar novamente...")
                    time.sleep(wait_time)
                    continue
                response.raise_for_status()
                response_json = response.json()
                if response_json.get("choices") and len(response_json["choices"]) > 0:
                    content = response_json["choices"][0].get("message", {}).get("content")
                    return content.strip() if content else "Resposta da IA vazia."
                return "Formato de resposta da IA inesperado."
            except requests.exceptions.HTTPError as http_err:
                if response.status_code == 429 and tentativa < max_retries - 1:
                    wait_time = 2 ** tentativa
                    logger.warning(f"HTTP 429 novamente. Esperando {wait_time}s para nova tentativa.")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Erro HTTP Mistral: {http_err} - Resp: {response.text if 'response' in locals() else 'N/A'}", exc_info=True)
                return f"Erro HTTP {http_err.response.status_code}."
            except Exception as e:
                logger.error(f"Erro chamada Mistral: {e}", exc_info=True)
                return f"Erro API: {e}"
        return "Erro: Limite de tentativas excedido ao comunicar com a API Mistral."

    def gerar_insight_conjunto_documentos(self, documentos_para_analise: List[Dict]) -> str:
        if not documentos_para_analise:
            return "Nenhum documento fornecido para análise consolidada."

        textos_concatenados = "\n\n---\n\n".join(
            f"Documento Título: {d['titulo']}\nData: {d['data_publicacao']}\nResumo IA: {d['resumo_ia']}\nPontos Críticos IA: {'; '.join(d['pontos_criticos_ia'])}"
            for d in documentos_para_analise
        )

        system_prompt = (
            "Você é um Analista de Inteligência Regulatória Sênior, especializado em identificar padrões e "
            "tendências em múltiplos documentos fiscais e contábeis do Piauí. Sua tarefa é fornecer um "
            "insight consolidado sobre os documentos apresentados."
        )
        user_prompt = (
            f"Com base na seguinte lista de documentos fiscais/contábeis relevantes e seus respectivos resumos e pontos críticos gerados por IA, "
            f"forneça uma ANÁLISE CONSOLIDADA (1-3 parágrafos curtos) sobre os temas ou impactos mais recorrentes ou significativos "
            f"que emergem do conjunto. Há alguma tendência notável ou alerta geral para os contadores?\n\n"
            f"Dados dos Documentos:\n\"\"\"\n{textos_concatenados[:14000]}\n\"\"\"\n\n"
            f"Análise Consolidada e Tendências Emergentes:"
        )
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        return self._call_mistral(messages, max_tokens=500, temperature=0.3) or "Não foi possível gerar o insight consolidado."

# --- FIM DA CLASSE MistralAIRelatorioAdapter ---


class AnaliseIA: # Sua classe AnaliseIA existente
    """Classe responsável por análises avançadas com IA dos documentos e normas"""

    def __init__(self, mistral_client_instance: Optional[MistralAIRelatorioAdapter] = None):
        # Recebe uma instância do cliente Mistral para não recriá-lo sempre,
        # ou cria uma nova se não for passada.
        self.mistral_adapter = mistral_client_instance if mistral_client_instance else MistralAIRelatorioAdapter()

    # Seus métodos estáticos _identificar_fontes_principais, _contar_tipos_normas,
    # _analisar_sentimentos_agregados, _identificar_assuntos_emergentes,
    # _calcular_risco_compliance, _gerar_recomendacoes_ia (precisarão de prompts para Mistral)
    # e _gerar_insights_automaticos permanecem aqui.
    # Vou adaptar _identificar_fontes_principais para usar 'fonte_documento'
    # e _gerar_insights_automaticos para potencialmente usar a Mistral.

    @staticmethod
    def _identificar_fontes_principais(documentos: List[Documento]) -> Dict[str, int]:
        logger.debug(f"Iniciando _identificar_fontes_principais para {len(documentos)} documentos.")
        fontes = defaultdict(int)
        try:
            for doc in documentos:
                fonte_val = None
                if hasattr(doc, 'fonte_documento') and doc.fonte_documento:
                    fonte_val = doc.fonte_documento.strip()
                elif doc.url_original:
                    try:
                        parsed_url = urlparse(doc.url_original)
                        fonte_val = parsed_url.netloc if parsed_url.netloc else doc.url_original
                    except: fonte_val = doc.url_original[:70] # Fallback
                
                if fonte_val:
                    fontes[fonte_val] += 1
                else:
                    fontes["Fonte Não Especificada"] += 1
            return dict(sorted(fontes.items(), key=lambda item: item[1], reverse=True)[:5])
        except Exception as e:
            logger.error(f"Erro em _identificar_fontes_principais: {e}", exc_info=True)
            return {"Erro na análise de fontes": 1}

    @staticmethod
    def _contar_tipos_normas(normas: List[NormaVigente]) -> Dict[str, int]:
        tipos = defaultdict(int)
        for norma in normas:
            tipos[norma.get_tipo_display()] += 1
        return dict(sorted(tipos.items(), key=lambda item: item[1], reverse=True))

    def _gerar_insights_automaticos(self, documentos: List[Documento], normas: List[NormaVigente]) -> List[Dict[str, str]]:
        """Gera insights com base em métricas e opcionalmente com IA para consolidação."""
        insights = []
        try:
            # Seus insights baseados em contagem (mantidos)
            if len(documentos) > 50: # Limite de exemplo
                insights.append({
                    'titulo': 'Alto Volume de Documentos',
                    'descricao': f'Sistema analisou {len(documentos)} documentos no período, indicando atividade regulatória significativa.',
                    'relevancia': 'alta'
                })
            
            normas_vigentes_count = len([n for n in normas if n.situacao == 'VIGENTE'])
            if normas and normas_vigentes_count / len(normas) > 0.8:
                insights.append({
                    'titulo': 'Boa Taxa de Conformidade de Normas',
                    'descricao': f'{(normas_vigentes_count/len(normas)*100):.1f}% das normas identificadas estão atualmente vigentes.',
                    'relevancia': 'média'
                })
            
            # Insight Consolidado da Mistral
            docs_para_insight_ia = []
            for doc in documentos:
                if doc.relevante_contabil and (hasattr(doc, 'resumo_ia') and doc.resumo_ia):
                    docs_para_insight_ia.append({
                        "titulo": doc.titulo,
                        "data_publicacao": doc.data_publicacao.strftime("%d/%m/%Y") if doc.data_publicacao else "N/D",
                        "resumo_ia": doc.resumo_ia[:300] + "..." if doc.resumo_ia and len(doc.resumo_ia) > 300 else doc.resumo_ia, # Envia resumos curtos
                        "pontos_criticos_ia": doc.metadata.get('ia_pontos_criticos', []) if hasattr(doc, 'metadata') and doc.metadata else []
                    })
            
            if docs_para_insight_ia: # Se houver documentos relevantes com resumos IA
                insight_consolidado_ia = self.mistral_adapter.gerar_insight_conjunto_documentos(docs_para_insight_ia[:5]) # Limita a 5 docs para o prompt
                if insight_consolidado_ia and "Erro" not in insight_consolidado_ia:
                    insights.append({
                        'titulo': 'Análise Consolidada por IA (Mistral)',
                        'descricao': insight_consolidado_ia,
                        'relevancia': 'alta'
                    })
            return insights
        except Exception as e:
            logger.error(f"Erro ao gerar insights automáticos: {e}", exc_info=True)
            return [{'titulo': 'Erro nos Insights', 'descricao': str(e), 'relevancia': 'crítica'}]

    # Outros métodos da AnaliseIA podem ser adaptados para usar self.mistral_adapter
    # se precisarem de mais poder de IA.


class RelatorioAvancado:
    """Gera um relatório avançado em formato Excel com múltiplas abas e análises."""

    CORES = { # Mantido do seu original
        'cabecalho': '4F81BD',
        'subcabecalho': 'B8CCE4',
        'destaque': 'FCD5B4',
        'sucesso': 'C6EFCE',
        'aviso': 'FFEB9C',
        'erro': 'FFC7CE',
        'neutro': 'D9D9D9',
        'zebra': 'F2F2F2',
    }

    def __init__(self):
        self.wb = Workbook()
        self.wb.remove(self.wb.active) # Remove a planilha padrão
        self.estilos = self._definir_estilos()
        self.mistral_ai = MistralAIRelatorioAdapter() # Instancia o adaptador Mistral
        self.analise_ia = AnaliseIA(mistral_client_instance=self.mistral_ai) # Passa a instância para AnaliseIA

    # Em monitor/utils/relatorio.py
# Dentro da classe RelatorioAvancado

    def _definir_estilos(self) -> Dict[str, NamedStyle]:
        estilos = {}
        border_thin_side = Side(border_style="thin", color="000000")
        default_border = Border(top=border_thin_side, left=border_thin_side, right=border_thin_side, bottom=border_thin_side)

        # Estilo Cabeçalho Principal
        estilos['cabecalho_principal'] = NamedStyle(name='cabecalho_principal_relatorio') # Nome único para o estilo
        estilos['cabecalho_principal'].font = Font(name='Calibri', size=16, bold=True, color="FFFFFF")
        estilos['cabecalho_principal'].fill = PatternFill(start_color=self.CORES['cabecalho'], end_color=self.CORES['cabecalho'], fill_type="solid")
        estilos['cabecalho_principal'].alignment = Alignment(horizontal="center", vertical="center")
        estilos['cabecalho_principal'].border = default_border


        # Estilo Título de Seção
        estilos['titulo_secao'] = NamedStyle(name='titulo_secao_relatorio')
        estilos['titulo_secao'].font = Font(name='Calibri', size=12, bold=True, color=self.CORES['cabecalho'])
        # estilos['titulo_secao'].border = default_border # Opcional para títulos de seção

        # Estilo Cabeçalho de Tabela
        estilos['cabecalho_tabela'] = NamedStyle(name='cabecalho_tabela_relatorio')
        estilos['cabecalho_tabela'].font = Font(name='Calibri', size=11, bold=True, color="FFFFFF")
        estilos['cabecalho_tabela'].fill = PatternFill(start_color=self.CORES['subcabecalho'], end_color=self.CORES['subcabecalho'], fill_type="solid")
        estilos['cabecalho_tabela'].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        estilos['cabecalho_tabela'].border = default_border

        # Estilos para células de dados
        estilos['dados_texto'] = NamedStyle(name='dados_texto_relatorio')
        estilos['dados_texto'].font = Font(name='Calibri', size=10)
        estilos['dados_texto'].alignment = Alignment(vertical="top", wrap_text=True, horizontal="left") # Adicionado horizontal left
        estilos['dados_texto'].border = default_border

        # Estilo para dados numéricos (baseado em dados_texto, mas com alinhamento diferente)
        estilos['dados_numero'] = NamedStyle(name='dados_numero_relatorio')
        estilos['dados_numero'].font = Font(name='Calibri', size=10) # Herda visualmente de dados_texto
        estilos['dados_numero'].alignment = Alignment(horizontal="right", vertical="top", wrap_text=False) # Modificação
        estilos['dados_numero'].border = default_border # Herda visualmente de dados_texto

        # Estilo para dados de data (baseado em dados_texto, mas com formato e alinhamento diferentes)
        estilos['dados_data'] = NamedStyle(name='dados_data_relatorio')
        estilos['dados_data'].font = Font(name='Calibri', size=10) # Herda visualmente de dados_texto
        estilos['dados_data'].number_format = 'DD/MM/YYYY' # Modificação
        estilos['dados_data'].alignment = Alignment(horizontal="center", vertical="top", wrap_text=False) # Modificação
        estilos['dados_data'].border = default_border # Herda visualmente de dados_texto



        for status_cor, cor_hex in self.CORES.items():

            estilos[f'fill_{status_cor}'] = PatternFill(start_color=cor_hex, end_color=cor_hex, fill_type="solid")

        return estilos
        
    # Dentro da classe RelatorioAvancado em relatorio.py
    def _aplicar_estilo_celula(self, celula, estilo_base_nome: str, estilo_fill_cor_nome: Optional[str] = None): # Renomeei para clareza
        """
        Aplica um estilo base (NamedStyle) e um estilo de preenchimento (PatternFill) opcional.
        estilo_fill_cor_nome deve ser a chave da cor em self.CORES, ex: 'sucesso', 'zebra'.
        """
        if estilo_base_nome in self.estilos:
            celula.style = self.estilos[estilo_base_nome] # Aplica o NamedStyle base

        # Aplica o PatternFill diretamente
        if estilo_fill_cor_nome and f'fill_{estilo_fill_cor_nome}' in self.estilos:
            # self.estilos[f'fill_{estilo_fill_cor_nome}'] já é um objeto PatternFill
            celula.fill = self.estilos[f'fill_{estilo_fill_cor_nome}'] # <--- CORREÇÃO AQUI


    def _criar_planilha_documentos_avancada(self, documentos: List[Documento]):
        """Cria a aba de Documentos com informações detalhadas e análises da IA."""
        ws = self.wb.create_sheet(title="📄 Documentos Detalhados")

        cabecalhos = [
            "ID", "Data Public.", "Título do Documento", "Tipo Documento", "Fonte Documento", "URL Original",
            "Relevante (IA)", "Justificativa Relevância (IA)", "Pontos Críticos (IA)",
            "Resumo IA", "Sentimento (IA)", "Impacto Fiscal (IA)",
            "Normas Extraídas (Regex)", "Qtd Normas",
            "Processado?", "Data Processamento", "Data Coleta"
        ]

        for col, cabecalho_texto in enumerate(cabecalhos, 1):
            cell = ws.cell(row=1, column=col, value=cabecalho_texto)
            # Supondo que self._aplicar_estilo_celula e self.estilos estão definidos corretamente
            self._aplicar_estilo_celula(cell, 'cabecalho_tabela')

        row_num = 2
        for doc in documentos:
            # Dados da IA (já devem estar no objeto Documento, preenchidos pelo PDFProcessor)
            justificativa_ia = doc.metadata.get('ia_relevancia_justificativa', "N/A") if hasattr(doc, 'metadata') and doc.metadata else "N/A"
            pontos_criticos_ia_lista = doc.metadata.get('ia_pontos_criticos', []) if hasattr(doc, 'metadata') and doc.metadata else []
            pontos_criticos_ia_str = "\n".join([f"- {p}" for p in pontos_criticos_ia_lista]) if pontos_criticos_ia_lista else "N/A"
            
            resumo_ia_val = getattr(doc, 'resumo_ia', doc.resumo or "N/A") # Usa resumo_ia se existir, senão resumo principal
            sentimento_ia_val = getattr(doc, 'sentimento_ia', "N/A")
            # Supondo que impacto_fiscal é um campo TextField ou CharField no modelo Documento
            # Se for um JSONField ou algo mais complexo, ajuste a forma de obter o valor.
            impacto_fiscal_ia_val = getattr(doc, 'impacto_fiscal_ia', getattr(doc, 'impacto_fiscal', "N/A"))


            normas_extraidas_obj = doc.normas_relacionadas.all()
            normas_extraidas_str = "\n".join([f"- {n.get_tipo_display()} {n.numero}/{n.ano if n.ano else ''}" for n in normas_extraidas_obj]) if normas_extraidas_obj.exists() else "Nenhuma"
            qtd_normas = normas_extraidas_obj.count()

            dados_linha = [
                doc.id,
                doc.data_publicacao, # Será formatado pelo estilo 'dados_data'
                doc.titulo,
                doc.get_tipo_documento_display() if hasattr(doc, 'tipo_documento') and doc.tipo_documento else "N/A",
                doc.fonte_documento if hasattr(doc, 'fonte_documento') and doc.fonte_documento else "N/A",
                doc.url_original,
                "SIM" if doc.relevante_contabil else "NÃO",
                justificativa_ia,
                pontos_criticos_ia_str,
                resumo_ia_val,
                sentimento_ia_val,
                impacto_fiscal_ia_val,
                normas_extraidas_str,
                qtd_normas,
                "SIM" if doc.processado else "NÃO",
                getattr(doc, 'data_processamento', None), # Será formatado se for data
                doc.data_coleta # Será formatado se for data
            ]

            estilo_fill_linha = 'fill_zebra' if row_num % 2 == 0 else None

            for col_idx, cell_value in enumerate(dados_linha, 1):
                cell = ws.cell(row=row_num, column=col_idx, value=cell_value)
                # Aplica estilo base e de preenchimento
                # CORREÇÃO AQUI:
                if isinstance(cell_value, (datetime, date)): # Verifica se é datetime.datetime ou datetime.date
                    self._aplicar_estilo_celula(cell, 'dados_data', estilo_fill_linha)
                elif isinstance(cell_value, (int, float)) and col_idx == cabecalhos.index("Qtd Normas") + 1 : # Exemplo para Qtd Normas
                    self._aplicar_estilo_celula(cell, 'dados_numero', estilo_fill_linha)
                else: # Texto
                    self._aplicar_estilo_celula(cell, 'dados_texto', estilo_fill_linha)
                
                # Formatação condicional para relevância
                if cabecalhos[col_idx-1] == "Relevante (IA)":
                    if doc.relevante_contabil:
                        # Supondo que self.estilos['fill_sucesso'] é um PatternFill
                        cell.fill = self.estilos['fill_sucesso'] 
                    else:
                        cell.fill = self.estilos['fill_aviso'] 

            row_num += 1

        # Ajusta larguras
        larguras = [6, 12, 45, 18, 25, 35, 12, 40, 40, 50, 15, 40, 30, 10, 10, 18, 18]
        for i, largura_val in enumerate(larguras):
            if i < len(cabecalhos): # Garante que não exceda o número de colunas
                ws.column_dimensions[get_column_letter(i + 1)].width = largura_val



    def _criar_resumo_executivo(self, documentos: List[Documento], normas: List[NormaVigente]):
        """Cria a aba de Resumo Executivo com os principais insights e gráficos."""
        ws = self.wb.create_sheet(title="📊 Resumo Executivo")
        self._aplicar_estilo_celula(ws.cell(row=1, column=1, value="📊 Resumo Executivo e Insights Chave"), 'cabecalho_principal')
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5) # Mescla para o título

        row_idx = 3
        ws.cell(row=row_idx, column=1, value="Principais Métricas do Período").style = self.estilos['titulo_secao']
        row_idx += 1
        
        metricas = [
            ("Total de Documentos Analisados:", len(documentos)),
            ("Documentos Relevantes (IA):", len([d for d in documentos if d.relevante_contabil])),
            ("Total de Normas Identificadas:", len(normas)),
            ("Normas Vigentes:", len([n for n in normas if n.situacao == 'VIGENTE'])),
            ("Normas Revogadas:", len([n for n in normas if n.situacao == 'REVOGADA'])),
            ("Normas A Verificar:", len([n for n in normas if n.situacao == 'A_VERIFICAR'])),
        ]
        for desc, valor in metricas:
            ws.cell(row=row_idx, column=1, value=desc).style = self.estilos['dados_texto']
            ws.cell(row=row_idx, column=2, value=valor).style = self.estilos['dados_numero']
            row_idx += 1
        row_idx +=1 # Espaço

        ws.cell(row=row_idx, column=1, value="Insights Gerados pela Análise IA").style = self.estilos['titulo_secao']
        row_idx += 1
        
        # Usando a instância de AnaliseIA que agora tem acesso ao MistralAdapter
        insights_ia = self.analise_ia._gerar_insights_automaticos(documentos, normas)
        if insights_ia:
            for insight in insights_ia:
                ws.cell(row=row_idx, column=1, value=f"Insight: {insight.get('titulo', 'N/A')}").font = Font(bold=True)
                ws.cell(row=row_idx, column=1).style = self.estilos['dados_texto']
                row_idx +=1
                ws.cell(row=row_idx, column=1, value=insight.get('descricao', 'N/A')).style = self.estilos['dados_texto']
                ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=5)
                ws.row_dimensions[row_idx].height = 30 # Aumenta altura da linha para descrição
                row_idx +=1
                ws.cell(row=row_idx, column=1, value=f"Relevância Percebida: {insight.get('relevancia', 'N/A').upper()}").font = Font(italic=True)
                ws.cell(row=row_idx, column=1).style = self.estilos['dados_texto']
                row_idx += 2 # Espaço
        else:
            ws.cell(row=row_idx, column=1, value="Nenhum insight automático gerado.").style = self.estilos['dados_texto']
            row_idx +=1

        # Adicionar mais seções conforme os métodos da AnaliseIA, por exemplo:
        # - Fontes mais comuns
        # - Tipos de normas mais frequentes

        # Ajuste de colunas para esta aba
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 15
        ws.column_dimensions['E'].width = 15


    def _criar_dashboard_visual(self, documentos: List[Documento], normas: List[NormaVigente]):
        ws = self.wb.create_sheet(title="📊 Dashboard Visual")
        self._aplicar_estilo_celula(ws.cell(row=1, column=1, value="📊 Dashboard Visual de Compliance"), self.estilos['cabecalho_principal'])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5)
        
        row_idx = 3
        ws.cell(row=row_idx, column=1, value="Distribuição de Documentos por Relevância (IA)").style = self.estilos['titulo_secao']
        row_idx += 1

        relevantes_count = len([d for d in documentos if d.relevante_contabil])
        nao_relevantes_count = len(documentos) - relevantes_count
        ws.cell(row=row_idx, column=1, value="Relevantes").style = self.estilos['dados_texto']
        ws.cell(row=row_idx, column=2, value=relevantes_count).style = self.estilos['dados_numero']
        row_idx += 1
        ws.cell(row=row_idx, column=1, value="Não Relevantes").style = self.estilos['dados_texto']
        ws.cell(row=row_idx, column=2, value=nao_relevantes_count).style = self.estilos['dados_numero']
        row_idx += 1

        if relevantes_count + nao_relevantes_count > 0 :
            c1 = PieChart()
            labels = Reference(ws, min_col=1, min_row=row_idx -2, max_row=row_idx -1)
            data = Reference(ws, min_col=2, min_row=row_idx-2, max_row=row_idx-1)
            c1.add_data(data, titles_from_data=False)
            c1.set_categories(labels)
            c1.title = "Relevância de Documentos"
            ws.add_chart(c1, "D4") # Posição do gráfico

        row_idx += 8 # Espaço para o gráfico
        ws.cell(row=row_idx, column=1, value="Situação das Normas Identificadas").style = self.estilos['titulo_secao']
        row_idx += 1
        
        situacao_counts = Counter(n.get_situacao_display() for n in normas)
        for situacao, count in situacao_counts.items():
            ws.cell(row=row_idx, column=1, value=situacao).style = self.estilos['dados_texto']
            ws.cell(row=row_idx, column=2, value=count).style = self.estilos['dados_numero']
            row_idx+=1

        if situacao_counts:
            c2 = BarChart()
            c2.type = "col"
            c2.style = 10
            c2.title = "Situação das Normas"
            c2.y_axis.title = 'Quantidade'
            c2.x_axis.title = 'Status'
            data = Reference(ws, min_col=2, min_row=row_idx - len(situacao_counts), max_row=row_idx-1)
            cats = Reference(ws, min_col=1, min_row=row_idx - len(situacao_counts), max_row=row_idx-1)
            c2.add_data(data, titles_from_data=False)
            c2.set_categories(cats)
            ws.add_chart(c2, "D" + str(row_idx - len(situacao_counts) +2))

        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 15


    def _salvar_relatorio(self, nome_base: str = "relatorio_compliance") -> Optional[str]:
        """Salva o workbook e retorna o caminho relativo para o modelo."""
        try:
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios') # MEDIA_ROOT do Django settings
            os.makedirs(relatorios_dir, exist_ok=True) # Cria o diretório se não existir

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            nome_arquivo_excel = f"{nome_base}_{timestamp}.xlsx"
            caminho_completo = os.path.join(relatorios_dir, nome_arquivo_excel)

            self.wb.save(caminho_completo)
            logger.info(f"Relatório Excel gerado e salvo em: {caminho_completo}")

            # Retorna o caminho relativo a MEDIA_ROOT para ser salvo no FileField
            return os.path.join('relatorios', nome_arquivo_excel)
        except Exception as e:
            logger.error(f"Erro ao salvar o relatório Excel: {e}", exc_info=True)
            return None


    def gerar_relatorio_completo(self) -> Optional[str]:
        """
        Ponto de entrada principal para gerar todas as abas do relatório.
        Recupera dados do banco e chama os métodos de criação de planilhas.
        """
        logger.info("Iniciando geração do relatório avançado de compliance...")
        try:
            # Coleta os dados (exemplo: últimos 30 dias, ou todos os relevantes não reportados)
            # Você pode adicionar filtros aqui conforme a necessidade
            trinta_dias_atras = timezone.now() - timedelta(days=30)
            documentos = Documento.objects.filter(data_coleta__gte=trinta_dias_atras).prefetch_related('normas_relacionadas').order_by('-data_publicacao')
            # Para normas, pegar todas as que foram relacionadas aos documentos do período ou todas as ativas
            normas_ids = set()
            for doc in documentos:
                for norma in doc.normas_relacionadas.all():
                    normas_ids.add(norma.id)
            normas = NormaVigente.objects.filter(id__in=list(normas_ids)).order_by('tipo', '-ano', 'numero')

            if not documentos.exists():
                logger.warning("Nenhum documento encontrado para o período. O relatório pode ficar vazio.")
                # Mesmo assim, podemos gerar um relatório vazio com cabeçalhos
            
            # Gerar as abas
            self._criar_resumo_executivo(documentos, normas)
            self._criar_planilha_documentos_avancada(documentos) # Planilha de Documentos aprimorada
            #self._criar_planilha_normas_avancada(normas)         # Planilha de Normas aprimorada
            # self._criar_analise_compliance(normas) # Revise este método
            # self._criar_tendencias_temporais(documentos) # Revise este método
            # self._criar_analise_ia(documentos, normas) # Revise ou remova se a de Documentos for suficiente
            self._criar_dashboard_visual(documentos, normas)


            # Salvar o relatório
            caminho_relativo_arquivo = self._salvar_relatorio()

            if caminho_relativo_arquivo:
                # Registrar no modelo RelatorioGerado
                RelatorioGerado.objects.create(
                    tipo='CONTABIL', # Ou um tipo mais específico como 'COMPLIANCE_AVANCADO'
                    formato='XLSX',
                    caminho_arquivo=caminho_relativo_arquivo,
                    # parametros = { ... } # Se houver parâmetros
                    # gerado_por = ... # Se tiver o usuário
                )
                logger.info("Relatório avançado gerado e registrado com sucesso.")
                return caminho_relativo_arquivo # Retorna o caminho para a view
            else:
                logger.error("Falha ao salvar o relatório gerado.")
                return None

        except Exception as e:
            logger.error(f"Erro GERAL na geração do relatório completo: {e}", exc_info=True)
            return None


# Função de fachada para ser chamada de views.py ou tasks.py
# Mantendo a compatibilidade com o nome que você usava antes.
def gerar_relatorio_contabil_avancado() -> Optional[str]:
    """Função principal de fachada para gerar o relatório avançado de compliance."""
    try:
        gerador = RelatorioAvancado()
        caminho_arquivo = gerador.gerar_relatorio_completo()
        return caminho_arquivo
    except Exception as e:
        logger.error(f"Erro ao chamar RelatorioAvancado().gerar_relatorio_completo(): {e}", exc_info=True)
        return None