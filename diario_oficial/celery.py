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
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

# Palavras-chave para busca de notícias relevantes
CONTABEIS_KEYWORDS = [
	"tributário", "fiscal", "trabalhista", "previdência", "contabilidade", "empresarial", "economia", "tecnologia", "carreira", "imposto", "reforma tributária", "INSS", "Simples Nacional", "NF-e", "IR", "Receita Federal"
]

# Tarefa Celery para buscar notícias do Contábeis
@app.task(name="buscar_noticias_contabeis")
def buscar_noticias_contabeis():
	from monitor.utils.contabeis_scraper import ContabeisScraper
	from monitor.models import Documento
	from django.utils import timezone
	scraper = ContabeisScraper()
	resultados = []
	salvos = 0
	for palavra in CONTABEIS_KEYWORDS:
		noticias = scraper.buscar_noticias(palavra_chave=palavra)
		for noticia in noticias:
			# Evita duplicidade pelo campo url_original
			if not noticia['url']:
				continue
			if Documento.objects.filter(url_original=noticia['url']).exists():
				continue
			detalhes = scraper.extrair_detalhes_noticia(noticia['url'])
			# Tenta extrair data de publicação (se possível)
			data_pub = timezone.now().date()
			if noticia['data']:
				try:
					# Tenta converter data tipo "11/08/2025 19:00" ou "Ontem 18:00"
					import dateparser
					data_pub_parsed = dateparser.parse(noticia['data'])
					if data_pub_parsed:
						data_pub = data_pub_parsed.date()
				except Exception:
					pass
			doc = Documento(
				titulo=noticia['titulo'] or detalhes.get('titulo') or noticia['resumo'][:100],
				data_publicacao=data_pub,
				url_original=noticia['url'],
				resumo=noticia['resumo'],
				texto_completo=detalhes.get('texto', ''),
				fonte_documento="Contabeis",
				tipo_documento="OUTRO"
			)
			doc.save()
			resultados.append(doc)
			salvos += 1
	print(f"Total de notícias capturadas: {len(resultados)} | Salvos: {salvos}")
	return salvos