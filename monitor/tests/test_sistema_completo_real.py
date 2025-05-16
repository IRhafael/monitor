from monitor.models import Documento, NormaVigente, ConfiguracaoColeta, TermoMonitorado
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.utils.relatorio import RelatorioGenerator
from datetime import datetime, timedelta
from django.utils import timezone
import os
from django.core.files import File
from django.conf import settings

def testar_fluxo_real_sistema():
    print("\n=== TESTE DE FUNCIONAMENTO REAL DO SISTEMA ===\n")
    print("Este teste irá:")
    print("1. Carregar os PDFs reais")
    print("2. Processar seu conteúdo (extração de texto e normas)")
    print("3. Verificar a vigência das normas na SEFAZ")
    print("4. Gerar relatórios com os resultados\n")

    # 1. Configuração mínima necessária
    print("1. CONFIGURANDO TERMOS DE MONITORAMENTO...")
    TermoMonitorado.objects.all().delete()
    
    termos = ["ICMS", "SUBSTITUIÇÃO TRIBUTÁRIA", "TRIBUTÁRIO", "FISCAL", "SEFAZ"]
    for termo in termos:
        TermoMonitorado.objects.create(termo=termo, tipo="TEXTO", ativo=True)
    print(f"-> {len(termos)} termos configurados")

    # 2. Carregar PDFs reais
    print("\n2. CARREGANDO PDFs REAIS...")
    pdfs_dir = os.path.join(settings.MEDIA_ROOT, 'pdfs')
    pdf_files = [
        'Lei_n_8.558_2024.pdf',
        'Decreto_n_23.741_2025.pdf'
    ]

    documentos = []
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdfs_dir, pdf_file)
        if not os.path.exists(pdf_path):
            print(f"ERRO: Arquivo não encontrado - {pdf_path}")
            return

        with open(pdf_path, 'rb') as f:
            doc = Documento.objects.create(
                titulo=pdf_file.replace('.pdf', ''),
                data_publicacao=timezone.now().date(),
                url_original=f"file://{pdf_path}",
                data_coleta=timezone.now(),
                assunto="Documento de teste"
            )
            doc.arquivo_pdf.save(pdf_file, File(f))
            documentos.append(doc)
            print(f"-> PDF carregado: {pdf_file} (ID: {doc.id})")

    # 3. Processamento real dos documentos
    print("\n3. PROCESSANDO DOCUMENTOS (EXTRAÇÃO DE TEXTO E NORMAS)...")
    processor = PDFProcessor()
    
    for doc in documentos:
        print(f"\nProcessando documento ID {doc.id}: {doc.titulo}")
        try:
            if processor.processar_documento(doc):
                doc.refresh_from_db()
                print("-> Processamento concluído com sucesso!")
                print(f"Texto extraído: {len(doc.texto_completo or '')} caracteres")
                
                normas = doc.normas_relacionadas.all()
                print(f"Normas identificadas: {normas.count()}")
                for norma in normas:
                    print(f"- {norma.tipo} {norma.numero} (Status: {norma.situacao})")
            else:
                print("-> Documento não considerado relevante")
        except Exception as e:
            print(f"ERRO no processamento: {str(e)}")

    # 4. Verificação real na SEFAZ
    print("\n4. VERIFICANDO VIGÊNCIA DAS NORMAS NA SEFAZ...")
    integrador = IntegradorSEFAZ()
    normas_para_verificar = NormaVigente.objects.filter(situacao="A VERIFICAR")
    
    print(f"-> {normas_para_verificar.count()} normas para verificar")
    
    for norma in normas_para_verificar:
        print(f"\nVerificando {norma.tipo} {norma.numero} no portal da SEFAZ...")
        try:
            vigente, detalhes = integrador.verificar_vigencia_com_detalhes(norma.tipo, norma.numero)
            norma.situacao = "VIGENTE" if vigente else "REVOGADA"
            norma.data_verificacao = timezone.now()
            norma.fonte = "SEFAZ"
            norma.save()
            
            print(f"-> Status atualizado: {norma.situacao}")
            if detalhes:
                print(f"Detalhes: {detalhes.get('situacao', 'Sem detalhes adicionais')}")
        except Exception as e:
            print(f"ERRO na verificação: {str(e)}")

    # 5. Geração de relatórios reais
    print("\n5. GERANDO RELATÓRIOS...")
    gerador = RelatorioGenerator()
    
    print("\nRelatório contábil completo:")
    relatorio_path = gerador.gerar_relatorio_contabil()
    print(f"-> Gerado em: {relatorio_path}")
    
    print("\nRelatório de mudanças:")
    mudancas_path = gerador.gerar_relatorio_mudancas()
    print(f"-> Gerado em: {mudancas_path}")

    # 6. Resultados finais
    print("\n6. RESULTADOS FINAIS:")
    print("\nDocumentos processados:")
    for doc in Documento.objects.all():
        normas = doc.normas_relacionadas.all()
        print(f"\n- {doc.titulo}")
        print(f"  Relevante: {'Sim' if doc.relevante_contabil else 'Não'}")
        print(f"  Normas: {normas.count()}")
        for norma in normas:
            print(f"  * {norma.tipo} {norma.numero} - {norma.situacao}")

    print("\n=== TESTE DO FLUXO REAL CONCLUÍDO ===")
    print("Verifique os relatórios gerados para detalhes completos")

# Para executar:
testar_fluxo_real_sistema()