#!/usr/bin/env python
import os
import django
import uuid
from io import BytesIO # Para ler o PDF em memória

# Configure o ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
django.setup()

from monitor.models import Documento, TermoMonitorado, NormaVigente
from monitor.utils.pdf_processor import PDFProcessor
from django.utils import timezone
from django.core.files.base import ContentFile # Para salvar o PDF no modelo

# Função para extrair texto de PDF usando pdfminer.six
from pdfminer.high_level import extract_text as pdfminer_extract_text
from pdfminer.layout import LAParams

def extrair_texto_pdf_local(caminho_pdf: str) -> str:
    """Extrai texto de um arquivo PDF local."""
    try:
        with open(caminho_pdf, 'rb') as f:
            texto = pdfminer_extract_text(f, laparams=LAParams())
            return texto
    except Exception as e:
        print(f"Erro ao extrair texto do PDF {caminho_pdf}: {e}")
        return ""

def criar_ou_atualizar_documento_de_arquivo(caminho_pdf_real: str, url_original_doc: str):
    """
    Cria ou atualiza um Documento no banco de dados a partir de um arquivo PDF real.
    Garante que a url_original seja única.
    """
    print(f"Processando arquivo PDF real: {caminho_pdf_real}")
    if not os.path.exists(caminho_pdf_real):
        print(f"ERRO: Arquivo PDF não encontrado em {caminho_pdf_real}")
        return None

    texto_extraido = extrair_texto_pdf_local(caminho_pdf_real)
    if not texto_extraido:
        print(f"ERRO: Não foi possível extrair texto do PDF {caminho_pdf_real}")
        return None

    # Extrai o nome do arquivo para usar como título
    nome_arquivo = os.path.basename(caminho_pdf_real)
    titulo_doc = nome_arquivo.replace('.pdf', '').replace('_', ' ')

    # Usar get_or_create para o Documento
    documento, created = Documento.objects.get_or_create(
        url_original=url_original_doc, # Use uma URL única e significativa para este documento de teste
        defaults={
            'titulo': titulo_doc,
            'texto_completo': texto_extraido,
            'data_publicacao': timezone.now().date(),
            'data_coleta': timezone.now(),
            'processado': False,
            'relevante_contabil': False,
            # Adicione outros campos com seus valores padrão aqui, se necessário
            # 'tipo_documento': 'OUTRO', # Exemplo
            # 'fonte_documento': 'Arquivo de Teste Local', # Exemplo
        }
    )

    if created:
        print(f"Documento de teste criado a partir do arquivo: {documento.titulo} (ID: {documento.id})")
    else:
        print(f"Documento de teste (de arquivo) já existia: {documento.titulo} (ID: {documento.id})")
        # Atualiza o texto e reseta o status para re-teste
        documento.titulo = titulo_doc # Garante que o título está atualizado
        documento.texto_completo = texto_extraido
        documento.processado = False
        documento.relevante_contabil = False
        # Limpar relações e campos de IA para um novo teste limpo
        documento.normas_relacionadas.clear()
        if hasattr(documento, 'resumo_ia'):
            documento.resumo_ia = None
        if hasattr(documento, 'sentimento_ia'):
            documento.sentimento_ia = None
        if hasattr(documento, 'metadata'):
            documento.metadata = {} # Reseta metadados da IA
        # Não precisa salvar o arquivo PDF novamente se ele já existe no objeto Documento
        # e a ideia é apenas reprocessar o texto. Se quiser forçar o re-upload:
        # with open(caminho_pdf_real, 'rb') as f_pdf:
        #     documento.arquivo_pdf.save(nome_arquivo, ContentFile(f_pdf.read()), save=False)
        documento.save()

    # Adiciona termos monitorados para teste (usando get_or_create para evitar IntegrityError)
    # Estes termos podem ser genéricos ou específicos para o conteúdo do seu PDF de teste
    termos_para_teste = [
        {"termo": "ICMS", "tipo": "TEXTO", "variacoes": "Imposto sobre Circulação de Mercadorias", "prioridade": 5},
        {"termo": "DECRETO", "tipo": "TEXTO", "variacoes": "Decretos", "prioridade": 3}, # Termo genérico para ajudar a IA
        # Adicione termos que você espera encontrar no seu PDF de teste
    ]

    for item_termo in termos_para_teste:
        termo_obj, termo_created = TermoMonitorado.objects.get_or_create(
            termo=item_termo["termo"],
            defaults={
                'tipo': item_termo["tipo"],
                'variacoes': item_termo.get("variacoes", ""),
                'ativo': True,
                'prioridade': item_termo.get("prioridade", 3)
            }
        )
        if termo_created:
            print(f"Termo Monitorado criado: {termo_obj.termo}")
        else: # Opcional: atualizar se já existir
            termo_obj.tipo = item_termo["tipo"]
            termo_obj.variacoes = item_termo.get("variacoes", "")
            termo_obj.ativo = True
            termo_obj.prioridade = item_termo.get("prioridade", 3)
            termo_obj.save()
            print(f"Termo Monitorado já existia/atualizado: {termo_obj.termo}")


    return documento

