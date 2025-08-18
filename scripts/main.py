# Importa as bibliotecas necessárias
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import chromadb
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente (sua chave da OpenAI)
load_dotenv()
print("API: Chave da OpenAI carregada.")

# --- CONFIGURAÇÃO E INICIALIZAÇÃO (executado uma vez quando a API inicia) ---

# 1. Inicializa o cliente da OpenAI
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    print("API: Cliente da OpenAI configurado.")
except Exception as e:
    print(f"API ERRO: Falha ao configurar o cliente da OpenAI: {e}")
    client = None

# 2. Inicializa o cliente do ChromaDB e conecta à base de dados local
import os
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CHROMA_PATH = os.path.join(BASE_DIR, "minha_base_vetorial")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_or_create_collection(
        name="reforma_tributaria",
        metadata={"openai_model": "text-embedding-3-small"}
    )
    print(f"API: Conectado à coleção '{collection.name}' com {collection.count()} itens.")
except Exception as e:
    print(f"API ERRO: Falha ao conectar ao ChromaDB. Verifique se a base de dados existe: {e}")
    collection = None

# Modelos a serem usados
EMBEDDING_MODEL = "text-embedding-3-small"
GPT_MODEL = "gpt-3.5-turbo" 

# 3. Inicializa a aplicação FastAPI
app = FastAPI(
    title="IA-Reforma-Tributária API",
    description="API para responder perguntas sobre a Reforma Tributária com base em documentos locais.",
    version="1.0.0"
)

@app.get("/demo")
def demo():
    """Endpoint de demonstração: retorna resposta para uma pergunta exemplo."""
    pergunta_demo = "Qual o impacto da reforma tributária sobre o consumo?"
    return consultar(PerguntaUsuario(pergunta=pergunta_demo, top_k=3))

# Para rodar a API, execute:
# uvicorn scripts.main:app --reload


# --- DEFINIÇÃO DOS DADOS DE ENTRADA (Request Body) ---
class PerguntaUsuario(BaseModel):
    pergunta: str
    top_k: int = 8


# --- LÓGICA DO PROMPT PARA O GPT ---
def construir_prompt(pergunta: str, contexto: list[str]) -> str:
    contexto_formatado = "\n\n---\n\n".join(contexto)
    prompt = f"""
    Você é um consultor fiscal e contábil altamente atualizado, especialista em legislação tributária, obrigações acessórias, novidades fiscais e práticas do mundo contábil brasileiro.
    Sua tarefa é relatar novidades, esclarecer dúvidas dos colaboradores e fornecer informações sempre baseadas EXCLUSIVAMENTE no contexto fornecido abaixo, que pode vir de documentos oficiais, notícias, webscraping de páginas tributárias ou fontes confiáveis do setor.

    REGRAS IMPORTANTES:
    1. NÃO invente informações ou use conhecimento externo. Responda apenas com base no contexto apresentado.
    2. Se o contexto não contiver informação suficiente para responder à pergunta, responda exatamente: "Com base nos documentos fornecidos, não encontrei informações suficientes para responder a esta pergunta."
    3. Estruture sua resposta de forma profissional, clara e fácil de entender.
    4. Sempre que possível, cite a fonte ou documento mencionado no contexto para dar credibilidade à resposta.
    5. Se a pergunta for sobre novidades, relacione as atualizações mais recentes presentes no contexto.

    CONTEXTO EXTRAÍDO DAS FONTES FISCAIS/CONTÁBEIS:
    {contexto_formatado}

    PERGUNTA DO USUÁRIO:
    {pergunta}

    RESPOSTA:
    """
    return prompt


@app.post("/consultar")
def consultar(pergunta_usuario: PerguntaUsuario):
    if not client or not collection:
        raise HTTPException(status_code=500, detail="Serviço de IA ou Banco de Dados não inicializado corretamente.")

    print(f"\nRecebida nova pergunta: '{pergunta_usuario.pergunta}'")
    top_k = min(max(pergunta_usuario.top_k, 1), 10)

    try:
        query_embedding = client.embeddings.create(
            input=[pergunta_usuario.pergunta],
            model=EMBEDDING_MODEL
        ).data[0].embedding
        print("--> Pergunta vetorizada com sucesso.")
    except Exception as e:
        print(f"ERRO ao vetorizar pergunta: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na API da OpenAI (Embedding): {e}")

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=['documents', 'metadatas', 'distances']
        )
        contexto_encontrado = results['documents'][0]
        metadados_encontrados = results['metadatas'][0]
        distancias_encontradas = results['distances'][0]
        print(f"--> {len(contexto_encontrado)} chunks de contexto encontrados no ChromaDB.")
    except Exception as e:
        print(f"ERRO ao buscar no ChromaDB: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na busca do banco de dados vetorial: {e}")

    prompt_final = construir_prompt(pergunta_usuario.pergunta, contexto_encontrado)

    try:
        print("--> Enviando prompt final para o GPT...")
        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": "Você é um assistente especialista em legislação tributária."},
                {"role": "user", "content": prompt_final}
            ],
            temperature=0.2,
        )
        resposta_final = response.choices[0].message.content
        print("--> Resposta recebida do GPT.")
    except Exception as e:
        print(f"ERRO ao chamar a API do GPT: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na API da OpenAI (ChatCompletion): {e}")

    # Retorna resposta e contexto usado (com metadados)
    contexto_completo = []
    for i in range(len(contexto_encontrado)):
        contexto_completo.append({
            "conteudo": contexto_encontrado[i],
            "metadados": metadados_encontrados[i],
            "distancia": distancias_encontradas[i]
        })

    return {
        "resposta": resposta_final,
        "contexto_utilizado": contexto_completo
    }

# --- ENDPOINT DE STATUS/HEALTHCHECK ---
@app.get("/status")
def status():
    return {
        "openai": bool(client),
        "chroma": bool(collection),
        "itens_base": collection.count() if collection else 0,
        "embedding_model": EMBEDDING_MODEL,
        "gpt_model": GPT_MODEL
    }

