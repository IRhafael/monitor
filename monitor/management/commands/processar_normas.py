from django.core.management.base import BaseCommand
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.models import Documento, NormaVigente
import os
import datetime
import re
from django.core.files import File
import traceback
from openpyxl import Workbook

class Command(BaseCommand):
    help = 'Processa PDF e verifica vigência de normas usando IntegradorSEFAZ'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pdf',
            type=str,
            default=r'C:\Users\RRCONTAS\Documents\GitHub\monitor\media\pdfs\DOEPI_92_2025.pdf'
        )
        parser.add_argument(
            '--debug',
            action='store_true',
            help='Ativa modo debug detalhado'
        )

    def handle(self, *args, **options):
        self.debug = options['debug']
        pdf_path = options['pdf']
        
        processor = NormaProcessor(self.stdout, self.style, debug=self.debug)
        processor.processar_fluxo_completo(pdf_path)

class NormaProcessor:
    def __init__(self, stdout=None, style=None, debug=False):
        self.stdout = stdout
        self.style = style
        self.debug = debug
        self.pdf_processor = PDFProcessor()
        self.integrador = IntegradorSEFAZ()

    def processar_fluxo_completo(self, pdf_path):
        try:
            self._print(f"\n📂 Processando PDF: {os.path.basename(pdf_path)}", self.style.SUCCESS)
            
            # 1. Processar PDF e extrair normas
            normas = self._processar_pdf(pdf_path)
            if not normas:
                self._print("❌ Nenhuma norma encontrada", self.style.ERROR)
                return False

            # 2. Verificar vigências usando o método disponível
            resultados = self._verificar_vigencias(normas)
            
            # 3. Gerar relatório
            relatorio_path = os.path.join(
                os.path.dirname(pdf_path),
                f"relatorio_{os.path.splitext(os.path.basename(pdf_path))[0]}.xlsx"
            )
            self._gerar_relatorio(resultados, relatorio_path)
            
            return True
            
        except Exception as e:
            self._print(f"❌ Erro no fluxo: {str(e)}", self.style.ERROR)
            if self.debug:
                traceback.print_exc()
            return False

    def _processar_pdf(self, pdf_path):
        """Processa o PDF e retorna as normas encontradas"""
        try:
            with open(pdf_path, 'rb') as f:
                doc = Documento(
                    titulo=os.path.basename(pdf_path),
                    data_publicacao=datetime.date.today()
                )
                doc.arquivo_pdf.save(os.path.basename(pdf_path), File(f))
                doc.save()

            if not self.pdf_processor.processar_documento(doc):
                return None

            doc.refresh_from_db()
            normas = list(doc.normas_relacionadas.all())
            
            if self.debug:
                self._print("\n🔍 Normas extraídas:", self.style.SUCCESS)
                for norma in normas:
                    self._print(f"- {norma.tipo} {norma.numero}", self.style.SUCCESS)
            
            return normas
            
        except Exception as e:
            self._print(f"❌ Erro ao processar PDF: {str(e)}", self.style.ERROR)
            if self.debug:
                traceback.print_exc()
            return None

    def _verificar_vigencias(self, normas):
        """Verifica vigência usando os métodos disponíveis no IntegradorSEFAZ"""
        resultados = {}
        
        self._print("\n🔎 Verificando vigência na SEFAZ...", self.style.SUCCESS)
        
        for norma in normas:
            try:
                # Usa o método mais apropriado disponível
                if hasattr(self.integrador, 'buscar_norma_especifica'):
                    resultado = self.integrador.buscar_norma_especifica(norma.tipo, norma.numero)
                    vigente = resultado.get('vigente', False)
                elif hasattr(self.integrador, 'verificar_vigencia_norma'):
                    vigente = self.integrador.verificar_vigencia_norma(norma.tipo, norma.numero)
                else:
                    vigente = False
                
                resultados[f"{norma.tipo} {norma.numero}"] = vigente
                
                status = "VIGENTE" if vigente else "NÃO VIGENTE"
                self._print(f"- {norma.tipo} {norma.numero}: {status}", self.style.SUCCESS)
                    
            except Exception as e:
                self._print(f"⚠️ Erro ao verificar {norma.tipo} {norma.numero}: {str(e)}", self.style.WARNING)
                resultados[f"{norma.tipo} {norma.numero}"] = False
                
        return resultados

    def _gerar_relatorio(self, resultados, output_path):
        """Gera relatório Excel com os resultados"""
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Normas"
            
            # Cabeçalhos
            ws.append(['Norma', 'Vigente', 'Detalhes'])
            
            # Dados
            for norma, vigente in resultados.items():
                ws.append([
                    norma,
                    'Sim' if vigente else 'Não',
                    'Verificado em ' + datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                ])
            
            wb.save(output_path)
            self._print(f"\n📄 Relatório gerado em: {output_path}", self.style.SUCCESS)
            return True
                
        except Exception as e:
            self._print(f"❌ Erro ao gerar relatório: {str(e)}", self.style.ERROR)
            if self.debug:
                traceback.print_exc()
            return False

    def _print(self, message, style=None):
        """Helper para output formatado"""
        if self.stdout and style:
            self.stdout.write(style(message))
        else:
            print(message)