# PARA RODAR A API LOCALMENTE wsl -d calculadora --cd /calculadora --exec bash start.sh


import requests
import json
from datetime import datetime
import mysql.connector


# Função para converter JSON em texto explicativo
def json_para_texto(endpoint, dados):
    if not dados:
        return "Nenhuma informação disponível."
    CAMPOS_PRINCIPAIS = [
        "texto", "textocurto", "conjuntotributo", "referencianormativa",
        "codigosituacaotributaria", "descricaosituacaotributaria",
        "codigoclassificacaotributaria", "descricaoclassificacaotributaria",
        "codigo", "descricao"
    ]
    def bloco(item):
        if isinstance(item, dict):
            html = ["<div class='p-2 mb-2 border rounded bg-light'>"]
            for k, v in item.items():
                if k.lower() in CAMPOS_PRINCIPAIS:
                    html.append(f"<strong>{k.replace('_',' ').capitalize()}:</strong> {v}<br>")
            html.append("</div>")
            return "".join(html)
        else:
            return f"<div class='p-2 mb-2 border rounded bg-light'>{item}</div>"
    if isinstance(dados, list):
        return "".join([bloco(item) for item in dados])
    elif isinstance(dados, dict):
        return bloco(dados)
    else:
        return f"<div class='p-2 mb-2 border rounded bg-light'>{dados}</div>"
# Função para buscar dados do banco por data
def buscar_dados(nome, data, uf=None):
    conn = conectar_mysql()
    cursor = conn.cursor()
    if nome == "aliquota_uf":
        cursor.execute(
            "SELECT dados FROM aliquota_uf WHERE uf=%s AND data=%s ORDER BY id DESC LIMIT 1",
            (uf, data)
        )
    else:
        cursor.execute(
            f"SELECT dados FROM {nome} WHERE data=%s ORDER BY id DESC LIMIT 1",
            (data,)
        )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

# Função para buscar a data anterior disponível
def buscar_data_anterior(nome, data, uf=None):
    conn = conectar_mysql()
    cursor = conn.cursor()
    if nome == "aliquota_uf":
        cursor.execute(
            "SELECT data FROM aliquota_uf WHERE uf=%s AND data < %s ORDER BY data DESC LIMIT 1",
            (uf, data)
        )
    else:
        cursor.execute(
            f"SELECT data FROM {nome} WHERE data < %s ORDER BY data DESC LIMIT 1",
            (data,)
        )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return row[0]
    return None


# Função para conectar ao MySQL
def conectar_mysql():
    return mysql.connector.connect(
        host="localhost",  
        user="root",       
        password="1234", 
        database="monitor" 
    )

