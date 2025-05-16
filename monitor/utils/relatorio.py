import os
from datetime import datetime
import logging
from django.conf import settings
from django.db.models import Count, Q, F, Value, CharField
from django.db.models.functions import Concat
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from monitor.models import Documento, NormaVigente

logger = logging.getLogger(__name__)

class RelatorioGenerator:
    @staticmethod
    def gerar_relatorio_contabil():
        try:
            # Configura caminhos
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
            os.makedirs(relatorios_dir, exist_ok=True)
            
            # Cria workbook
            wb = Workbook()
            ws_docs = wb.active
            ws_docs.title = "Documentos Contábeis"
            
            # Cabeçalho com estilo melhorado
            cabecalho_docs = ["ID", "Título", "Data Publicação", "Assunto", "Resumo", "Normas Relacionadas"]
            RelatorioGenerator._adicionar_cabecalho(ws_docs, cabecalho_docs)
            
            # Preenche dados - com ordenação e otimização de consulta
            from monitor.models import Documento
            documentos = Documento.objects.filter(
                relevante_contabil=True, 
                processado=True
            ).select_related().prefetch_related(
                'normas_relacionadas'
            ).order_by('-data_publicacao')
            
            RelatorioGenerator._preencher_planilha_documentos(ws_docs, documentos)
            
            # Segunda aba: Resumo de Normas
            ws_normas = wb.create_sheet(title="Resumo Normas")
            cabecalho_normas = ["Tipo", "Número", "Situação", "Frequência", "Documentos Relacionados"]
            RelatorioGenerator._adicionar_cabecalho(ws_normas, cabecalho_normas)
            
            # Dados de normas com contagem agrupada e otimização
            normas = NormaVigente.objects.filter(
                documentos__relevante_contabil=True  # Use 'documentos' em vez de 'documento'
            ).annotate(
                qtd_docs=Count('documentos')
            ).order_by('-qtd_docs', 'tipo', 'numero')
            
            RelatorioGenerator._preencher_planilha_normas(ws_normas, normas)
            
            # Terceira aba: Estatísticas
            ws_stats = wb.create_sheet(title="Estatísticas")
            RelatorioGenerator._gerar_estatisticas(ws_stats)
            
            # Ajusta largura das colunas em todas as planilhas
            for ws in [ws_docs, ws_normas, ws_stats]:
                RelatorioGenerator._ajustar_colunas(ws)
            
            # Salva arquivo
            nome_arquivo = f"relatorio_contabil_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            caminho_completo = os.path.join(relatorios_dir, nome_arquivo)
            wb.save(caminho_completo)
            
            logger.info(f"Relatório gerado com sucesso: {nome_arquivo}")
            return f"/media/relatorios/{nome_arquivo}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _adicionar_cabecalho(worksheet, cabecalho):
        """Adiciona cabeçalho com estilo melhorado"""
        worksheet.append(cabecalho)
        
        # Estilos do cabeçalho
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=12)
        header_border = Border(
            bottom=Side(border_style="medium", color="FFFFFF")
        )
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        # Aplica estilos
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.border = header_border
            cell.alignment = header_alignment
    
    @staticmethod
    def _preencher_planilha_documentos(worksheet, documentos):
        """Preenche planilha de documentos contábeis com formatação"""
        # Estilos para alternância de linhas
        zebra_fill = PatternFill(start_color="EEF1F5", end_color="EEF1F5", fill_type="solid")
        row_num = 2  # Começa após o cabeçalho
        
        for doc in documentos:
            # Extrai informações das normas
            normas = ", ".join([f"{n.tipo} {n.numero}" for n in doc.normas_relacionadas.all()]) or "Nenhuma norma"
            
            # Limita tamanho do resumo para não sobrecarregar a planilha
            resumo = doc.resumo[:500] + "..." if doc.resumo and len(doc.resumo) > 500 else (doc.resumo or "Sem resumo")
            
            # Adiciona linha
            worksheet.append([
                doc.id,
                doc.titulo,
                doc.data_publicacao.strftime("%d/%m/%Y"),
                doc.assunto or "Não especificado",
                resumo,
                normas
            ])
            
            # Aplica estilo zebrado
            if row_num % 2 == 0:
                for cell in worksheet[row_num]:
                    cell.fill = zebra_fill
            
            # Alinhamento para todas as células
            for cell in worksheet[row_num]:
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            
            # Alinha ID à direita
            worksheet.cell(row=row_num, column=1).alignment = Alignment(horizontal='right')
            
            row_num += 1
    
    @staticmethod
    def _preencher_planilha_normas(worksheet, normas):
        """Preenche planilha de resumo de normas"""
        zebra_fill = PatternFill(start_color="EEF1F5", end_color="EEF1F5", fill_type="solid")
        row_num = 2  # Começa após o cabeçalho
        
        for norma in normas:
            # Obtém documentos relacionados
            docs_relacionados = ", ".join([
                f"{doc.id} ({doc.data_publicacao.strftime('%d/%m/%Y')})" 
                for doc in norma.documento_set.all()[:5]  # Limita a 5 documentos para não sobrecarregar
            ])
            
            if norma.documento_set.count() > 5:
                docs_relacionados += f" e mais {norma.documento_set.count() - 5} documento(s)"
            
            worksheet.append([
                norma.tipo,
                norma.numero,
                norma.situacao,
                norma.qtd_docs,  # Anotação do Count
                docs_relacionados
            ])
            
            # Aplica estilo zebrado
            if row_num % 2 == 0:
                for cell in worksheet[row_num]:
                    cell.fill = zebra_fill
            
            # Alinhamento
            for cell in worksheet[row_num]:
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            
            # Frequência alinhada à direita
            worksheet.cell(row=row_num, column=4).alignment = Alignment(horizontal='right')
            
            row_num += 1
    
    @staticmethod
    def _gerar_estatisticas(worksheet):
        """Gera estatísticas na terceira aba"""
        # Estilos
        title_font = Font(size=14, bold=True)
        subtitle_font = Font(size=12, bold=True)
        header_fill = PatternFill(start_color="C5D9F1", end_color="C5D9F1", fill_type="solid")
        
        # Título
        worksheet.append(["Estatísticas do Sistema de Monitoramento"])
        worksheet['A1'].font = title_font
        worksheet.merge_cells('A1:E1')
        worksheet['A1'].alignment = Alignment(horizontal='center')
        
        # Espaço
        worksheet.append([])
        
        # Total de documentos
        total_docs = Documento.objects.count()
        docs_contabeis = Documento.objects.filter(relevante_contabil=True).count()
        docs_processados = Documento.objects.filter(processado=True).count()
        
        worksheet.append(["Estatísticas de Documentos", "", "", "", ""])
        worksheet['A3'].font = subtitle_font
        worksheet.merge_cells('A3:E3')
        
        # Cabeçalhos das estatísticas
        worksheet.append(["Métrica", "Valor", "Percentual", "", ""])
        for cell in worksheet[4]:
            if cell.column_letter in ['A', 'B', 'C']:
                cell.fill = header_fill
                cell.font = Font(bold=True)
        
        # Dados de estatísticas
        stats = [
            ["Total de documentos", total_docs, "100%"],
            ["Documentos contábeis", docs_contabeis, f"{docs_contabeis/total_docs*100:.1f}%" if total_docs else "0%"],
            ["Documentos processados", docs_processados, f"{docs_processados/total_docs*100:.1f}%" if total_docs else "0%"],
            ["Não processados", total_docs - docs_processados, f"{(total_docs-docs_processados)/total_docs*100:.1f}%" if total_docs else "0%"]
        ]
        
        row_num = 5
        for stat in stats:
            worksheet.append(stat + ["", ""])
            row_num += 1
        
        # Espaço
        worksheet.append([])
        row_num += 1
        
        # Estatísticas de normas
        worksheet.append(["Estatísticas de Normas", "", "", "", ""])
        worksheet[f'A{row_num}'].font = subtitle_font
        worksheet.merge_cells(f'A{row_num}:E{row_num}')
        row_num += 1
        
        # Cabeçalhos
        worksheet.append(["Tipo de Norma", "Quantidade", "Normas Vigentes", "Percentual Vigentes", ""])
        for cell in worksheet[row_num]:
            if cell.column_letter in ['A', 'B', 'C', 'D']:
                cell.fill = header_fill
                cell.font = Font(bold=True)
        row_num += 1
        
        # Dados agrupados por tipo de norma
        from django.db.models import Count
        tipos_normas = NormaVigente.objects.values('tipo').annotate(
            total=Count('id'),
            vigentes=Count('id', filter=Q(situacao='VIGENTE'))
        ).order_by('-total')
        
        for tipo in tipos_normas:
            percentual = f"{tipo['vigentes']/tipo['total']*100:.1f}%" if tipo['total'] else "0%"
            worksheet.append([
                tipo['tipo'],
                tipo['total'],
                tipo['vigentes'],
                percentual,
                ""
            ])
            row_num += 1
            
        # Nova seção: Evolução Mensal
        from django.db.models.functions import TruncMonth
        evolucao = (
            Documento.objects
            .annotate(mes=TruncMonth('data_publicacao'))
            .values('mes')
            .annotate(total=Count('id'))
            .order_by('mes')
        )
        
        worksheet.append(["Evolução Mensal de Documentos"])
        for item in evolucao:
            worksheet.append([item['mes'].strftime("%Y-%m"), item['total']])
    
    @staticmethod
    def _ajustar_colunas(worksheet):
        """Ajusta a largura das colunas baseado no conteúdo"""
        dimensoes = {}
        for linha in worksheet.rows:
            for i, cell in enumerate(linha):
                if cell.value:
                    # Estima o tamanho baseado no conteúdo
                    tamanho_conteudo = len(str(cell.value)) + 4
                    # Ajusta para largura máxima
                    tamanho_conteudo = min(tamanho_conteudo, 60)
                    
                    coluna = cell.column_letter
                    dimensoes[coluna] = max(
                        dimensoes.get(coluna, 10),
                        tamanho_conteudo
                    )
        
        for col, value in dimensoes.items():
            worksheet.column_dimensions[col].width = value



    @staticmethod
    def gerar_relatorio_mudancas(dias_retroativos=30):
        """Gera um relatório de mudanças nas normas"""
        try:
            from monitor.utils.sefaz_integracao import IntegradorSEFAZ
            integrador = IntegradorSEFAZ()
            mudancas = integrador.comparar_mudancas(dias_retroativos)
            
            # Cria workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Mudanças nas Normas"
            
            # Estilos
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            zebra_fill = PatternFill(start_color="EEF1F5", end_color="EEF1F5", fill_type="solid")
            
            # Seção de Novas Normas
            ws.append(["Novas Normas Identificadas"])
            ws['A1'].font = Font(size=14, bold=True)
            ws.merge_cells('A1:B1')
            
            ws.append(["Norma", "Detalhes"])
            for cell in ws[2]:
                cell.fill = header_fill
                cell.font = header_font
            
            row_num = 3
            for norma in mudancas['novas_normas']:
                ws.append([norma, "Nova norma identificada no Diário Oficial"])
                if row_num % 2 == 0:
                    for cell in ws[row_num]:
                        cell.fill = zebra_fill
                row_num += 1
            
            # Seção de Normas Revogadas
            ws.append([])
            ws.append(["Normas Potencialmente Revogadas"])
            ws[f'A{row_num}'].font = Font(size=14, bold=True)
            ws.merge_cells(f'A{row_num}:B{row_num}')
            row_num += 1
            
            ws.append(["Norma", "Última Menção"])
            for cell in ws[row_num]:
                cell.fill = header_fill
                cell.font = header_font
            row_num += 1
            
            for item in mudancas['normas_revogadas']:
                ws.append([item['norma'], item['ultima_menção']])
                if row_num % 2 == 0:
                    for cell in ws[row_num]:
                        cell.fill = zebra_fill
                row_num += 1
            
            # Ajusta colunas
            ws.column_dimensions['A'].width = 40
            ws.column_dimensions['B'].width = 40
            
            # Salva arquivo
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
            os.makedirs(relatorios_dir, exist_ok=True)
            
            nome_arquivo = f"relatorio_mudancas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            caminho_completo = os.path.join(relatorios_dir, nome_arquivo)
            wb.save(caminho_completo)
            
            logger.info(f"Relatório de mudanças gerado: {nome_arquivo}")
            return f"/media/relatorios/{nome_arquivo}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório de mudanças: {e}", exc_info=True)
            return None