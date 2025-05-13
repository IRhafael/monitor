import os
from datetime import datetime
from django.conf import settings
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

class RelatorioGenerator:
    @staticmethod
    def gerar_relatorio_contabil():
        try:
            # Configura caminhos
            relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
            os.makedirs(relatorios_dir, exist_ok=True)
            
            # Cria workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Documentos Contábeis"
            
            # Cabeçalho
            cabecalho = ["ID", "Título", "Data Publicação", "Assunto", "Resumo", "Normas Relacionadas"]
            ws.append(cabecalho)
            
            # Formata cabeçalho
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
            
            # Preenche dados
            from monitor.models import Documento
            documentos = Documento.objects.filter(relevante_contabil=True).select_related().prefetch_related('normas_relacionadas')
            
            for doc in documentos:
                # Extrai informações das normas
                normas = ", ".join([f"{n.tipo} {n.numero}" for n in doc.normas_relacionadas.all()])
                
                # Adiciona linha
                ws.append([
                    doc.id,
                    doc.titulo,
                    doc.data_publicacao.strftime("%d/%m/%Y"),
                    doc.assunto or "Não especificado",
                    doc.resumo or "Sem resumo",
                    normas or "Nenhuma norma relacionada"
                ])
            
            # Ajusta largura das colunas
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                ws.column_dimensions[col].width = 20
            
            # Salva arquivo
            nome_arquivo = f"relatorio_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            caminho_completo = os.path.join(relatorios_dir, nome_arquivo)
            wb.save(caminho_completo)
            
            return f"/media/relatorios/{nome_arquivo}"
            
        except Exception as e:
            print(f"Erro ao gerar relatório: {e}")
            return None