def testar_pdf_processor_com_arquivo_real(caminho_do_pdf: str, url_doc_teste: str):
    print(f"\n=== TESTE DO PDF PROCESSOR COM ARQUIVO REAL: {os.path.basename(caminho_do_pdf)} ===")
    print("Criando/Obtendo documento de teste e termos...")
    documento = criar_ou_atualizar_documento_de_arquivo(caminho_do_pdf, url_doc_teste)

    if not documento:
        print("Não foi possível criar o documento a partir do arquivo PDF. Teste abortado.")
        return

    print("\nDocumento a ser processado:")
    print(f"  ID: {documento.id}")
    print(f"  Título: {documento.titulo}")
    print(f"  Texto (início): {documento.texto_completo[:250]}...") # Mostra um trecho maior

    print("\nInstanciando PDFProcessor...")
    processor = PDFProcessor()

    print("\nProcessando documento com PDFProcessor...")
    resultado = processor.process_document(documento)

    print("\n------------------------------------")
    print("  RESULTADO DO PROCESSAMENTO (PDFProcessor):")
    print("------------------------------------")
    if resultado:
        print(f"  Status: {resultado.get('status')}")
        print(f"  Mensagem: {resultado.get('message')}")
        print(f"  Relevante (IA): {resultado.get('relevante_contabil')}")
        if resultado.get('relevante_contabil'):
             print(f"  Justificativa Relevância (IA): {resultado.get('justificativa_relevancia', 'N/A')}")

        print("\n  Normas extraídas (Regex/spaCy):")
        normas_extraidas_proc = resultado.get('normas_extraidas', [])
        if normas_extraidas_proc:
            for norma_str in normas_extraidas_proc:
                print(f"    - {norma_str}")
        else:
            print("    Nenhuma norma extraída pelo processador.")

        print("\n  Resumo IA (do resultado do processamento):")
        print(f"    {resultado.get('resumo_ia', 'N/A')}")

        print("\n  Pontos Críticos (IA - do resultado do processamento):")
        pontos_criticos_proc = resultado.get('pontos_criticos', [])
        if pontos_criticos_proc and isinstance(pontos_criticos_proc, list): # Verifica se é uma lista
            for ponto in pontos_criticos_proc:
                print(f"    - {ponto}")
        elif pontos_criticos_proc: # Se não for lista mas tiver valor, imprime
             print(f"    {pontos_criticos_proc}")
        else:
            print("    N/A ou não retornado.")
    else:
        print("  Resultado do processamento foi None.")
    print("------------------------------------\n")

    # Recarrega o documento do banco para ver as alterações salvas
    documento.refresh_from_db()
    print("\n------------------------------------")
    print("  DOCUMENTO APÓS PROCESSAMENTO (DO BANCO DE DADOS):")
    print("------------------------------------")
    print(f"  ID: {documento.id}")
    print(f"  Título: {documento.titulo}")
    print(f"  Processado: {documento.processado}")
    print(f"  Relevante contábil: {documento.relevante_contabil}")
    print(f"  Assunto: {documento.assunto}")

    if hasattr(documento, 'resumo_ia') and documento.resumo_ia:
        print(f"  Resumo IA (armazenado): {documento.resumo_ia[:250]}...")
    else:
        print(f"  Resumo Principal (armazenado): {documento.resumo[:250]}...")


    if hasattr(documento, 'metadata') and documento.metadata:
         print(f"  Pontos Críticos IA (metadata): {documento.metadata.get('ia_pontos_criticos', 'N/A')}")
         print(f"  Justificativa Relevância IA (metadata): {documento.metadata.get('ia_relevancia_justificativa', 'N/A')}")
         print(f"  Modelo IA Usado (metadata): {documento.metadata.get('ia_modelo_usado', 'N/A')}")
    else:
        print("  Campo 'metadata' não encontrado ou vazio no modelo Documento.")

    normas_relacionadas_db = documento.normas_relacionadas.all()
    print("\n  Normas relacionadas no banco:")
    if normas_relacionadas_db.exists():
        for norma_obj in normas_relacionadas_db:
            print(f"    - {norma_obj.tipo} {norma_obj.numero} (Última menção: {norma_obj.data_ultima_mencao})")
    else:
        print("    Nenhuma norma relacionada encontrada no banco para este documento.")
    print("------------------------------------\n")

    print("\n=== TESTE CONCLUÍDO ===")

if __name__ == "__main__":
    # ---------------------------------------------------------------------
    # MODIFIQUE AQUI: Coloque o caminho para um PDF real no seu sistema
    # E uma URL única para identificar este documento de teste no banco
    # ---------------------------------------------------------------------
    CAMINHO_PDF_EXEMPLO = r"C:\Users\RRCONTAS\Documents\GitHub\monitor\media\pdfs\DOEPI_96_2025_1.pdf" # Exemplo: r"C:\Users\SeuNome\Documentos\diario_exemplo.pdf"
    URL_DOCUMENTO_TESTE = "https://www.diario.pi.gov.br/doe/files/diarios/anexo/d94ccdb3-5e89-4f5c-add5-56827fd1858a/DOEPI_99_2025.pdf"
    # ---------------------------------------------------------------------

    if not os.path.exists(CAMINHO_PDF_EXEMPLO):
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"ATENÇÃO: O arquivo PDF de exemplo NÃO FOI ENCONTRADO em '{CAMINHO_PDF_EXEMPLO}'.")
        print(f"Por favor, edite o script 'teste.py' na seção '__main__'")
        print(f"e coloque um caminho válido para um arquivo PDF que você deseja testar.")
        print(f"O teste não será executado com um arquivo real até que isso seja feito.")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        # Opcional: Você pode rodar o teste com o texto fixo se o arquivo não for encontrado
        print("\nRodando teste com texto fixo embutido como fallback...")
        from teste_com_texto_fixo import testar_pdf_processor_texto_fixo # Supondo que você tenha isso em outro arquivo
        testar_pdf_processor_texto_fixo()
    else:
        testar_pdf_processor_com_arquivo_real(CAMINHO_PDF_EXEMPLO, URL_DOCUMENTO_TESTE)