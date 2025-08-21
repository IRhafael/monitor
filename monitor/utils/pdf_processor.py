import re
class PDFProcessor:
	"""
	Stub mínimo para evitar erro de importação em outros módulos Django.
	"""
	pass
import os
import requests
from dotenv import load_dotenv
from pdfminer.high_level import extract_text

# Carrega variáveis do .env
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path)

def processar_pdf_com_openai(pdf_path, modelo="gpt-3.5-turbo", normas_info=None):
	"""
	Extrai texto de um PDF e processa com OpenAI, retornando o resumo. Pode receber normas_info para enriquecer o prompt.
	"""
	chave_api = os.environ.get("OPENAI_API_KEY")
	if not chave_api:
		raise Exception("OPENAI_API_KEY não encontrada no .env")
	texto = extract_text(pdf_path)
	max_chars = 12000
	texto_truncado = texto[:max_chars]
	if len(texto) > max_chars:
		texto_truncado += "\n\n[TEXTO TRUNCADO - ENVIE O PDF EM PARTES PARA ANÁLISE COMPLETA]"
	prompt = (
		"Você é um assistente para análise de documentos fiscais e contábeis. "
		"Resuma o texto abaixo, destaque atos normativos, leis, decretos, portarias e informações relevantes. "
		"Texto:\n" + texto_truncado
	)
	if normas_info:
		normas_txt = "\n\nNormas identificadas e status de vigência (consultadas na SEFAZ):\n"
		for n in normas_info:
			normas_txt += f"- {n['tipo']} {n['numero']}: Vigente={n['vigente']} | Status={n['status']}\n"
		prompt += normas_txt
	url = "https://api.openai.com/v1/chat/completions"
	headers = {
		"Authorization": f"Bearer {chave_api}",
		"Content-Type": "application/json"
	}
	data = {
		"model": modelo,
		"messages": [
			{"role": "system", "content": "Você é um especialista em documentos fiscais/contábeis."},
			{"role": "user", "content": prompt}
		],
		"max_tokens": 512,
		"temperature": 0.2
	}
	response = requests.post(url, headers=headers, json=data, timeout=60)
	if response.status_code == 200:
		resposta = response.json()
		conteudo = resposta["choices"][0]["message"]["content"]
		return conteudo
	else:
		raise Exception(f"OpenAI status {response.status_code}: {response.text}")
	



def limpar_texto_documento(texto):
	"""
	Remove sumário, rodapés, cabeçalhos e ruídos comuns do DOEPI.
	"""
	# Remove sumário até o primeiro título principal
	texto = re.sub(r"SUMÁRIO[\s\S]*?(DECRETOS|PORTARIAS|EXTRATOS|AVISOS|EDITAIS|ATOS|ERRATAS|DECISÕES|NOMEAÇÕES E/OU EXONERAÇÕES)", r"\1", texto, flags=re.IGNORECASE)
	# Remove padrões de rodapé/cabeçalho
	noise_patterns = [
		r"^\s*Disponibilizado:.*$",
		r"^\s*Publicado:.*$",
		r"^\s*Diário Oficial\s*$",
		r"^\s*Estado do Piaui\s*$",
		r"^\s*Diário nº \d+/\d+, \d+ de \w+ de \d{4}\.",
		r"^\s*\*\*\* Iniciado: .* \*\*\*\s*$",
		r"^\s*Página \d+/\d+\s*$",
		r"^\s*ESTADO DO PIAUI\s*$",
		r"^\s*GOVERNO DO\s*$",
		r"^\s*PIAUÍ\s*$",
		r"^\s*AQUI TEM TRABALHO\.\s*$",
		r"^\s*AQUI TEM FUTURO\.\s*$",
		r"^\s*IMPAVIDUM FERIENT RUINAE\s*$",
		r"^\s*\(Transcrição da nota .* de Nº .*, datada de .* de \w+ de \d{4}\.\?\)\s*$"
	]
	for pattern in noise_patterns:
		texto = re.sub(pattern, "", texto, flags=re.MULTILINE)
	# Remove múltiplas quebras de linha
	texto = re.sub(r'\n{3,}', '\n\n', texto)
	# Remove espaços em branco excessivos
	texto = re.sub(r' {2,}', ' ', texto)
	return texto.strip()

def gerar_relatorio_completo_openai(pdf_path, modelo="gpt-3.5-turbo", normas_info=None):
	"""
	Pipeline: extrai texto, limpa, processa com OpenAI e gera relatório consolidado. Pode receber normas_info para enriquecer o prompt.
	"""
	chave_api = os.environ.get("OPENAI_API_KEY")
	if not chave_api:
		raise Exception("OPENAI_API_KEY não encontrada no .env")
	texto = extract_text(pdf_path)
	texto_limpo = limpar_texto_documento(texto)
	max_chars = 12000
	texto_truncado = texto_limpo[:max_chars]
	if len(texto_limpo) > max_chars:
		texto_truncado += "\n\n[TEXTO TRUNCADO - ENVIE O PDF EM PARTES PARA ANÁLISE COMPLETA]"
	prompt = (
		"Você é um Consultor Tributário Estratégico e Analista Regulatório Sênior, especialista em legislação fiscal e contábil do Piauí. "
		"Analise o texto abaixo e elabore um RELATÓRIO CONSOLIDADO com as seguintes seções:\n"
		"1. PRINCIPAIS TEMAS E ALTERAÇÕES LEGISLATIVAS IDENTIFICADAS\n"
		"2. TENDÊNCIAS REGULATÓRIAS EMERGENTES PARA O PIAUÍ\n"
		"3. POTENCIAIS RISCOS E PONTOS DE ATENÇÃO CRÍTICOS\n"
		"4. RECOMENDAÇÕES ESTRATÉGICAS E AÇÕES IMEDIATAS PARA CONTADORES\n"
		"5. SÍNTESE DO SENTIMENTO GERAL (IMPACTO PREDOMINANTE)\n"
		"Texto para análise:\n" + texto_truncado
	)
	if normas_info:
		normas_txt = "\n\nNormas identificadas e status de vigência (consultadas na SEFAZ):\n"
		for n in normas_info:
			normas_txt += f"- {n['tipo']} {n['numero']}: Vigente={n['vigente']} | Status={n['status']}\n"
		prompt += normas_txt
	url = "https://api.openai.com/v1/chat/completions"
	headers = {
		"Authorization": f"Bearer {chave_api}",
		"Content-Type": "application/json"
	}
	data = {
		"model": modelo,
		"messages": [
			{"role": "system", "content": "Você é um especialista em documentos fiscais/contábeis."},
			{"role": "user", "content": prompt}
		],
		"max_tokens": 1024,
		"temperature": 0.2
	}
	response = requests.post(url, headers=headers, json=data, timeout=60)
	if response.status_code == 200:
		resposta = response.json()
		conteudo = resposta["choices"][0]["message"]["content"]
		tokens_total = resposta.get("usage", {}).get("total_tokens")
		print("\n===== RELATÓRIO CONSOLIDADO =====\n")
		print(conteudo)
		print(f"\nTotal de tokens usados: {tokens_total}")
		return conteudo
	else:
		raise Exception(f"OpenAI status {response.status_code}: {response.text}")
