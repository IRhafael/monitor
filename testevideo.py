
import os
import uuid
import requests
from pdf_processor import MistralAI
from relatorio import RelatorioAvancado
from sefaz_integracao import IntegradorSEFAZ

def baixar_pdf(url, destino='pdfs'):
    os.makedirs(destino, exist_ok=True)
    nome_arquivo = f"{uuid.uuid4()}.pdf"
    caminho_completo = os.path.join(destino, nome_arquivo)
    print(f"Baixando PDF de {url}")
    response = requests.get(url)
    if response.status_code == 200:
        with open(caminho_completo, 'wb') as f:
            f.write(response.content)
        print(f"PDF salvo como {caminho_completo}")
        return caminho_completo
    else:
        raise Exception("Erro ao baixar PDF.")

def extrair_texto_do_pdf(caminho_pdf):
    from diario_scraper import DiarioOficialScraper
    scraper = DiarioOficialScraper()
    with open(caminho_pdf, 'rb') as f:
        pdf_bytes = f.read()
    texto = scraper.extrair_texto_pdf(pdf_bytes)
    return texto

def processar_documento(texto, max_normas=5):
    mistral = MistralAI()
    resumo = mistral.gerar_resumo_contabil(texto)
    sentimento = mistral.analisar_sentimento_contabil(texto)
    impacto = mistral.identificar_impacto_fiscal(texto)
    integrador = IntegradorSEFAZ()
    normas = integrador.extrair_normas_do_texto(texto)[:max_normas]
    resultados_vigencia = []
    for tipo, numero in normas:
        status = integrador.buscar_norma_especifica(tipo, numero)
        resultados_vigencia.append(status)
    return {
        "resumo": resumo,
        "sentimento": sentimento,
        "impacto": impacto,
        "normas": resultados_vigencia
    }

def salvar_relatorio(resultados, destino='relatorios'):
    os.makedirs(destino, exist_ok=True)
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Resumo Técnico", "Sentimento", "Impactos Fiscais"])
    ws.append([resultados["resumo"], resultados["sentimento"], resultados["impacto"]])
    ws.append([])
    ws.append(["Normas Identificadas", "Situação"])
    for norma in resultados["normas"]:
        ws.append([f'{norma["tipo"]} {norma["numero"]}', norma.get("vigente", "Desconhecido")])
    nome_arquivo = os.path.join(destino, f"relatorio_{uuid.uuid4().hex[:8]}.xlsx")
    wb.save(nome_arquivo)
    print(f"Relatório salvo em: {nome_arquivo}")

def main():
    url = input("Informe a URL do PDF: ").strip()
    caminho = baixar_pdf(url)
    texto = extrair_texto_do_pdf(caminho)
    resultados = processar_documento(texto)
    salvar_relatorio(resultados)

if __name__ == "__main__":
    main()
