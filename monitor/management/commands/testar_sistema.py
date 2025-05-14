import os
from datetime import datetime
import time
from django.core.management.base import BaseCommand
from monitor.models import Documento
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.utils.relatorio import RelatorioGenerator
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Testa todas as funcionalidades do sistema de monitoramento contábil'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando teste completo do sistema...'))

        # 1. Localizar documentos não processados
        docs_nao_processados = Documento.objects.filter(processado=False)
        self.stdout.write(f'Encontrados {docs_nao_processados.count()} documentos não processados')

        if docs_nao_processados.count() == 0:
            self.stdout.write(self.style.WARNING('Nenhum documento não processado encontrado. Criando um para teste...'))
            self.criar_documento_teste()
            docs_nao_processados = Documento.objects.filter(processado=False)

        # 2. Processar documentos com PDFProcessor
        self.stdout.write('\n=== TESTANDO PROCESSAMENTO DE PDFs ===')
        pdf_processor = PDFProcessor()
        
        for doc in docs_nao_processados[:1]:  # Limita a 1 para teste
            try:
                self.stdout.write(f'Processando documento ID {doc.id} - {doc.titulo}')
                
                if pdf_processor.processar_documento(doc):
                    doc.refresh_from_db()
                    self.stdout.write(self.style.SUCCESS('Documento processado com sucesso!'))
                    self.stdout.write(f'- Resumo: {doc.resumo[:100]}...')
                    self.stdout.write(f'- Relevante: {doc.relevante_contabil}')
                    self.stdout.write(f'- Normas relacionadas: {doc.normas_relacionadas.count()}')
                else:
                    self.stdout.write(self.style.WARNING('Documento não relevante'))
                    # Não tenta acessar doc.id após delete
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Erro ao processar: {str(e)}'))

        # 3. Testar integração com SEFAZ (versão otimizada)
        self.stdout.write('\n=== TESTANDO INTEGRAÇÃO COM SEFAZ (OTIMIZADA) ===')
        integrador = IntegradorSEFAZ()
        
        # Pega um documento com normas relacionadas
        doc_com_normas = Documento.objects.filter(
            normas_relacionadas__isnull=False
        ).first()
        
        if doc_com_normas:
            start_time = time.time()
            normas = integrador.verificar_vigencia_automatica(doc_com_normas.id)
            elapsed_time = time.time() - start_time
            
            self.stdout.write(f"Verificadas {len(normas)} normas em {elapsed_time:.2f}s")
            for norma in normas[:5]:  # Mostra apenas as primeiras 5
                self.stdout.write(f"- {norma.tipo} {norma.numero}: {norma.situacao}")
        else:
            self.stdout.write(self.style.WARNING('Nenhum documento com normas encontrado'))

        # 4. Testar comparação de mudanças
        self.stdout.write('\n=== TESTANDO COMPARAÇÃO DE MUDANÇAS ===')
        mudancas = integrador.comparar_mudancas(dias_retroativos=7)
        self.stdout.write(f'Novas normas: {len(mudancas["novas_normas"])}')
        self.stdout.write(f'Normas revogadas: {len(mudancas["normas_revogadas"])}')

        # 5. Testar geração de relatórios
        self.stdout.write('\n=== TESTANDO GERAÇÃO DE RELATÓRIOS ===')
        try:
            caminho_relatorio = RelatorioGenerator.gerar_relatorio_contabil()
            self.stdout.write(self.style.SUCCESS(f'Relatório contábil gerado: {caminho_relatorio}'))

            caminho_mudancas = RelatorioGenerator.gerar_relatorio_mudancas()
            self.stdout.write(self.style.SUCCESS(f'Relatório de mudanças gerado: {caminho_mudancas}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erro ao gerar relatórios: {str(e)}'))

        self.stdout.write(self.style.SUCCESS('\nTeste completo concluído!'))

    def criar_documento_teste(self):
        """Cria um documento de teste com conteúdo contábil fictício"""
        from django.core.files.base import ContentFile
        from faker import Faker
        import tempfile

        fake = Faker('pt_BR')

        conteudo = """
        DECRETO Nº 1234/2025
        Dispõe sobre alterações na legislação do ICMS no estado do Piauí

        Art. 1º Fica alterada a alíquota do ICMS para o setor de serviços conforme Lei 5678/2020.

        Art. 2º As empresas do Simples Nacional deverão apresentar a DAS até o dia 20 de cada mês.

        Referências:
        - Lei 5678/2020
        - Portaria SEFAZ 987/2024
        - Instrução Normativa RFB 123/2023
        """

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(conteudo.encode())
            tmp_path = tmp.name

        doc = Documento.objects.create(
            titulo="DOCUMENTO DE TESTE - Alterações ICMS 2025",
            data_publicacao=datetime.now().date(),
            url_original="http://exemplo.com/teste.pdf",
            data_coleta=datetime.now()
        )

        with open(tmp_path, 'rb') as f:
            doc.arquivo_pdf.save('documento_teste.pdf', ContentFile(f.read()))

        os.unlink(tmp_path)
        return doc

    def test_spacy_processing(self):
        processor = PDFProcessor()
        test_text = "A Lei 1234/2025 altera o Decreto 5678 sobre ICMS"
        
        relevante, detalhes = processor.analisar_relevancia(test_text)
        self.assertTrue(relevante)
        self.assertIn(("LEI", "1234/2025"), detalhes['normas'])
        self.assertIn(("DECRETO", "5678"), detalhes['normas'])
        self.assertIn("icms", detalhes['termos'])