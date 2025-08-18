# Importa as bibliotecas necessárias
import fitz  # Esta é a biblioteca PyMuPDF
import os
import json

# --- CONFIGURAÇÃO ---
# Define os caminhos para as pastas de entrada e saída de forma dinâmica
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DOCUMENTOS = os.path.join(BASE_DIR, 'media', 'pdfs')
PASTA_SAIDA = os.path.join(BASE_DIR, 'media', 'documentos_processados')
ARQUIVO_SAIDA = os.path.join(PASTA_SAIDA, 'base_conhecimento.json')

# Garante que a pasta de saída exista. Se não existir, o script a cria.
os.makedirs(PASTA_SAIDA, exist_ok=True)

def extrair_e_processar_pdfs():
    """
    Função principal que lê os PDFs, extrai o texto e salva em um arquivo JSON.
    """


    import re

    base_conhecimento = []
    id_counter = 1
    print("Iniciando processamento de documentos...")


    def extrair_data(texto, nome_arquivo):
        padrao_data = r'(\d{2}/\d{2}/\d{4})|(\d{4}-\d{2}-\d{2})'
        match = re.search(padrao_data, texto)
        if match:
            return match.group(0)
        match = re.search(padrao_data, nome_arquivo)
        if match:
            return match.group(0)
        return None

    def extrair_artigo(texto):
        padrao_artigo = r'(Art\.\s*\d+[A-Za-z\-]*)|(Se[cç][aã]o\s*\d+)|(§\s*\d+)'
        match = re.search(padrao_artigo, texto)
        if match:
            return match.group(0)
        return None

    def gerar_temas(texto):
        temas = []
        palavras_chave = [
            ('tributária', 'tributação'),
            ('federativo', 'federalismo'),
            ('ICMS', 'ICMS'),
            ('IPI', 'IPI'),
            ('ISS', 'ISS'),
            ('imposto', 'impostos'),
            ('arrecadação', 'arrecadação'),
            ('desoneração', 'desoneração'),
            ('guerra fiscal', 'guerra fiscal'),
            ('repartição', 'repartição'),
            ('complexidade', 'complexidade'),
            ('regressividade', 'regressividade'),
            ('transparência', 'transparência'),
            ('eficiência', 'eficiência'),
            ('autonomia', 'autonomia'),
            ('município', 'municípios'),
            ('estado', 'estados'),
            ('União', 'União'),
        ]
        texto_lower = texto.lower()
        for termo, tema in palavras_chave:
            if termo in texto_lower:
                temas.append(tema)
        return list(set(temas))

    def gerar_sumario(texto):
        # Sumarização simples: pega as primeiras frases ou até 200 caracteres
        frases = re.split(r'(?<=[.!?]) +', texto)
        sumario = ''
        for frase in frases:
            if len(sumario) + len(frase) <= 200:
                sumario += frase + ' '
            else:
                break
        return sumario.strip() if sumario else texto[:200]

    def classificar_tipo_documento(nome_arquivo, texto):
        # Classifica tipo de documento por padrões no nome ou texto
        if 'lei' in nome_arquivo.lower() or 'lei' in texto.lower():
            return 'Lei'
        if 'emenda' in nome_arquivo.lower() or 'emenda' in texto.lower():
            return 'Emenda Constitucional'
        if 'artigo' in nome_arquivo.lower() or 'artigo' in texto.lower():
            return 'Artigo Científico'
        if 'decreto' in nome_arquivo.lower() or 'decreto' in texto.lower():
            return 'Decreto'
        return 'Outro'

    def extrair_autor(texto):
        # Busca por padrões de autoria
        padrao_autor = r'(por\s+([A-Z][a-z]+\s+[A-Z][a-z]+))|(Autor[a-z]*:.*?\n)'
        match = re.search(padrao_autor, texto)
        if match:
            return match.group(0).replace('\n', '').strip()
        return None

    def validar_data(data):
        # Valida se a data está no formato correto
        if not data:
            return None
        try:
            import datetime
            if '/' in data:
                datetime.datetime.strptime(data, '%d/%m/%Y')
            elif '-' in data:
                datetime.datetime.strptime(data, '%Y-%m-%d')
            else:
                return None
            return data
        except Exception:
            return None

    def normalizar_artigo(artigo):
        if artigo:
            return artigo.replace('Art.', 'Artigo').replace('Seção', 'Seção').replace('§', 'Parágrafo')
        return None


    for nome_arquivo in os.listdir(PASTA_DOCUMENTOS):
        if nome_arquivo.lower().endswith('.pdf'):
            caminho_completo = os.path.join(PASTA_DOCUMENTOS, nome_arquivo)
            print(f"--> Processando arquivo: {nome_arquivo}")

            try:
                doc = fitz.open(caminho_completo)
                for num_pagina, pagina in enumerate(doc):
                    texto_bruto = pagina.get_text("text")
                    chunks = texto_bruto.split('\n\n')

                    for chunk in chunks:
                        texto_limpo = chunk.strip().replace('\n', ' ')
                        if len(texto_limpo) > 50:
                            data_extraida = validar_data(extrair_data(texto_limpo, nome_arquivo))
                            artigo_extraido = normalizar_artigo(extrair_artigo(texto_limpo))
                            temas_extraidos = gerar_temas(texto_limpo)
                            sumario = gerar_sumario(texto_limpo)
                            tipo_documento = classificar_tipo_documento(nome_arquivo, texto_limpo)
                            autor = extrair_autor(texto_limpo)
                            base_conhecimento.append({
                                'id': id_counter,
                                'titulo': texto_limpo[:60] + '...' if len(texto_limpo) > 60 else texto_limpo,
                                'sumario': sumario,
                                'fonte': f"{nome_arquivo} (página {num_pagina + 1})",
                                'data': data_extraida,
                                'artigo': artigo_extraido,
                                'tema': temas_extraidos,
                                'tipo_documento': tipo_documento,
                                'autor': autor,
                                'vigente': True,
                                'conteudo': texto_limpo
                            })
                            id_counter += 1
                doc.close()
            except Exception as e:
                print(f"    ERRO ao processar o arquivo {nome_arquivo}: {e}")

    print(f"\nProcessamento concluído. {len(base_conhecimento)} chunks de texto foram extraídos.")

    with open(ARQUIVO_SAIDA, 'w', encoding='utf-8') as f:
        json.dump(base_conhecimento, f, ensure_ascii=False, indent=2)

    print(f"Base de conhecimento salva em: {ARQUIVO_SAIDA}")

# --- EXECUÇÃO ---
# Este bloco garante que a função só será executada quando o script for chamado diretamente
if __name__ == "__main__":
    extrair_e_processar_pdfs()