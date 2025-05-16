from datetime import datetime, timedelta
from django.utils import timezone
from django.core.files import File
from monitor.utils.pdf_processor import PDFProcessor
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from monitor.models import Documento, NormaVigente, ConfiguracaoColeta, TermoMonitorado
import os

def testar_sistema_completo_com_pdfs():
    print("\n=== INICIANDO TESTE DO SISTEMA COMPLETO COM PDFs REAIS ===\n")
    
    # 1. Configuração inicial
    print("1. Configurando ambiente de teste...")
    ConfiguracaoColeta.objects.all().delete()
    TermoMonitorado.objects.all().delete()
    Documento.objects.all().delete()
    NormaVigente.objects.all().delete()
    
    config = ConfiguracaoColeta.objects.create(
        ativa=True,
        intervalo_horas=24,
        max_documentos=5
    )
    
    termos = [
        ("ICMS", "TEXTO"),
        ("SUBSTITUIÇÃO TRIBUTÁRIA", "TEXTO"),
        ("TRIBUTÁRIO", "TEXTO"),
        ("FISCAL", "TEXTO"),
        ("SEFAZ", "TEXTO")
    ]
    
    for termo, tipo in termos:
        TermoMonitorado.objects.create(termo=termo, tipo=tipo, ativo=True)
    
    print("-> Configuração criada com 5 termos de monitoramento")
    
    # 2. Carregar PDFs existentes
    print("\n2. Carregando PDFs existentes...")
    
    # Caminhos dos PDFs - ajuste conforme sua estrutura
    media_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'media', 'pdfs')
    pdf1_path = os.path.join(media_root, 'Lei_n_8.558_2024.pdf')
    pdf2_path = os.path.join(media_root, 'Decreto_n_23.741_2025.pdf')
    
    if not os.path.exists(pdf1_path):
        print(f"ERRO: PDF não encontrado: {pdf1_path}")
        return
    if not os.path.exists(pdf2_path):
        print(f"ERRO: PDF não encontrado: {pdf2_path}")
        return
    
    # 3. Criar documentos com os PDFs reais
    print("\n3. Criando documentos com PDFs reais...")
    
    try:
        with open(pdf1_path, 'rb') as f:
            doc1 = Documento.objects.create(
                titulo=os.path.basename(pdf1_path),
                data_publicacao=timezone.now().date(),
                url_original=f"file://{pdf1_path}",
                data_coleta=timezone.now(),
                assunto="Lei sobre ICMS e substituição tributária"
            )
            doc1.arquivo_pdf.save(os.path.basename(pdf1_path), File(f), save=True)
            print(f"-> Documento 1 criado: {doc1.titulo} (ID: {doc1.id})")
        
        with open(pdf2_path, 'rb') as f:
            doc2 = Documento.objects.create(
                titulo=os.path.basename(pdf2_path),
                data_publicacao=(timezone.now() - timedelta(days=1)).date(),
                url_original=f"file://{pdf2_path}",
                data_coleta=timezone.now(),
                assunto="Decreto sobre regulamentação fiscal"
            )
            doc2.arquivo_pdf.save(os.path.basename(pdf2_path), File(f), save=True)
            print(f"-> Documento 2 criado: {doc2.titulo} (ID: {doc2.id})")
    
    except Exception as e:
        print(f"ERRO ao criar documentos: {str(e)}")
        return
    
    # 4. Processamento dos documentos com tratamento robusto
    print("\n4. Processando documentos com PDFProcessor...")
    processor = PDFProcessor()
    
    for doc in [doc1, doc2]:
        try:
            print(f"\nProcessando documento {doc.id} ({doc.titulo})...")
            
            # Verificar se o arquivo PDF existe
            if not doc.arquivo_pdf or not os.path.exists(doc.arquivo_pdf.path):
                print(f"-> Arquivo PDF não encontrado para o documento {doc.id}")
                continue
                
            # Tentar processar o documento
            try:
                success = processor.processar_documento(doc)
            except Exception as e:
                print(f"-> Erro durante o processamento: {str(e)}")
                continue
                
            if success:
                doc.refresh_from_db()
                print(f"-> Processado com sucesso! Relevante: {doc.relevante_contabil}")
                
                # Mostrar informações do processamento
                print(f"Tamanho do texto: {len(doc.texto_completo) if doc.texto_completo else 0} caracteres")
                print(f"Resumo: {doc.resumo[:200] + '...' if doc.resumo else 'Sem resumo gerado'}")
                
                # Mostrar normas encontradas
                normas = doc.normas_relacionadas.all()
                if normas.exists():
                    print("Normas identificadas:")
                    for norma in normas:
                        print(f"- {norma.tipo} {norma.numero} (Situação: {norma.situacao})")
                else:
                    print("Nenhuma norma identificada")
            else:
                print("-> O documento não foi considerado relevante ou houve falha no processamento")
                
        except Exception as e:
            print(f"ERRO ao processar documento {doc.id}: {str(e)}")
            continue
    
    # 5. Verificação na SEFAZ (simulada com mock)
    print("\n5. Simulando verificação na SEFAZ com mock...")
    
    normas_para_verificar = NormaVigente.objects.filter(situacao="A VERIFICAR")
    if not normas_para_verificar.exists():
        print("Nenhuma norma para verificar")
    else:
        for norma in normas_para_verificar:
            try:
                # Simular verificação - alternando entre vigente e revogada
                if norma.tipo == "LEI":
                    norma.situacao = "VIGENTE"
                else:
                    norma.situacao = "REVOGADA"
                    
                norma.data_verificacao = timezone.now()
                norma.fonte = "SEFAZ"
                norma.save()
                
                print(f"-> {norma.tipo} {norma.numero} marcada como {norma.situacao}")
                
            except Exception as e:
                print(f"ERRO ao verificar norma {norma.tipo} {norma.numero}: {str(e)}")
    
    # 6. Verificação final detalhada
    print("\n6. Resultados finais detalhados:")
    
    print("\nDOCUMENTOS PROCESSADOS:")
    for doc in Documento.objects.all():
        print(f"\n[ID: {doc.id}] {doc.titulo}")
        print(f"- Data: {doc.data_publicacao}")
        print(f"- Processado: {'Sim' if doc.processado else 'Não'}")
        print(f"- Relevante: {'Sim' if doc.relevante_contabil else 'Não'}")
        print(f"- Tamanho do texto: {len(doc.texto_completo) if doc.texto_completo else 0} caracteres")
        print(f"- Resumo: {doc.resumo[:100] + '...' if doc.resumo else 'Sem resumo'}")
        
        normas = doc.normas_relacionadas.all()
        print(f"- Normas relacionadas ({normas.count()}):")
        for norma in normas:
            print(f"  • {norma.tipo} {norma.numero} ({norma.situacao})")
    
    print("\nNORMAS IDENTIFICADAS:")
    for norma in NormaVigente.objects.all():
        print(f"\n{norma.tipo} {norma.numero}")
        print(f"- Situação: {norma.situacao}")
        print(f"- Fonte: {norma.fonte}")
        print(f"- Verificado em: {norma.data_verificacao}")
        print(f"- Documentos relacionados: {norma.documentos.count()}")
    
    print("\n=== TESTE CONCLUÍDO ===\n")

# Executar o teste
testar_sistema_completo_com_pdfs()