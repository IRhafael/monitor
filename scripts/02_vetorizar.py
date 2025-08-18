# Importa as bibliotecas necessárias
from openai import OpenAI
import chromadb
import os
import json
from dotenv import load_dotenv
import time

# Carrega a variável de ambiente (sua chave da OpenAI) do arquivo .env
load_dotenv()
print("Chave de API da OpenAI carregada.")

# --- CONFIGURAÇÃO DOS SERVIÇOS ---
try:
    # 1. Configura o cliente da OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    print("Cliente da OpenAI configurado.")

    # 2. Configura o cliente do ChromaDB para rodar LOCALMENTE (caminho dinâmico)
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CHROMA_PATH = os.path.join(BASE_DIR, "minha_base_vetorial")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    print(f"Cliente do ChromaDB (local) configurado em: {CHROMA_PATH}")

    # Define o nome da sua "coleção" (como uma tabela no banco de dados)
    NOME_COLECAO = "reforma_tributaria"

    # Cria a coleção ou a acessa se já existir
    # O metadata aqui define qual modelo de embedding foi usado, o que é uma boa prática.
    collection = chroma_client.get_or_create_collection(
        name=NOME_COLECAO,
        metadata={"openai_model": "text-embedding-3-small"}
    )
    print(f"Coleção '{NOME_COLECAO}' acessada/criada no ChromaDB.")

except Exception as e:
    print(f"ERRO na configuração: {e}")
    exit()

# Define o modelo de embedding da OpenAI a ser usado
EMBEDDING_MODEL = "text-embedding-3-small"

# Define o caminho para o seu arquivo JSON com os dados processados (dinâmico)
ARQUIVO_DADOS = os.path.join(BASE_DIR, "media", "documentos_processados", "base_conhecimento.json")


def vetorizar_e_enviar():
    """
    Lê os dados, gera os embeddings com a OpenAI e salva localmente no ChromaDB.
    """

    # Limpa a coleção antiga para garantir consistência
    if collection.count() > 0:
        print(f"Limpando {collection.count()} itens antigos da coleção...")
        existing_ids = collection.get(include=[])['ids']
        if existing_ids:
            collection.delete(ids=existing_ids)
        print("Coleção limpa.")

    print("\nIniciando o processo de vetorização e salvamento local...")

    try:
        with open(ARQUIVO_DADOS, 'r', encoding='utf-8') as f:
            documentos = json.load(f)
        print(f"Encontrados {len(documentos)} chunks de texto no arquivo JSON.")
    except FileNotFoundError:
        print(f"ERRO: Arquivo '{ARQUIVO_DADOS}' não encontrado.")
        return

    # Validação: remove duplicados e chunks vazios
    ids_unicos = set()
    documentos_filtrados = []
    for item in documentos:
        if not item.get('conteudo') or not item.get('id'):
            continue
        if item['id'] in ids_unicos:
            continue
        ids_unicos.add(item['id'])
        documentos_filtrados.append(item)
    print(f"Após validação: {len(documentos_filtrados)} chunks válidos para vetorização.")

    # Processa em lotes (batches)
    batch_size = 100
    total_lotes = (len(documentos_filtrados) // batch_size) + 1
    tempo_total = time.time()
    for i in range(0, len(documentos_filtrados), batch_size):
        batch = documentos_filtrados[i:i+batch_size]
        conteudos = [item['conteudo'] for item in batch]
        print(f"\nProcessando lote {i//batch_size + 1}/{total_lotes}...")
        tempo_lote = time.time()

        # 1. Gera os embeddings usando a API da OpenAI
        try:
            response = client.embeddings.create(input=conteudos, model=EMBEDDING_MODEL)
            embeddings = [item.embedding for item in response.data]
            print(f"--> {len(embeddings)} vetores gerados pela OpenAI.")
        except Exception as e:
            print(f"    ERRO ao gerar embeddings: {e}")
            continue

        # 2. Prepara os dados para salvar no ChromaDB
        metadatas = []
        for item in batch:
            metadatas.append({
                "id_original": str(item.get("id", "")),
                "titulo": str(item.get("titulo", "")),
                "sumario": str(item.get("sumario", "")),
                "fonte": str(item.get("fonte", "")),
                "artigo": str(item.get("artigo", "N/A")),
                "tema": ", ".join(item.get("tema", [])),
                "tipo_documento": str(item.get("tipo_documento", "Outro")),
                "vigente": str(item.get("vigente", True)),
                "data": str(item.get("data", "")),
                "autor": str(item.get("autor", "")),
                "embedding_model": EMBEDDING_MODEL,
                "conteudo_completo": str(item.get("conteudo", ""))
            })

        ids = [f"chunk_{item['id']}" for item in batch]

        # 3. Adiciona os dados à coleção local do ChromaDB
        try:
            collection.add(
                embeddings=embeddings,
                metadatas=metadatas,
                documents=conteudos,
                ids=ids
            )
            print(f"--> Lote salvo com sucesso no ChromaDB local. Tempo do lote: {round(time.time()-tempo_lote,2)}s")
        except Exception as e:
            print(f"    ERRO ao salvar no ChromaDB: {e}")

        time.sleep(1)

    print(f"\n\nProcesso concluído! Sua base de conhecimento foi vetorizada e salva localmente.")
    print(f"Total de itens na sua base de IA local: {collection.count()}")
    print(f"Tempo total de processamento: {round(time.time()-tempo_total,2)}s")

    # Função extra: busca de similaridade (teste)
    def buscar_similaridade(query, top_k=3):
        print(f"\nTeste de busca semântica: '{query}'")
        try:
            query_embedding = client.embeddings.create(input=[query], model=EMBEDDING_MODEL).data[0].embedding
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=['metadatas', 'documents', 'distances']
            )
            for idx in range(top_k):
                print(f"\nResultado {idx+1} (distância: {results['distances'][0][idx]:.4f}):")
                print(f"Título: {results['metadatas'][0][idx].get('titulo')}")
                print(f"Sumário: {results['metadatas'][0][idx].get('sumario')}")
                print(f"Fonte: {results['metadatas'][0][idx].get('fonte')}")
                print(f"Conteúdo: {results['documents'][0][idx][:300]}...")
        except Exception as e:
            print(f"    ERRO na busca semântica: {e}")

    # Exemplo de teste de busca
    buscar_similaridade("imposto sobre consumo no Brasil", top_k=3)

if __name__ == "__main__":
    vetorizar_e_enviar()