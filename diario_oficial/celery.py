from __future__ import absolute_import
import os
from celery import Celery
from django.conf import settings

# Configurações específicas para Windows
os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')

app = Celery('diario_oficial')

# Usar 'solo' como pool no Windows
app.conf.worker_pool = 'solo'  # Ou 'threads' para múltiplas threads

# Desativar soft timeouts
app.conf.worker_disable_rate_limits = True
app.conf.worker_enable_remote_control = False

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(['monitor', 'monitor.utils'])

# Palavras-chave para busca de notícias relevantes
CONTABEIS_KEYWORDS = [
	"tributário", "fiscal", "trabalhista", "previdência", "contabilidade", "empresarial", "economia", "tecnologia", "carreira", "imposto", "reforma tributária", "INSS", "Simples Nacional", "NF-e", "IR", "Receita Federal",
	"auditoria", "balanço patrimonial", "DRE", "SPED", "EFD", "ICMS", "ISS", "IPI", "PIS", "COFINS", "CSLL", "lucro real", "lucro presumido", "MEI", "microempresa", "empresa de pequeno porte", "sociedade limitada", "sociedade anônima",
	"escrituração", "nota fiscal eletrônica", "substituição tributária", "regime tributário", "planejamento tributário", "compliance", "governança corporativa", "demonstrações financeiras", "conciliação contábil", "ativo", "passivo", "patrimônio líquido",
	"provisão", "depreciação", "amortização", "receita", "despesa", "resultado", "tributos", "obrigações acessórias", "GFIP", "RAIS", "DIRF", "DCTF", "eSocial", "FGTS", "CAGED", "cadastro nacional de pessoa jurídica", "CNPJ", "cadastro de contribuintes",
	"regulamentação contábil", "normas internacionais de contabilidade", "IFRS", "CPC", "CFC", "CRC", "contabilidade pública", "contabilidade gerencial", "contabilidade de custos", "contabilidade societária", "contabilidade tributária", "contabilidade ambiental",
	"contabilidade digital", "contabilidade consultiva", "contabilidade estratégica", "contabilidade financeira", "contabilidade rural", "contabilidade para startups", "contabilidade para ONGs", "contabilidade para terceiro setor", "contabilidade internacional",
	"recolhimento de impostos", "apuração de impostos", "declaração de impostos", "malha fiscal", "fiscalização tributária", "crédito tributário", "débito tributário", "parcelamento tributário", "refis", "cadastro fiscal", "cadastro tributário", "cadastro previdenciário"
]


@app.task(name="coleta_diaria_completa")
def coleta_diaria_completa():
	resultados = []
	# SEFAZ ICMS
	try:
		from monitor.utils.sefaz_icms_scraper import coletar_sefaz_icms
		resultados += coletar_sefaz_icms()
	except Exception as e:
		print(f"Erro SEFAZ ICMS: {e}")
	print(f"Total de documentos capturados: {len(resultados)}")
	# Aqui pode gerar boletim, enviar e-mail, etc.
	return len(resultados)

# Configuração do Celery Beat para rodar a coleta todo dia às 8h
from celery.schedules import crontab
app.conf.beat_schedule = {
	'coleta-diaria-completa': {
		'task': 'coleta_diaria_completa',
		'schedule': crontab(hour=8, minute=0),
	},
}