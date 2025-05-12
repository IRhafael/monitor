# relatorio.py
import openpyxl
from datetime import datetime
from django.conf import settings
import os

class RelatorioGenerator:
    @staticmethod
    def gerar_relatorio_contabil():
        try:
            logger.info("Iniciando geração de relatório contábil")
            documentos = Documento.objects.filter(relevante_contabil=True).order_by('-data_publicacao')
            
            if not documentos.exists():
                logger.warning("Nenhum documento contábil relevante encontrado")
                return None
                
            # Restante do código de geração do relatório...
            logger.info(f"Relatório contábil gerado com {documentos.count()} documentos")
            return caminho_completo
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório contábil: {str(e)}")
            return None

    @staticmethod
    def gerar_relatorio_mudancas():
        """Gera relatório Excel com mudanças na legislação"""
        integrador = IntegradorSEFAZ()
        mudancas = integrador.comparar_mudancas()
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Mudanças Legislativas"
        
        # Nova aba para novas normas
        ws.append(["Novas Normas"])
        for norma in mudancas['novas_normas']:
            ws.append([norma])
        
        # Nova aba para normas revogadas
        ws_revogadas = wb.create_sheet("Normas Revogadas")
        ws_revogadas.append(["Normas Revogadas"])
        for norma in mudancas['normas_revogadas']:
            ws_revogadas.append([norma])
        
        # Salvar arquivo
        relatorios_dir = os.path.join(settings.MEDIA_ROOT, 'relatorios')
        os.makedirs(relatorios_dir, exist_ok=True)
        
        nome_arquivo = f"relatorio_mudancas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        caminho_completo = os.path.join(relatorios_dir, nome_arquivo)
        
        wb.save(caminho_completo)
        return caminho_completo