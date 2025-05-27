import os
from datetime import datetime
import logging
from django.conf import settings
from django.db.models import Count, Q, Max
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from monitor.models import Documento, NormaVigente
from django.db.models import Case, When, Value, CharField


logger = logging.getLogger(__name__)

class RelatorioGenerator:
    @staticmethod
    def gerar_relatorio_contabil():
        """Gera relatório contábil completo com abas para documentos, normas e estatísticas"""
        try:
            # Configura caminhos e cria diretório se necessário
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
            os.makedirs(relatorios_dir, exist_ok=True)
            
            # Cria workbook e planilhas
            wb = Workbook()
            ws_docs = wb.active
            ws_docs.title = "Documentos Contábeis"
            
            # Planilha de Documentos Contábeis
            cabecalho_docs = [
                "ID", "Título", "Data Publicação", "Assunto", 
                "Resumo", "Normas Relacionadas", "Fonte Verificação"
            ]
            RelatorioGenerator._adicionar_cabecalho(ws_docs, cabecalho_docs)
            
            # Consulta otimizada para documentos
            documentos = Documento.objects.filter(
                relevante_contabil=True, 
                processado=True
            ).select_related().prefetch_related(
                'normas_relacionadas'
            ).order_by('-data_publicacao')
            
            RelatorioGenerator._preencher_planilha_documentos(ws_docs, documentos)
            
            # Planilha de Resumo de Normas
            ws_normas = wb.create_sheet(title="Resumo Normas")
            cabecalho_normas = [
                "Tipo", "Número", "Situação", "Frequência", 
                "Documentos Relacionados", "Fonte", "Última Verificação", "Resumo IA"
            ]
            RelatorioGenerator._adicionar_cabecalho(ws_normas, cabecalho_normas)
            
            # Consulta otimizada para normas
            normas = NormaVigente.objects.annotate(
                qtd_docs=Count('documentos')
            ).order_by('-qtd_docs', 'tipo', 'numero')
            
            RelatorioGenerator._preencher_planilha_normas(ws_normas, normas)
            
            # Planilha de Normas Não Encontradas
            ws_nao_encontradas = wb.create_sheet(title="Normas Problemáticas")
            cabecalho_problemas = [
                "Tipo", "Número", "Situação", "Última Menção", 
                "Documentos", "Fonte Alternativa", "Resumo IA"
            ]
            RelatorioGenerator._adicionar_cabecalho(ws_nao_encontradas, cabecalho_problemas)
            
            normas_problema = NormaVigente.objects.filter(
                Q(situacao='NÃO ENCONTRADA') | Q(fonte_confirmacao='BING')
            ).annotate(
                qtd_docs=Count('documentos')
            ).order_by('-data_verificacao')
            
            RelatorioGenerator._preencher_planilha_problemas(ws_nao_encontradas, normas_problema)
            
            # Planilha de Estatísticas
            ws_stats = wb.create_sheet(title="Estatísticas")
            RelatorioGenerator._gerar_estatisticas(ws_stats)
            
            # Ajusta formatação de todas as planilhas
            for ws in wb.worksheets:
                RelatorioGenerator._ajustar_colunas(ws)
                RelatorioGenerator._aplicar_auto_filtro(ws)
            
            # Salva arquivo com timestamp
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
        """Adiciona cabeçalho estilizado à planilha"""
        worksheet.append(cabecalho)
        
        # Estilos do cabeçalho
        header_style = {
            'fill': PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid"),
            'font': Font(color="FFFFFF", bold=True, size=12),
            'border': Border(bottom=Side(border_style="medium", color="FFFFFF")),
            'alignment': Alignment(horizontal='center', vertical='center', wrap_text=True)
        }
        
        for cell in worksheet[1]:
            for attr, value in header_style.items():
                setattr(cell, attr, value)

    @staticmethod
    def _preencher_planilha_documentos(worksheet, documentos):
        """Preenche a planilha de documentos com formatação condicional"""
        zebra_style = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        
        for row_num, doc in enumerate(documentos, start=2):
            normas = ", ".join([f"{n.tipo} {n.numero}" for n in doc.normas_relacionadas.all()[:3]])
            if doc.normas_relacionadas.count() > 3:
                normas += f" (+{doc.normas_relacionadas.count() - 3} mais)"
                
            fonte = ", ".join(set([n.fonte_confirmacao or "N/A" for n in doc.normas_relacionadas.all()]))
            
            worksheet.append([
                doc.id,
                doc.titulo,
                doc.data_publicacao.strftime("%d/%m/%Y"),
                doc.assunto or "Não especificado",
                doc.resumo[:300] + "..." if doc.resumo and len(doc.resumo) > 300 else doc.resumo,
                normas,
                fonte
            ])
            
            # Formatação zebrada
            if row_num % 2 == 0:
                for cell in worksheet[row_num]:
                    cell.fill = zebra_style
            
            # Alinhamentos específicos
            worksheet.cell(row=row_num, column=1).alignment = Alignment(horizontal='right')  # ID
            worksheet.cell(row=row_num, column=3).alignment = Alignment(horizontal='center')  # Data

    @staticmethod
    def _preencher_planilha_normas(worksheet, normas):
        """Preenche a planilha de normas com dados completos"""
        zebra_style = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        alerta_style = PatternFill(start_color="FFEEEE", end_color="FFEEEE", fill_type="solid")
        
        for row_num, norma in enumerate(normas, start=2):
            docs_relacionados = ", ".join([
                f"{doc.id} ({doc.data_publicacao.strftime('%d/%m/%Y')})" 
                for doc in norma.documentos.all()[:2]
            ])
            if norma.documentos.count() > 2:
                docs_relacionados += f" e +{norma.documentos.count() - 2}"
                
            worksheet.append([
                norma.tipo,
                norma.numero,
                norma.situacao or "NÃO VERIFICADO",
                norma.qtd_docs,
                docs_relacionados,
                norma.fonte_confirmacao or "N/A",
                norma.data_verificacao.strftime("%d/%m/%Y %H:%M") if norma.data_verificacao else "N/A",
                RelatorioGenerator._formatar_resumo_ia(norma.resumo_ia)
            ])
            
            # Formatação condicional
            if norma.situacao == 'REVOGADA':
                for cell in worksheet[row_num]:
                    cell.fill = alerta_style
            elif row_num % 2 == 0:
                for cell in worksheet[row_num]:
                    cell.fill = zebra_style

    @staticmethod
    def _preencher_planilha_problemas(worksheet, normas):
        """Preenche a planilha de normas problemáticas com destaque"""
        alerta_style = PatternFill(start_color="FFEEEE", end_color="FFEEEE", fill_type="solid")
        
        for row_num, norma in enumerate(normas, start=2):
            worksheet.append([
                norma.tipo,
                norma.numero,
                norma.situacao or "NÃO VERIFICADO",
                norma.data_ultima_mencao.strftime("%d/%m/%Y") if norma.data_ultima_mencao else "N/A",
                norma.qtd_docs,
                "Bing" if norma.fonte_confirmacao == 'BING' else "N/A",
                RelatorioGenerator._formatar_resumo_ia(norma.resumo_ia)
            ])
            
            # Destaque para todas as linhas
            for cell in worksheet[row_num]:
                cell.fill = alerta_style

    @staticmethod
    def _gerar_estatisticas(worksheet):
        """Gera a planilha de estatísticas com dados consolidados"""
        # Estilos
        title_style = {'font': Font(size=14, bold=True), 'alignment': Alignment(horizontal='center')}
        header_style = {
            'fill': PatternFill(start_color="5B9BD5", end_color="5B9BD5", fill_type="solid"),
            'font': Font(color="FFFFFF", bold=True)
        }
        
        # Seção 1: Estatísticas de Documentos
        worksheet.merge_cells('A1:E1')
        worksheet['A1'] = "ESTATÍSTICAS DE DOCUMENTOS"
        for attr, value in title_style.items():
            setattr(worksheet['A1'], attr, value)
        
        # Cabeçalhos
        worksheet.append(["Métrica", "Total", "Contábil", "Processados", "Não Processados"])
        for cell in worksheet[2]:
            for attr, value in header_style.items():
                setattr(cell, attr, value)
        
        # Dados
        total_docs = Documento.objects.count()
        contabeis = Documento.objects.filter(relevante_contabil=True).count()
        processados = Documento.objects.filter(processado=True).count()
        
        worksheet.append([
            "Quantidade",
            total_docs,
            contabeis,
            processados,
            total_docs - processados
        ])
        
        # Seção 2: Estatísticas de Normas
        worksheet.merge_cells('A5:E5')
        worksheet['A5'] = "ESTATÍSTICAS DE NORMAS"
        for attr, value in title_style.items():
            setattr(worksheet['A5'], attr, value)
        
        # Cabeçalhos
        worksheet.append(["Tipo", "Total", "Vigentes", "Revogadas", "Não Verificadas"])
        for cell in worksheet[6]:
            for attr, value in header_style.items():
                setattr(cell, attr, value)
        
        # Dados agrupados por tipo
        tipos = NormaVigente.objects.values('tipo').annotate(
            total=Count('id'),
            vigentes=Count('id', filter=Q(situacao='VIGENTE')),
            revogadas=Count('id', filter=Q(situacao='REVOGADA'))
        )
        
        for tipo in tipos:
            worksheet.append([
                tipo['tipo'],
                tipo['total'],
                tipo['vigentes'],
                tipo['revogadas'],
                tipo['total'] - tipo['vigentes'] - tipo['revogadas']
            ])

    @staticmethod
    def _formatar_resumo_ia(resumo):
        """Formata o resumo da IA para exibição na planilha"""
        if not resumo:
            return ""
        
        resumo = resumo.replace('\n', ' ').strip()
        return (resumo[:150] + '...') if len(resumo) > 150 else resumo

    @staticmethod
    def _ajustar_colunas(worksheet):
        """Ajusta automaticamente a largura das colunas"""
        for col_cells in worksheet.columns:
            max_length = 0
            column_letter = None
            for cell in col_cells:
                if not hasattr(cell, "column_letter"):
                    continue  # ignora células mescladas
                column_letter = cell.column_letter
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass
            if column_letter:
                adjusted_width = (max_length + 2) * 1.1
                worksheet.column_dimensions[column_letter].width = min(adjusted_width, 50)


    @staticmethod
    def _aplicar_auto_filtro(worksheet):
        """Adiciona filtros automáticos ao cabeçalho"""
        if worksheet.max_row > 1:
            worksheet.auto_filter.ref = f"A1:{get_column_letter(worksheet.max_column)}{1}"

    @staticmethod
    def gerar_relatorio_mudancas(dias_retroativos=30):
        """Gera relatório específico de mudanças nas normas"""
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Mudanças Recentes"
            
            # Estilos
            title_style = {
                'font': Font(size=14, bold=True, color="1F4E78"),
                'alignment': Alignment(horizontal='center')
            }
            
            # Título principal
            ws.merge_cells('A1:D1')
            ws['A1'] = f"RELATÓRIO DE MUDANÇAS - ÚLTIMOS {dias_retroativos} DIAS"
            for attr, value in title_style.items():
                setattr(ws['A1'], attr, value)
            
            # Consulta de normas alteradas
            from django.utils import timezone
            from django.db.models import F
            data_corte = timezone.now() - timezone.timedelta(days=dias_retroativos)
            
            normas_alteradas = NormaVigente.objects.filter(
                data_verificacao__gte=data_corte
            ).annotate(
                mudanca=Case(
                    When(data_verificacao=F('data_ultima_mencao'), then=Value('NOVA')),
                    When(situacao='REVOGADA', then=Value('REVOGADA')),
                    default=Value('ATUALIZADA'),
                    output_field=CharField()
                )
            ).order_by('-data_verificacao')
            
            # Cabeçalhos
            cabecalhos = ["Norma", "Tipo Mudança", "Data Verificação", "Detalhes"]
            ws.append(cabecalhos)
            
            # Formata cabeçalhos
            for cell in ws[2]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
                cell.border = Border(bottom=Side(border_style="thin"))
            
            # Preenche dados
            for norma in normas_alteradas:
                ws.append([
                    f"{norma.tipo} {norma.numero}",
                    norma.mudanca,
                    norma.data_verificacao.strftime("%d/%m/%Y %H:%M"),
                    norma.resumo_ia[:100] + "..." if norma.resumo_ia else "Sem detalhes"
                ])
            
            # Ajustes finais
            RelatorioGenerator._ajustar_colunas(ws)
            RelatorioGenerator._aplicar_auto_filtro(ws)
            
            # Salva arquivo
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
            os.makedirs(relatorios_dir, exist_ok=True)
            
            nome_arquivo = f"mudancas_normas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            caminho_completo = os.path.join(relatorios_dir, nome_arquivo)
            wb.save(caminho_completo)
            
            logger.info(f"Relatório de mudanças gerado: {nome_arquivo}")
            return f"/media/relatorios/{nome_arquivo}"
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório de mudanças: {e}", exc_info=True)
            return None