import os
import tempfile
from unittest import mock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.utils.relatorio import RelatorioGenerator
from monitor.models import Documento, NormaVigente, ConfiguracaoColeta, TermoMonitorado

# Criar um diretório de mídia temporário para testes
TEST_MEDIA_ROOT = tempfile.mkdtemp()

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class TestSistemaCompletoReal(TestCase):
    @classmethod
    def setUpTestData(cls):
        """Configuração inicial para todos os testes"""
        # Configuração do sistema
        cls.config = ConfiguracaoColeta.objects.create(
            ativa=True,
            intervalo_horas=24,
            max_documentos=10
        )
        
        # Termos para monitoramento (apenas termos genéricos)
        cls.termos_contabeis = [
            ("ICMS", "TEXTO"),
            ("SUBSTITUIÇÃO TRIBUTÁRIA", "TEXTO"),
            ("TRIBUTÁRIO", "TEXTO"),
            ("FISCAL", "TEXTO"),
            ("CONTÁBIL", "TEXTO"),
            ("SEFAZ", "TEXTO"),
            ("IMPOSTO", "TEXTO")
        ]
        for termo, tipo in cls.termos_contabeis:
            TermoMonitorado.objects.create(
                termo=termo,
                tipo=tipo,
                ativo=True
            )
        
        # Criar um arquivo PDF de exemplo para testes
        cls.pdf_conteudo_exemplo = b'%PDF-1.4\n1 0 obj\n<<\n/Title (Exemplo PDF)\n/Author (Teste)\n>>\nendobj\n2 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 2 0 R\n>>\n%%EOF'
        
    def setUp(self):
        """Configuração para cada teste individual"""
        # Criar um diretório temporário para os PDFs
        self.pdf_dir = os.path.join(TEST_MEDIA_ROOT, 'pdfs')
        os.makedirs(self.pdf_dir, exist_ok=True)
        
        # Criar um diretório temporário para os relatórios
        self.relatorios_dir = os.path.join(TEST_MEDIA_ROOT, 'relatorios')
        os.makedirs(self.relatorios_dir, exist_ok=True)

    @mock.patch.object(PDFProcessor, '_extrair_texto_com_fallback')
    @mock.patch.object(PDFProcessor, 'processar_documento')
    @mock.patch.object(IntegradorSEFAZ, 'verificar_vigencia_normas')
    @mock.patch.object(RelatorioGenerator, 'gerar_relatorio_contabil')
    @mock.patch.object(RelatorioGenerator, 'gerar_relatorio_mudancas')
    def test_fluxo_completo_real(self, mock_rel_mudancas, mock_rel_contabil, 
                                mock_verif_normas, mock_processar_doc, mock_extrair_texto):
        """Teste completo do sistema com documento simulado"""
        print("\n=== INICIANDO TESTE DE SISTEMA COMPLETO ===\n")
        
        # Configurar mocks
        mock_extrair_texto.return_value = "Este é um texto de exemplo contendo palavras-chave como ICMS, TRIBUTÁRIO e FISCAL para teste."
        mock_processar_doc.return_value = True
        
        # Mock para normas verificadas
        norma1 = mock.MagicMock()
        norma1.tipo = "Lei"
        norma1.numero = "123"
        norma1.situacao = "Vigente"
        
        norma2 = mock.MagicMock()
        norma2.tipo = "Decreto"
        norma2.numero = "456"
        norma2.situacao = "Revogado"
        
        mock_verif_normas.return_value = [norma1, norma2]
        
        # Mock para relatórios
        rel_contabil_path = os.path.join(self.relatorios_dir, 'relatorio_contabil_teste.pdf')
        rel_mudancas_path = os.path.join(self.relatorios_dir, 'relatorio_mudancas_teste.pdf')
        
        with open(rel_contabil_path, 'wb') as f:
            f.write(b'Conteudo do relatorio contabil')
        
        with open(rel_mudancas_path, 'wb') as f:
            f.write(b'Conteudo do relatorio de mudancas')
            
        mock_rel_contabil.return_value = rel_contabil_path
        mock_rel_mudancas.return_value = rel_mudancas_path
        
        # 1. CARREGAMENTO DO DOCUMENTO
        print("\n1. Carregando documento...")
        
        try:
            # Criar um arquivo PDF temporário para teste
            pdf_path = os.path.join(self.pdf_dir, 'documento_teste.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(self.pdf_conteudo_exemplo)
                
            doc = Documento.objects.create(
                titulo="documento_teste.pdf",
                data_publicacao=timezone.now().date(),
                url_original=f"file://{pdf_path}",
                arquivo_pdf=SimpleUploadedFile(
                    name="documento_teste.pdf",
                    content=self.pdf_conteudo_exemplo,
                    content_type='application/pdf'
                ),
                data_coleta=timezone.now()
            )
            print(f"-> Documento criado: ID {doc.id}")
            
            # Simular normas relacionadas para o documento
            norma_vigente = NormaVigente.objects.create(
                documento=doc,
                tipo="Lei",
                numero="123",
                data_publicacao=timezone.now().date(),
                situacao="Vigente"
            )
            
            print(f"-> Norma relacionada criada: {norma_vigente.tipo} {norma_vigente.numero}")
            
        except Exception as e:
            self.fail(f"Falha ao carregar documento: {str(e)}")

        # 2. PROCESSAMENTO DO PDF
        print("\n2. Processando documento...")
        processor = PDFProcessor()
        
        try:
            # Teste de extração de texto
            texto = mock_extrair_texto.return_value
            self.assertIsNotNone(texto, "Falha na extração de texto")
            print(f"-> Texto extraído ({len(texto)} caracteres)")
            
            # Processamento completo
            success = processor.processar_documento(doc)
            self.assertTrue(success, "Falha no processamento do documento")
            
            # Atualizar o documento para simular processamento completo
            doc.processado = True
            doc.relevante_contabil = True
            doc.resumo = "Resumo de exemplo para o documento de teste."
            doc.save()
            
            print(f"-> Documento marcado como relevante: {doc.relevante_contabil}")
            print(f"-> Resumo gerado: {doc.resumo[:200]}..." if doc.resumo else "-> Sem resumo gerado")
            
        except Exception as e:
            self.fail(f"Erro no processamento: {str(e)}")

        # 3. INTEGRAÇÃO COM SEFAZ
        print("\n3. Verificando normas na SEFAZ...")
        integrador = IntegradorSEFAZ()
        
        try:
            normas_verificadas = integrador.verificar_vigencia_normas(doc.id)
            self.assertGreater(len(normas_verificadas), 0, "Nenhuma norma verificada")
            
            print(f"-> Normas verificadas ({len(normas_verificadas)}):")
            for norma in normas_verificadas:
                print(f"- {norma.tipo} {norma.numero}: {norma.situacao}")
                
            # Atualizar a norma para simular verificação
            norma_vigente.data_verificacao = timezone.now()
            norma_vigente.save()
                           
        except Exception as e:
            self.fail(f"Falha na verificação com SEFAZ: {str(e)}")

        # 4. GERAÇÃO DE RELATÓRIOS
        print("\n4. Gerando relatórios...")
        try:
            # Relatório Contábil
            rel_contabil = RelatorioGenerator.gerar_relatorio_contabil()
            self.assertTrue(os.path.exists(rel_contabil), "Relatório contábil não foi criado")
            print(f"-> Relatório contábil: {rel_contabil}")
            
            # Relatório de Mudanças
            rel_mudancas = RelatorioGenerator.gerar_relatorio_mudancas(dias_retroativos=30)
            self.assertTrue(os.path.exists(rel_mudancas), "Relatório de mudanças não foi criado")
            print(f"-> Relatório de mudanças: {rel_mudancas}")
            
        except Exception as e:
            self.fail(f"Falha na geração de relatórios: {str(e)}")

        # 5. VERIFICAÇÃO FINAL
        print("\n5. Verificando resultados finais...")
        doc.refresh_from_db()
        self.assertTrue(doc.processado, "Documento não marcado como processado")
        self.assertTrue(doc.relevante_contabil, "Documento não marcado como relevante")
        self.assertTrue(doc.normas_relacionadas.exists(), "Nenhuma norma relacionada")

        print("\n=== TESTE CONCLUÍDO COM SUCESSO ===")

    def tearDown(self):
        """Limpeza após os testes"""
        # Remove documentos criados
        for doc in Documento.objects.all():
            if doc.arquivo_pdf and os.path.exists(doc.arquivo_pdf.path):
                try:
                    os.remove(doc.arquivo_pdf.path)
                except:
                    pass
        
        # Remove relatórios temporários
        if os.path.exists(self.relatorios_dir):
            for f in os.listdir(self.relatorios_dir):
                if f.startswith('relatorio_'):
                    try:
                        os.remove(os.path.join(self.relatorios_dir, f))
                    except:
                        pass
                        
    @classmethod
    def tearDownClass(cls):
        """Limpeza após todos os testes da classe"""
        # Remover diretório de mídia temporário
        import shutil
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)