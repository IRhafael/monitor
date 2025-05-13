import os
from datetime import datetime
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

        for doc in docs_nao_processados[:5]:  # Limita a 5 para teste
            self.stdout.write(f'Processando documento ID {doc.id} - {doc.titulo}')

            try:
                resultado = pdf_processor.processar_documento(doc)
                if resultado:
                    doc.refresh_from_db()
                    self.stdout.write(self.style.SUCCESS(f'Documento processado com sucesso!'))
                    self.stdout.write(f'- Resumo: {doc.resumo[:100]}...')
                    self.stdout.write(f'- Relevante: {doc.relevante_contabil}')
                    self.stdout.write(f'- Normas relacionadas: {doc.normas_relacionadas.count()}')
                else:
                    self.stdout.write(self.style.WARNING('Documento não foi considerado relevante'))

                    # Deleta o documento que não é relevante contábil
                    doc.delete()
                    self.stdout.write(self.style.NOTICE(f'Documento ID {doc.id} deletado por não ser relevante contábil.'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Erro ao processar: {str(e)}'))

        # 3. Testar integração com SEFAZ
        self.stdout.write('\n=== TESTANDO INTEGRAÇÃO COM SEFAZ ===')
        integrador = IntegradorSEFAZ()

        doc_com_normas = Documento.objects.filter(
            processado=True,
            relevante_contabil=True
        ).exclude(normas_relacionadas=None).first()

        if doc_com_normas:
            self.stdout.write(f'Verificando normas para documento ID {doc_com_normas.id}')
            normas = integrador.verificar_vigencia_normas(doc_com_normas.id)
            self.stdout.write(f'Encontradas {len(normas)} normas:')
            for norma in normas:
                self.stdout.write(f'- {norma.tipo} {norma.numero} ({norma.situacao})')
        else:
            self.stdout.write(self.style.WARNING('Nenhum documento com normas encontrado para teste'))

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
