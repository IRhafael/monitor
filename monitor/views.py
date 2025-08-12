# monitor/views.py
import logging
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .forms import DocumentoUploadForm
from .models import Documento, NormaVigente
from monitor.utils.resumo_util import gerar_resumo_documentos
from monitor.utils.api import coletar_dados_receita
from django.utils import timezone
from datetime import timedelta

from django_celery_results.models import TaskResult

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from monitor.tasks import coletar_diario_oficial_task, processar_documentos_pendentes_task, verificar_normas_sefaz_task




logger = logging.getLogger(__name__)




# --- SISTEMA SIMPLIFICADO ---

@login_required
def home(request):
    """Página inicial simples, mostra os documentos coletados e do Diário Oficial."""
    documentos = Documento.objects.all().order_by('-id')
    # Busca documentos do Diário Oficial (se houver modelo específico)
    try:
        from .models import DocumentoDiarioOficial
        docs_diario = DocumentoDiarioOficial.objects.all().order_by('-id')
    except ImportError:
        docs_diario = []
    except Exception:
        docs_diario = []
    # Busca o último log da coleta da Receita Federal
    from monitor.models import LogExecucao
    log_api_receita = LogExecucao.objects.filter(tipo_execucao='COLETA_API_RECEITA').order_by('-data_fim').first()
    endpoints_status = {}
    try:
        from monitor.utils.api import ENDPOINTS
        todos_endpoints = list(ENDPOINTS.keys())
    except Exception:
        todos_endpoints = []
    log_status = {}
    if log_api_receita and log_api_receita.detalhes:
        log_status = log_api_receita.detalhes.get('endpoints_status', {})
    for ep in todos_endpoints:
        if ep in log_status:
            endpoints_status[ep] = log_status[ep]
        else:
            endpoints_status[ep] = 'Nenhum dado'
    resumo_documentos = gerar_resumo_documentos(list(documentos))
    resumo_docs_diario = gerar_resumo_documentos(list(docs_diario))
    return render(request, 'home.html', {
        'documentos': documentos,
        'docs_diario': docs_diario,
        'resumo_documentos': resumo_documentos,
        'resumo_docs_diario': resumo_docs_diario,
        'endpoints_status': endpoints_status,
        'log_api_receita': log_api_receita
    })

@login_required
def upload_documento(request):
    """Upload de documento simples."""
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = DocumentoUploadForm()
    return render(request, 'upload.html', {'form': form})

@login_required
def coletar_dados_receita_view(request):
    """Painel de consulta e atualização dos dados dos endpoints da Receita Federal."""
    dados_extraidos = {}
    erros_coleta = []
    sucesso = None
    # Sempre busca os dados da base para exibir
    from monitor.utils.api import ENDPOINTS, conectar_mysql, json_para_texto
    conn = conectar_mysql()
    cursor = conn.cursor()
    for nome in ENDPOINTS.keys():
        cursor.execute(f"SELECT data, dados FROM {nome} ORDER BY data DESC LIMIT 50")
        rows = cursor.fetchall()
        dados_extraidos[nome] = {}
        for row in rows:
            data, dados_json = row
            try:
                dados_dict = json.loads(dados_json)
                dados_extraidos[nome][str(data)] = json_para_texto(nome, dados_dict)
            except Exception as err:
                erros_coleta.append(f"Erro ao carregar dados de {nome} para data {data}: {err}")
    cursor.close()
    conn.close()
    # Se for POST, atualiza a base
    if request.method == 'POST':
        try:
            sucesso = coletar_dados_receita()
        except Exception as e:
            sucesso = False
            erros_coleta.append(str(e))
        # Após atualizar, recarrega os dados da base
        conn = conectar_mysql()
        cursor = conn.cursor()
        for nome in ENDPOINTS.keys():
            cursor.execute(f"SELECT data, dados FROM {nome} ORDER BY data DESC LIMIT 50")
            rows = cursor.fetchall()
            dados_extraidos[nome] = {}
            for row in rows:
                data, dados_json = row
                try:
                    dados_dict = json.loads(dados_json)
                    dados_extraidos[nome][str(data)] = json_para_texto(nome, dados_dict)
                except Exception as err:
                    erros_coleta.append(f"Erro ao carregar dados de {nome} para data {data}: {err}")
        cursor.close()
        conn.close()
    return render(request, 'coletar.html', {
        'sucesso': sucesso,
        'dados_extraidos': dados_extraidos,
        'erros_coleta': erros_coleta
    })


# --- VIEWS UTILITÁRIAS ---
from django.shortcuts import render

@login_required
def coletar_diario_oficial_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com DiarioOficialScraper
        resultado = {'msg': 'Coleta simulada.'}
    return render(request, 'coletar_diario.html', {'resultado': resultado})

@login_required
def processar_documentos_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com PDFProcessor
        resultado = {'msg': 'Processamento simulado.'}
    return render(request, 'processar_documentos.html', {'resultado': resultado})

@login_required
def verificar_normas_sefaz_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com IntegradorSEFAZ
        resultado = {'msg': 'Verificação simulada.'}
    return render(request, 'verificar_normas.html', {'resultado': resultado})

@login_required
def gerar_relatorio_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com ClaudeProcessor
        resultado = {'msg': 'Relatório simulado.'}
    return render(request, 'gerar_relatorio.html', {'resultado': resultado})

@login_required
def pipeline_manual_view(request):
    resultado = None
    if request.method == 'POST':
        # Aqui você pode integrar com pipeline_manual_completo
        resultado = {'msg': 'Pipeline manual simulado.'}
    return render(request, 'pipeline_manual.html', {'resultado': resultado})


from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from monitor.tasks import coletar_diario_oficial_task, processar_documentos_pendentes_task, verificar_normas_sefaz_task

# --- MONITORAMENTO DE TASKS CELERY ---
@login_required
def monitoramento_tasks(request):
    tasks = TaskResult.objects.order_by('-date_done')[:20]
    return render(request, 'monitoramento_tasks.html', {'tasks': tasks})


@csrf_exempt
@login_required
def painel_tasks(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        tipo = data.get('tipo')
        if tipo == 'coletar_diario':
            res = coletar_diario_oficial_task.delay()
            return JsonResponse({'status': 'Task disparada', 'result': f'Task ID: {res.id}'})
        elif tipo == 'processar_documentos':
            res = processar_documentos_pendentes_task.delay()
            return JsonResponse({'status': 'Task disparada', 'result': f'Task ID: {res.id}'})
        elif tipo == 'verificar_normas':
            res = verificar_normas_sefaz_task.delay()
            return JsonResponse({'status': 'Task disparada', 'result': f'Task ID: {res.id}'})
        elif tipo == 'gerar_relatorio':
            from monitor.tasks import gerar_relatorio_task
            res = gerar_relatorio_task.delay()
            return JsonResponse({'status': 'Task disparada', 'result': f'Task ID: {res.id}'})
        elif tipo == 'pipeline_manual':
            res = pipeline_manual_view.delay()
            return JsonResponse({'status': 'Task disparada', 'result': f'Task ID: {res.id}'})
        else:
            return JsonResponse({'status': 'Tipo inválido', 'result': ''})
    return render(request, 'painel_tasks.html')