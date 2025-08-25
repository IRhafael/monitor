# --- Inicialização de serviços ---
def inicializar_servicos():
	"""
	Inicializa a API da Receita Federal (WSL) e os serviços Celery worker e beat.
	Executa comandos necessários para subir os serviços em paralelo.
	"""
	import subprocess
	import sys
	import os

	# # Inicia API da Receita Federal via WSL (envia '1' automaticamente)
	# try:
	#     print("Iniciando API da Receita Federal via WSL (com entrada automática)...")
	#     subprocess.Popen([
	#         "wsl", "-d", "calculadora", "--cd", "/calculadora", "--exec", "bash", "-c", "echo 1 | bash start.sh"
	#     ])
	# except Exception as e:
	#     print(f"[ERRO] Falha ao iniciar API da Receita Federal: {e}")

	# Inicia Celery worker
	try:
		print("Iniciando Celery worker...")
		subprocess.Popen([
			sys.executable, "-m", "celery", "-A", "diario_oficial", "worker", "-l", "info"
		], cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
	except Exception as e:
		print(f"[ERRO] Falha ao iniciar Celery worker: {e}")

	# Inicia Celery beat
	try:
		print("Iniciando Celery beat...")
		subprocess.Popen([
			sys.executable, "-m", "celery", "-A", "diario_oficial", "beat", "-l", "info"
		], cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
	except Exception as e:
		print(f"[ERRO] Falha ao iniciar Celery beat: {e}")

	print("Serviços iniciados! Verifique os logs para detalhes.")

# Esqueleto para unificar extrações dos scrapers e API
# Apenas nomes das funções, sem lógica ainda

# --- Diário Oficial ---
def extrair_diario_oficial():
	"""Extrai documentos do Diário Oficial (DOEPI) usando DiarioOficialScraper."""
	from monitor.utils.diario_scraper import DiarioOficialScraper
	try:
		scraper = DiarioOficialScraper()
		documentos = scraper.coletar_e_salvar_documentos()
		# Retorna lista de objetos Documento ou dados relevantes
		return documentos
	except Exception as e:
		import logging
		logging.error(f"Erro na extração do Diário Oficial: {e}")
		return []

# --- SEFAZ ICMS ---
def extrair_sefaz_icms():
	"""Extrai documentos e normas ICMS do portal SEFAZ usando SEFAZICMSScraper."""
	from monitor.utils.sefaz_icms_scraper import SEFAZICMSScraper
	try:
		scraper = SEFAZICMSScraper()
		documentos = scraper.coletar_documentos()
		# Retorna lista de objetos Documento ou dados relevantes
		return documentos
	except Exception as e:
		import logging
		logging.error(f"Erro na extração do SEFAZ ICMS: {e}")
		return []

# --- SEFAZ Geral ---
def extrair_sefaz_geral():
	"""Extrai normas, decretos, portarias e ementas do portal SEFAZ usando SEFAZScraper."""
	from monitor.utils.sefaz_scraper import SEFAZScraper
	try:
		scraper = SEFAZScraper()
		documentos = scraper.coletar_documentos()
		# Retorna lista de objetos Documento ou dados relevantes
		return documentos
	except Exception as e:
		import logging
		logging.error(f"Erro na extração do SEFAZ Geral: {e}")
		return []

# --- API Regime Geral ---
def extrair_dados_api():
	"""Extrai dados normativos, classificações, alíquotas e situações tributárias da API usando coletar_dados_receita."""
	from monitor.utils.api import coletar_dados_receita
	try:
		resultado = coletar_dados_receita()
		# Retorna True/False ou dados relevantes
		return resultado
	except Exception as e:
		import logging
		logging.error(f"Erro na extração da API: {e}")
		return None

# --- Função principal unificadora ---
def extrair_todos_os_dados():
	"""Executa todas as extrações e retorna dados consolidados."""
	dados_diario = extrair_diario_oficial()
	dados_icms = extrair_sefaz_icms()
	dados_sefaz = extrair_sefaz_geral()
	dados_api = extrair_dados_api()
	# Retorno será ajustado depois
	return {
		"diario_oficial": dados_diario,
		"sefaz_icms": dados_icms,
		"sefaz_geral": dados_sefaz,
		"api": dados_api
	}