# Função para criar tabelas (uma para cada endpoint)
def criar_tabelas():
    conn = conectar_mysql()
    cursor = conn.cursor()
    tabelas = {
        "situacoes_tributarias_imposto_seletivo": "CREATE TABLE IF NOT EXISTS situacoes_tributarias_imposto_seletivo (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "situacoes_tributarias_cbs_ibs": "CREATE TABLE IF NOT EXISTS situacoes_tributarias_cbs_ibs (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "fundamentacoes_legais": "CREATE TABLE IF NOT EXISTS fundamentacoes_legais (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "classificacoes_tributarias_imposto_seletivo": "CREATE TABLE IF NOT EXISTS classificacoes_tributarias_imposto_seletivo (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "classificacoes_tributarias_cbs_ibs": "CREATE TABLE IF NOT EXISTS classificacoes_tributarias_cbs_ibs (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "aliquota_uniao": "CREATE TABLE IF NOT EXISTS aliquota_uniao (id INT AUTO_INCREMENT PRIMARY KEY, data DATE, dados JSON)",
        "aliquota_uf": "CREATE TABLE IF NOT EXISTS aliquota_uf (id INT AUTO_INCREMENT PRIMARY KEY, uf VARCHAR(2), data DATE, dados JSON)"
    }
    for sql in tabelas.values():
        cursor.execute(sql)
    conn.commit()
    cursor.close()
    conn.close()

# Função para inserir dados em cada tabela
def inserir_dados(nome, data, dados, uf=None):
    conn = conectar_mysql()
    cursor = conn.cursor()
    try:
        if nome == "aliquota_uf":
            cursor.execute(
                "INSERT INTO aliquota_uf (uf, data, dados) VALUES (%s, %s, %s)",
                (uf, data, json.dumps(dados, ensure_ascii=False))
            )
        else:
            cursor.execute(
                f"INSERT INTO {nome} (data, dados) VALUES (%s, %s)",
                (data, json.dumps(dados, ensure_ascii=False))
            )
        conn.commit()
        print(f"[OK] Dados inseridos em {nome} para data {data} UF {uf if nome == 'aliquota_uf' else ''}")
    except Exception as e:
        print(f"[ERRO] Falha ao inserir em {nome} para data {data} UF {uf if nome == 'aliquota_uf' else ''}: {e}")
    finally:
        cursor.close()
        conn.close()

# Endpoints da Receita Federal
ENDPOINTS = {
    "situacoes_tributarias_imposto_seletivo": "/calculadora/dados-abertos/situacoes-tributarias/imposto-seletivo",
    "situacoes_tributarias_cbs_ibs": "/calculadora/dados-abertos/situacoes-tributarias/cbs-ibs",
    "fundamentacoes_legais": "/calculadora/dados-abertos/fundamentacoes-legais",
    "classificacoes_tributarias_imposto_seletivo": "/calculadora/dados-abertos/classificacoes-tributarias/imposto-seletivo",
    "classificacoes_tributarias_cbs_ibs": "/calculadora/dados-abertos/classificacoes-tributarias/cbs-ibs",
    "aliquota_uniao": "/calculadora/dados-abertos/aliquota-uniao",
    "aliquota_uf": "/calculadora/dados-abertos/aliquota-uf"
}

BASE_URL = "http://localhost:8080/api"  # Endereço correto da API do Regime Geral

# Função para consumir endpoint
def consumir_endpoint(endpoint, params=None):
    url = BASE_URL + endpoint
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro ao consumir {endpoint}: {response.status_code}")
        try:
            print("Conteúdo da resposta:", response.text)
        except Exception:
            pass
        return None

# Exemplo de uso: consumir um endpoint e salvar os dados


# Função principal para integração com Django/views/tasks
def coletar_dados_receita(data=None):
    """
    Coleta dados dos endpoints da Receita Federal, salva no banco e retorna status.
    Pode ser chamada por views, comandos ou tasks.
    """
    criar_tabelas()
    ufs = consumir_endpoint("/calculadora/dados-abertos/ufs")
    if not ufs:
        print("Não foi possível obter a lista de UFs.")
        return False
    print(f"\n--- Coletando todos os dados disponíveis ---")
    # Tenta buscar datas por endpoint alternativo ou gera datas recentes
    datas_disponiveis = []
    # Tenta endpoint alternativo de datas, mas já com parâmetro 'data' para evitar erro 400
    from datetime import date, timedelta
    hoje = date.today()
    datas_api = consumir_endpoint("/calculadora/dados-abertos/aliquota-uniao", {"data": hoje.strftime('%Y-%m-%d')})
    if datas_api and isinstance(datas_api, list):
        for item in datas_api:
            data_val = item.get('data') or item.get('dataReferencia') or item.get('data_ref')
            if data_val:
                datas_disponiveis.append(data_val)
    if not datas_disponiveis:
        # Gera datas dos últimos 30 dias
        for i in range(30):
            datas_disponiveis.append((hoje - timedelta(days=i)).strftime('%Y-%m-%d'))
    # Consumir e salvar dados dos endpoints normais para cada data
    for nome, endpoint in ENDPOINTS.items():
        if nome == "aliquota_uf":
            continue
        for data in datas_disponiveis:
            dados = consumir_endpoint(endpoint, {"data": data})
            if dados:
                inserir_dados(nome, data, dados)
                print(f"Dados de {nome} inseridos no banco para data {data}!")
            else:
                print(f"Nenhum dado recebido de {nome} para data {data}.")
    # Consumir e salvar dados de aliquota_uf para cada UF e cada data
    for uf in ufs:
        codigo_uf = uf.get("codigoUf")
        sigla_uf = uf.get("sigla")
        if not codigo_uf:
            continue
        for data in datas_disponiveis:
            dados = consumir_endpoint(ENDPOINTS["aliquota_uf"], {"codigoUf": codigo_uf, "data": data})
            if dados:
                inserir_dados("aliquota_uf", data, dados, sigla_uf)
                print(f"Dados de aliquota_uf para {sigla_uf} ({codigo_uf}) inseridos no banco para data {data}!")
            else:
                print(f"Nenhum dado recebido de aliquota_uf para {sigla_uf} ({codigo_uf}) na data {data}.")
    return True

# Exemplo de chamada para integração (pode ser usado em views, comandos, tasks)
if __name__ == "__main__":
    coletar_dados_receita()
