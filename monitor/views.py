
from django.utils.safestring import mark_safe

# monitor/views.py
from datetime import timedelta, datetime, date # Certifique-se que date e datetime estão importados
import inspect
from itertools import count
from urllib import request
from django.db.models import F, ExpressionWrapper, Q
from django.forms import DurationField
from django.http import Http404, HttpResponse, FileResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from django.db import transaction
import os
import logging
from django.views.decorators.http import require_POST
# Importe a tarefa Celery correta do seu tasks.py refatorado
from .utils.tasks import (
    pipeline_coleta_e_processamento_automatica, # Nome da tarefa para pipeline padrão
    pipeline_manual_completo,                   # Nome da tarefa para pipeline com datas manuais
    coletar_diario_oficial_task,                # Para coleta isolada
    processar_documentos_pendentes_task,        # Para processar todos os pendentes
    verificar_normas_sefaz_task                 # Para verificar todas as normas SEFAZ
)
from .forms import DocumentoUploadForm #, PipelineManualForm # Você pode criar PipelineManualForm
from .models import Documento, NormaVigente, LogExecucao, RelatorioGerado
from .utils.sefaz_integracao import IntegradorSEFAZ
from .utils.relatorio import RelatorioAvancado
# A importação de verificar_normas_sefaz_task já está acima
import subprocess
from celery.app.control import Control # Removido app.control.inspect() daqui, movido para view se necessário
from diario_oficial.celery import app # Importa o app Celery
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Count, Sum # Count já estava, Sum adicionado
import calendar
import platform
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST # Para garantir que a exclusão seja via POST
from django.contrib import messages
from .models import RelatorioGerado
import os # Para remover o arquivo
from django.conf import settings # Para construir o caminho do arquivo


inspector = app.control.inspect()




logger = logging.getLogger(__name__)

"""
Dashboard principal: mostra cards de resumo, documentos recentes, relevantes, normas e status geral.
"""
@login_required
def dashboard(request):
    # Documentos relevantes (com normas relacionadas)
    documentos_relevantes = Documento.objects.filter(relevante_contabil=True).prefetch_related('normas_relacionadas').order_by('-data_publicacao')[:10]
    for doc in documentos_relevantes:
        # Garante que doc.normas_relacionadas seja uma lista para uso no template, sem sobrescrever o relacionamento ManyToMany
        doc.normas_relacionadas_list = list(doc.normas_relacionadas.all())
    # Documentos recentes
    documentos_recentes = Documento.objects.order_by('-data_publicacao')[:10]
    # Normas e documentos relevantes
    normas_docs = []
    normas_qs = NormaVigente.objects.prefetch_related('documentos').order_by('tipo', 'numero')
    for norma in normas_qs:
        docs = [doc for doc in norma.documentos.all() if getattr(doc, 'relevante_contabil', False)]
        if docs:
            normas_docs.append({'norma': norma, 'documentos': docs})
    # Normas já verificadas e normas pendentes
    normas_verificadas = NormaVigente.objects.filter(data_verificacao__isnull=False).order_by('-data_verificacao')[:10]
    normas_pendentes = NormaVigente.objects.filter(Q(data_verificacao__isnull=True) | Q(data_verificacao__lt=timezone.now() - timedelta(days=30))).order_by('-data_cadastro')[:10]
    # Totais para os cards
    total_documentos = Documento.objects.count()
    total_normas = NormaVigente.objects.count()
    # Última execução
    ultima_execucao = LogExecucao.objects.order_by('-data_inicio').first()
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context = {
        'documentos_relevantes': documentos_relevantes,
        'documentos_recentes': documentos_recentes,
        'normas_docs': normas_docs,
        'normas_verificadas': normas_verificadas,
        'normas_pendentes': normas_pendentes,
        'total_documentos': total_documentos,
        'total_normas': total_normas,
        'ultima_execucao': ultima_execucao,
        'messages': storage,
    }
    return render(request, 'dashboard.html', context)


"""
Lista documentos pendentes de processamento para análise manual.
"""

from django.core.paginator import Paginator

@login_required
def analise_documentos(request):
    status = request.GET.get('status', 'todos')
    documentos = Documento.objects.order_by('-data_publicacao')
    if status == 'pendentes':
        documentos = documentos.filter(processado=False)
    elif status == 'processados':
        documentos = documentos.filter(processado=True)
    # Paginação
    paginator = Paginator(documentos, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'documentos': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'status': status,
    }
    return render(request, 'processamento/analise.html', context)

"""
Lista documentos já processados.
"""

from django.core.paginator import Paginator

@login_required
def resultados_analise(request):
    relevancia = request.GET.get('relevancia', 'todos')
    documentos = Documento.objects.filter(processado=True).order_by('-data_publicacao')
    if relevancia == 'relevantes':
        documentos = documentos.filter(relevante_contabil=True)
    elif relevancia == 'irrelevantes':
        documentos = documentos.filter(relevante_contabil=False)
    # Paginação
    paginator = Paginator(documentos, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'documentos': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'relevancia': relevancia,
    }
    return render(request, 'processamento/resultados.html', context)

"""
Lista normas que precisam ser validadas/verificadas.
"""
@login_required
def validacao_normas(request):
    # Esta view pode mostrar todas as normas e seu status de validação/verificação
    normas = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) | 
        Q(data_verificacao__lt=timezone.now()-timedelta(days=30))
    ).order_by('tipo', 'numero').prefetch_related('documentos')
    return render(request, 'normas/validacao.html', {'normas': normas})

"""
Verifica uma norma específica via AJAX (usado em botões de verificação rápida).
"""
def verificar_norma_ajax(request, tipo, numero):
    import subprocess
    print(f"Verificando norma: tipo={tipo}, numero={numero}")  # DEBUG
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            # Abre um novo terminal cmd para mostrar o andamento da verificação
            # O comando abaixo assume que existe um comando customizado no manage.py chamado verificar_norma
            # Se não existir, crie um comando customizado Django para isso
            cmd = f'start cmd /K "{settings.BASE_DIR}\\venv311\\Scripts\\activate.bat && cd /d {settings.BASE_DIR} && python manage.py verificar_norma {tipo} {numero}"'
            subprocess.Popen(cmd, shell=True)

            # Executa a verificação normalmente (para manter o AJAX funcional)
            norma = NormaVigente.objects.get(tipo=tipo, numero=numero)
            integrador = IntegradorSEFAZ()
            resultado = integrador.buscar_norma_especifica(norma.tipo, norma.numero)

            status = 'VIGENTE' if resultado.get('vigente') else 'REVOGADA'
            norma.situacao = status
            norma.data_verificacao = timezone.now()
            norma.save()

            return JsonResponse({
                'success': True,
                'status': status,
                'data_verificacao': norma.data_verificacao.strftime('%d/%m/%Y %H:%M'),
                'terminal': 'Um novo terminal foi aberto para acompanhar o andamento da verificação.'
            })
        except NormaVigente.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Norma não encontrada.'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao verificar norma {tipo} {numero}: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Requisição inválida'}, status=400)


"""
View para iniciar pipeline automático de coleta e processamento (com status do Celery).
"""
@login_required
def executar_coleta_view(request):
    if request.method == 'POST':
        try:
            dias_retroativos = int(request.POST.get('days_back', 3))
            cmd = f'start cmd /K "{settings.BASE_DIR}\\venv311\\Scripts\\activate.bat && cd /d {settings.BASE_DIR} && python manage.py processar_pipeline {dias_retroativos}"'
            subprocess.Popen(cmd, shell=True)
            task_info = pipeline_coleta_e_processamento_automatica.delay(dias_retroativos_coleta=dias_retroativos)
            messages.success(request,
                f"Pipeline automático (coleta dos últimos {dias_retroativos} dias, processamento e verificação SEFAZ) iniciado. "
                f"ID da tarefa: {task_info.id}. Um novo terminal foi aberto para acompanhar o processamento.")
        except Exception as e:
            logger.error(f"Erro ao disparar pipeline automático: {e}", exc_info=True)
            messages.error(request, f"Erro ao iniciar pipeline: {str(e)}")
        return redirect('executar_coleta')

    # GET: Buscar status do Celery, última execução e tarefas recentes
    celery_worker_status = {'is_running': False, 'active_tasks': 0, 'queued_tasks': 0, 'workers': 0}
    recent_tasks = []
    try:
        inspector = app.control.inspect(timeout=1)
        active = inspector.active() or {}
        scheduled = inspector.scheduled() or {}
        ping_result = inspector.ping() or {}
        celery_worker_status['is_running'] = bool(ping_result)
        celery_worker_status['workers'] = len(ping_result.keys()) if ping_result else 0
        celery_worker_status['active_tasks'] = sum(len(tasks) for tasks in active.values()) if active else 0
        celery_worker_status['queued_tasks'] = sum(len(tasks) for tasks in scheduled.values()) if scheduled else 0
        # Monta lista de tarefas recentes
        for worker, tasks in active.items():
            for t in tasks:
                recent_tasks.append({
                    'id': t.get('id', ''),
                    'name': t.get('name', ''),
                    'status': t.get('status', 'STARTED'),
                    'received': t.get('time_start', None),
                    'status_badge': 'bg-info',
                    'result': t.get('result', {}),
                })
        for worker, tasks in scheduled.items():
            for t in tasks:
                recent_tasks.append({
                    'id': t['request'].get('id', ''),
                    'name': t['request'].get('name', ''),
                    'status': 'SCHEDULED',
                    'received': t.get('eta', None),
                    'status_badge': 'bg-warning',
                    'result': {},
                })
    except Exception as e:
        logger.warning(f"Não foi possível obter status do Celery em executar_coleta_view: {e}")

    # Última execução de coleta
    ultima_execucao_coleta = LogExecucao.objects.filter(tipo_execucao='COLETA').order_by('-data_inicio').first()
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context = {
        'celery_status': celery_worker_status,
        'ultima_execucao_coleta': ultima_execucao_coleta,
        'recent_tasks': recent_tasks,
        'messages': storage,
    }
    return render(request, 'executar_coleta.html', context)




"""
Upload manual de documento PDF para processamento.
"""
@login_required
def upload_documento(request):
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save(commit=False)
            documento.processado = False  # Marca como não processado inicialmente
            documento.relevante_contabil = False # Definir como false por padrão
            documento.save()
            messages.success(request, 'Documento enviado com sucesso! Será processado em breve.')
            
            # Opcional: Disparar a tarefa de processamento para incluir o novo documento
            processar_documentos_pendentes_task.delay()

            return redirect('analise_documentos')
    else:
        form = DocumentoUploadForm()
    return render(request, 'documento/upload.html', {'form': form})



"""
Exibe detalhes de um documento específico.
"""
@login_required
def detalhe_documento(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    # Verifica se o documento tem resumo
    tem_resumo = bool(getattr(documento, 'resumo', None))
    # Caminho do arquivo PDF para visualização
    caminho_pdf = documento.arquivo.url if hasattr(documento, 'arquivo') and documento.arquivo else None
    context = {
        'documento': documento,
        'tem_resumo': tem_resumo,
        'caminho_pdf': caminho_pdf
    }
    return render(request, 'documentos/detalhe.html', context)



"""
Edita campos de um documento (relevância, etc).
"""
@login_required
def editar_documento(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    if request.method == 'POST':
        documento.relevante_contabil = request.POST.get('relevante_contabil') == 'on'
        # Adicione mais campos para edição conforme seu formulário
        documento.save()
        messages.success(request, 'Documento atualizado com sucesso.')
        return redirect('detalhe_documento', pk=documento.pk)
    # Se for um GET, renderiza o formulário de edição
    return render(request, 'documento/editar.html', {'documento': documento}) # Ou um form específico

"""
Gera relatório contábil avançado.
"""
@login_required
def gerar_relatorio_contabil_view(request):
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        formato = request.POST.get('formato')
        data_inicio = request.POST.get('data_inicio')
        data_fim = request.POST.get('data_fim')
        norma_tipo = request.POST.getlist('norma_tipo')
        status = request.POST.get('status')
        form_data = request.POST.copy()
        # Validação básica
        if not tipo or not formato:
            messages.error(request, 'Preencha todos os campos obrigatórios.')
            return render(request, 'relatorios/gerar_relatorio.html', {'form_data': form_data})
        if data_inicio and data_fim and data_inicio > data_fim:
            messages.error(request, 'A data inicial deve ser menor que a final.')
            return render(request, 'relatorios/gerar_relatorio.html', {'form_data': form_data})
        try:
            # Chame a função de geração de relatório, passando todos os parâmetros
            # relatorio = RelatorioAvancado.gerar(tipo, formato, data_inicio, data_fim, norma_tipo, status)
            messages.success(request, 'Relatório gerado com sucesso!')
            return redirect('dashboard_relatorios')
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {e}", exc_info=True)
            messages.error(request, f'Erro ao gerar relatório: {e}')
            return render(request, 'relatorios/gerar_relatorio.html', {'form_data': form_data})
    return render(request, 'relatorios/gerar_relatorio.html')

"""
Lista todos os relatórios gerados.
"""
@login_required
def dashboard_relatorios(request):
    # Filtros avançados
    tipo = request.GET.get('tipo', '')
    data_inicio = request.GET.get('data_inicio', '')
    data_fim = request.GET.get('data_fim', '')
    relatorios = RelatorioGerado.objects.all()
    if tipo:
        relatorios = relatorios.filter(tipo=tipo)
    if data_inicio:
        try:
            data = datetime.strptime(data_inicio, '%Y-%m-%d').date()
            relatorios = relatorios.filter(data_criacao__gte=data)
        except ValueError:
            pass
    if data_fim:
        try:
            data = datetime.strptime(data_fim, '%Y-%m-%d').date()
            relatorios = relatorios.filter(data_criacao__lte=data)
        except ValueError:
            pass
    relatorios = relatorios.order_by('-data_criacao')
    # Paginação
    from django.core.paginator import Paginator
    paginator = Paginator(relatorios, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    # Caminho para download
    for relatorio in page_obj:
        relatorio.caminho_download = relatorio.caminho_arquivo.url if hasattr(relatorio, 'caminho_arquivo') and relatorio.caminho_arquivo else None
    context = {
        'relatorios': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'tipo': tipo,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
    }
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context['messages'] = storage
    return render(request, 'relatorios/listar_relatorios.html', context)


"""
Permite download seguro de um relatório gerado.
"""
@login_required
def download_relatorio(request, pk):
    relatorio = get_object_or_404(RelatorioGerado, pk=pk)
    # Garante que o caminho seja seguro para evitar Directory Traversal
    caminho_arquivo = relatorio.caminho_arquivo.path if hasattr(relatorio.caminho_arquivo, 'path') else None
    if not caminho_arquivo or not os.path.exists(caminho_arquivo) or not os.path.isfile(caminho_arquivo):
        raise Http404("Arquivo não encontrado.")

    abs_media_root = os.path.abspath(settings.MEDIA_ROOT)
    abs_file_path = os.path.abspath(caminho_arquivo)
    if not abs_file_path.startswith(abs_media_root):
        raise Http404("Acesso negado: Caminho de arquivo inválido.")

    # Tenta identificar o tipo de arquivo para o Content-Type
    import mimetypes
    content_type, _ = mimetypes.guess_type(caminho_arquivo)
    if not content_type:
        content_type = 'application/octet-stream'

    with open(caminho_arquivo, 'rb') as fh:
        response = HttpResponse(fh.read(), content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(caminho_arquivo)}"'
        return response

# Exemplo de uma view para exibir logs de execução
"""
Exibe logs de execução do sistema (coleta, processamento, etc).
"""
@login_required
def logs_execucao(request):
    status_filtro = request.GET.get('status', '')
    logs_qs = LogExecucao.objects.all().order_by('-data_inicio')
    if status_filtro:
        logs_qs = logs_qs.filter(status=status_filtro)
    # Paginação
    from django.core.paginator import Paginator
    paginator = Paginator(logs_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context = {
        'logs': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'status_filtro': status_filtro,
        'messages': storage,
    }
    return render(request, 'monitor/logs_execucao.html', context)


"""
Lista normas que estão com status 'REVOGADA'.
"""
@login_required
def normas_revogadas(request):
    normas = NormaVigente.objects.filter(situacao='REVOGADA').order_by('-data_verificacao', '-data_cadastro').prefetch_related('documentos')
    normas_docs = []
    for norma in normas:
        documentos_origem = norma.documentos.all()
        normas_docs.append({
            'norma': norma,
            'documentos': documentos_origem
        })
    context = {
        'normas_docs': normas_docs
    }
    return render(request, 'normas/normas_revogadas.html', context)

"""
Exibe histórico de verificações de uma norma específica.
"""
def norma_historico(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    documentos = norma.documentos.all()
    # Buscar histórico de verificações se existir (LogExecucao)
    historico = LogExecucao.objects.filter(
        tipo_execucao='VERIFICACAO_SEFAZ',
        detalhes__contains={'norma_id': norma.id}
    ).order_by('-data_inicio')
    return render(request, 'normas/historico.html', {
        'norma': norma,
        'documentos': documentos,
        'historico': historico
    })



# Uma view para detalhe de uma norma específica
"""
Exibe detalhes de uma norma específica.
"""
@login_required
def detalhe_norma(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    # Busca documentos de origem e parágrafo (assumindo campo paragrafo na relação)
    documentos_origem = norma.documentos.all()
    documentos_info = []
    for doc in documentos_origem:
        # Tenta buscar o parágrafo de origem (assumindo campo ManyToMany com through ou atributo)
        paragrafo = None
        if hasattr(doc, 'paragrafo_origem'):
            paragrafo = doc.paragrafo_origem
        elif hasattr(doc, 'paragrafo'):
            paragrafo = doc.paragrafo
        documentos_info.append({
            'documento': doc,
            'paragrafo': paragrafo
        })
    context = {
        'norma': norma,
        'documentos_info': documentos_info,
        'status': norma.situacao
    }
    return render(request, 'normas/detalhe_norma.html', context)

# Exemplo de view para marcar um documento como irrelevante (se for uma ação manual)
"""
Marca um documento como irrelevante manualmente.
"""
@login_required
def marcar_documento_irrelevante(request, pk):
    if request.method == 'POST':
        documento = get_object_or_404(Documento, pk=pk)
        documento.relevante_contabil = False
        documento.processado = True # Marcar como processado para não ser reprocessado
        documento.save()
        messages.info(request, f"Documento '{documento.titulo}' marcado como irrelevante.")
        return redirect('analise_documentos') # Ou para onde for mais adequado
    return Http404("Método não permitido.")


"""
Agendar reprocessamento de um documento específico.
"""
@login_required
def reprocessar_documento(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    if request.method == 'POST':
        try:

            documento.processado = False
            documento.save()
            
            processamento_task_info = processar_documentos_pendentes_task.delay()
            
            messages.success(request, 
                f"Documento '{documento.titulo}' (ID: {pk}) agendado para reprocessamento. "
                f"ID da tarefa: {processamento_task_info.id}"
            )
        except Exception as e:
            logger.error(f"Erro ao agendar reprocessamento do documento {documento.pk}: {e}", exc_info=True)
            messages.error(request, f"Erro ao agendar reprocessamento: {str(e)}")
        
        return redirect('detalhe_documento', pk=pk) # Redireciona de volta para a página de detalhes do documento
    
    # Se a requisição não for POST, redireciona ou mostra uma mensagem de erro
    messages.error(request, "Método não permitido para reprocessamento direto.")
    return redirect('detalhe_documento', pk=pk)


# Exemplo de uma view para exibir logs de execução
"""
Exibe logs de execução (duplicado, pode remover se já existe acima).
"""
@login_required
def logs_execucao(request):
    logs = LogExecucao.objects.all().order_by('-data_inicio')
    context = {
        'logs': logs
    }
    return render(request, 'logs_execucao.html', context)


"""
Lista normas revogadas (duplicado, pode remover se já existe acima).
"""
@login_required
def normas_revogadas(request):
    normas = NormaVigente.objects.filter(situacao='REVOGADA').order_by('-data_verificacao', '-data_cadastro')
    context = {
        'normas': normas
    }
    return render(request, 'normas/normas_revogadas.html', context)

"""
Adiciona norma manualmente (duplicado, pode remover se já existe acima).
"""
@login_required
def adicionar_norma(request):
    # from .forms import NormaVigenteForm # Descomente e crie este formulário
    
    if request.method == 'POST':
        messages.error(request, "Funcionalidade de adicionar norma manual não implementada ainda.")
        return redirect('validacao_normas') # Ou renderiza o formulário novamente com erros
    return render(request, 'normas/adicionar_norma.html', {}) # Criar template 'adicionar_norma.html'



# Exemplo de view para marcar um documento como irrelevante (se for uma ação manual)
"""
Marca documento como irrelevante (duplicado, pode remover se já existe acima).
"""
@login_required
def marcar_documento_irrelevante(request, pk):
    if request.method == 'POST':
        documento = get_object_or_404(Documento, pk=pk)
        documento.relevante_contabil = False
        documento.processado = True # Marcar como processado para não ser reprocessado desnecessariamente
        documento.save()
        messages.info(request, f"Documento '{documento.titulo}' marcado como irrelevante.")
        return redirect('analise_documentos') # Ou para onde for mais adequado após a ação
    return Http404("Método não permitido. Esta ação requer um POST.")



"""
Exibe painel de controle do Celery.
"""
@login_required
def celery_control(request):
    # Obtém status dos workers
    try:
        inspector = app.control.inspect(timeout=1)
        active = inspector.active() or {}
        scheduled = inspector.scheduled() or {}
        ping_result = inspector.ping() or {}
        is_running = bool(ping_result)
        workers = list(ping_result.keys()) if is_running else []
        active_tasks = sum(len(tasks) for tasks in active.values()) if active else 0
        queued_tasks = sum(len(tasks) for tasks in scheduled.values()) if scheduled else 0
    except Exception as e:
        is_running = False
        workers = []
        active_tasks = 0
        queued_tasks = 0
        ping_result = None
    # Lista de tarefas detalhadas
    tasks = []
    if is_running:
        for worker, worker_tasks in active.items():
            for t in worker_tasks:
                tasks.append({
                    'id': t.get('id', ''),
                    'name': t.get('name', ''),
                    'status': t.get('status', 'STARTED'),
                    'received': t.get('time_start', None),
                    'worker': worker,
                })
        for worker, worker_tasks in scheduled.items():
            for t in worker_tasks:
                tasks.append({
                    'id': t['request'].get('id', ''),
                    'name': t['request'].get('name', ''),
                    'status': 'SCHEDULED',
                    'received': t.get('eta', None),
                    'worker': worker,
                })
    if request.method == 'POST':
        try:
            dias_retroativos = int(request.POST.get('days_back', 3))
            cmd = f'start cmd /K "{settings.BASE_DIR}\\venv311\\Scripts\\activate.bat && cd /d {settings.BASE_DIR} && python manage.py processar_pipeline {dias_retroativos}"'
            subprocess.Popen(cmd, shell=True)
            task_info = pipeline_coleta_e_processamento_automatica.delay(dias_retroativos_coleta=dias_retroativos)
            messages.success(request,
                f"Pipeline automático (coleta dos últimos {dias_retroativos} dias, processamento e verificação SEFAZ) iniciado. "
                f"ID da tarefa: {task_info.id}. Um novo terminal foi aberto para acompanhar o processamento.")
        except Exception as e:
            logger.error(f"Erro ao disparar pipeline automático: {e}", exc_info=True)
            messages.error(request, f"Erro ao iniciar pipeline: {str(e)}")
        return redirect('executar_coleta')

    # GET: Buscar status do Celery, última execução e tarefas recentes
    celery_worker_status = {'is_running': False, 'active_tasks': 0, 'queued_tasks': 0, 'workers': 0}
    recent_tasks = []
    try:
        inspector = app.control.inspect(timeout=1)
        active = inspector.active() or {}
        scheduled = inspector.scheduled() or {}
        ping_result = inspector.ping() or {}
        celery_worker_status['is_running'] = bool(ping_result)
        celery_worker_status['workers'] = len(ping_result.keys()) if ping_result else 0
        celery_worker_status['active_tasks'] = sum(len(tasks) for tasks in active.values()) if active else 0
        celery_worker_status['queued_tasks'] = sum(len(tasks) for tasks in scheduled.values()) if scheduled else 0
        # Monta lista de tarefas recentes
        for worker, tasks in active.items():
            for t in tasks:
                recent_tasks.append({
                    'id': t.get('id', ''),
                    'name': t.get('name', ''),
                    'status': t.get('status', 'STARTED'),
                    'received': t.get('time_start', None),
                    'status_badge': 'bg-info',
                    'result': t.get('result', {}),
                })
        for worker, tasks in scheduled.items():
            for t in tasks:
                recent_tasks.append({
                    'id': t['request'].get('id', ''),
                    'name': t['request'].get('name', ''),
                    'status': 'SCHEDULED',
                    'received': t.get('eta', None),
                    'status_badge': 'bg-warning',
                    'result': {},
                })
    except Exception as e:
        logger.warning(f"Não foi possível obter status do Celery em executar_coleta_view: {e}")

    # Última execução de coleta
    ultima_execucao_coleta = LogExecucao.objects.filter(tipo_execucao='COLETA').order_by('-data_inicio').first()
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context = {
        'celery_status': celery_worker_status,
        'ultima_execucao_coleta': ultima_execucao_coleta,
        'recent_tasks': recent_tasks,
        'messages': storage,
    }
    return render(request, 'executar_coleta.html', context)



"""
Inicia um worker Celery via comando no terminal (Windows).
"""
@login_required
@require_POST
def start_celery_worker(request):
    try:
        # Usar settings.BASE_DIR que é a raiz do projeto Django (onde manage.py está)
        project_root = str(settings.BASE_DIR)
        logger.info(f"Project root: {project_root}")

        # Confirme este caminho para o seu ambiente virtual
        venv_scripts_path = os.path.join(project_root, 'venv311', 'Scripts')
        venv_activate_path = os.path.join(venv_scripts_path, 'activate.bat')
        celery_executable_path = os.path.join(venv_scripts_path, 'celery.exe') # Caminho explícito

        logger.info(f"Venv activate path: {venv_activate_path}")
        logger.info(f"Celery executable path: {celery_executable_path}")

        if not os.path.exists(venv_activate_path):
            logger.error(f"Script de ativação do Venv não encontrado: {venv_activate_path}")
            return JsonResponse({'status': 'error', 'message': f'Venv activate script not found: {venv_activate_path}'}, status=500)
        if not os.path.exists(celery_executable_path):
            logger.error(f"Executável do Celery não encontrado: {celery_executable_path}")
            return JsonResponse({'status': 'error', 'message': f'Celery executable not found: {celery_executable_path}'}, status=500)

   
        celery_command_args = [celery_executable_path, '-A', 'diario_oficial', 'worker', '--loglevel=info', '-P', 'solo']
        celery_command_str = " ".join(f'"{arg}"' if " " in arg else arg for arg in celery_command_args) # Aspas em args com espaço

        if platform.system() == "Windows":

            full_command = f'start cmd /K "call "{venv_activate_path}" && cd /d "{project_root}" && {celery_command_str}"'
            logger.info(f"Tentando iniciar Celery no Windows com o comando: {full_command}")

            subprocess.Popen(full_command, shell=True, cwd=project_root)

            message = 'Tentativa de iniciar o worker Celery em um novo terminal. Verifique o novo terminal e os logs do Django.'

        # ... (resto da lógica para Linux/macOS, se aplicável) ...
        elif platform.system() == "Linux" or platform.system() == "Darwin":
            logger.warning("Iniciar worker Celery automaticamente via botão em um novo terminal no Linux/macOS é complexo. Recomenda-se iniciar manualmente.")
            message = 'Para Linux/macOS, inicie o worker manualmente em um novo terminal.'
            return JsonResponse({'status': 'info', 'message': message})
        else:
            logger.warning(f"Sistema operacional {platform.system()} não suportado para iniciar worker automaticamente.")
            message = f'Sistema operacional {platform.system()} não suportado para esta ação.'
            return JsonResponse({'status': 'error', 'message': message}, status=400)

        return JsonResponse({'status': 'success', 'message': message})
    except Exception as e:
        logger.error(f"Erro ao tentar iniciar worker Celery: {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)



"""
Encerra os workers Celery via comando broadcast.
"""
@login_required
@require_POST # Garante que esta ação seja via POST
def stop_celery_worker(request):
    try:
        logger.info("Recebida solicitação para parar workers Celery...")
        # Aumentar um pouco o timeout para dar mais chance de resposta
        inspector = app.control.inspect(timeout=2.0) 
        
        ping_result = inspector.ping() # Tenta pingar os workers

        if ping_result: # Se ping_result não for None e não for um dict vazio
            workers_responsive = list(ping_result.keys()) # Pega os nomes dos workers que responderam
            if workers_responsive:
                logger.info(f"Workers respondendo ao ping: {workers_responsive}. Enviando comando de shutdown...")
                app.control.broadcast('shutdown', destination=workers_responsive)
                messages.success(request, f'Comando de shutdown enviado para {len(workers_responsive)} worker(s). Verifique os terminais dos workers.')
                return JsonResponse({'status': 'success', 'message': f'Comando de shutdown enviado para {len(workers_responsive)} worker(s).'})
            else:
                logger.warning("Ping aos workers teve resposta, mas não listou workers. Não foi possível enviar shutdown.")
                messages.warning(request, "Workers Celery parecem estar online, mas não foi possível identificá-los para parada.")
                return JsonResponse({'status': 'warning', 'message': 'Workers Celery parecem estar online, mas não foi possível identificá-los para parada.'})
        else:
            logger.warning("Nenhum worker Celery respondeu ao ping. O comando de shutdown não foi enviado. Verifique se os workers estão rodando e conectados ao broker.")
            messages.warning(request, "Nenhum worker Celery ativo/responsivo encontrado para parar.")
            return JsonResponse({'status': 'warning', 'message': 'Nenhum worker Celery ativo/responsivo encontrado para parar.'})
    except ConnectionRefusedError:
         logger.error("Não foi possível conectar ao broker Celery (Redis) ao tentar parar workers. Verifique se o Redis está em execução.", exc_info=True)
         messages.error(request, 'Falha ao conectar ao broker Celery (Redis).')
         return JsonResponse({'status': 'error', 'message': 'Falha ao conectar ao broker Celery (Redis).'}, status=500)
    except Exception as e:
        logger.error(f"Erro excepcional ao tentar parar workers Celery: {e}", exc_info=True)
        messages.error(request, f'Erro ao comunicar com workers: {str(e)}')
        return JsonResponse({'status': 'error', 'message': f'Erro ao comunicar com workers: {str(e)}'}, status=500)

"""
Retorna lista de tarefas Celery (ativas e agendadas).
"""
@login_required
def get_celery_tasks(request):
    try:
        i = app.control.inspect(timeout=1) # Adicione timeout
        active = i.active() or {}
        scheduled = i.scheduled() or {}
        tasks = [] #
        for worker, worker_tasks in active.items(): #
            tasks.extend([{ #
                'id': t['id'], #
                'name': t['name'], #
                'status': 'STARTED', #
                'received': t['time_start'], #
                'args': t['args'], #
                'worker': worker #
            } for t in worker_tasks]) #

        for worker, worker_tasks in scheduled.items(): #
            tasks.extend([{ #
                'id': t['request']['id'], #
                'name': t['request']['name'], #
                'status': 'SCHEDULED', #
                'eta': t['eta'], #
                'args': t['request']['args'], #
                'worker': worker #
            } for t in worker_tasks]) #

        return JsonResponse({'tasks': tasks})
    except Exception as e:
        logger.error(f"Erro ao obter lista de tarefas Celery: {e}", exc_info=True) # Adicionado log
        return JsonResponse({'error': str(e), 'tasks': []}, status=500)
"""
Dispara verificação em lote de normas via Celery.
"""
@login_required
def verify_normas_batch(request):
    if request.method == 'POST':
        # Filtra apenas IDs numéricos
        norma_ids = [int(i) for i in request.POST.getlist('ids[]') if str(i).isdigit()]
        normas = NormaVigente.objects.filter(id__in=norma_ids)
        
        # Dispara tarefa assíncrona para verificar em lote
        task = verificar_normas_sefaz_task.delay(
            norma_ids=norma_ids
        )
        
        return JsonResponse({
            'status': 'success',
            'task_id': task.id,
            'count': len(norma_ids)
        })
    
    return JsonResponse({'status': 'error'}, status=405)

"""
Dispara processamento em lote de documentos via Celery.
"""
@require_POST
@login_required
def process_document_batch(request):
    try:
        # Filtra apenas IDs numéricos
        document_ids = [int(i) for i in request.POST.getlist('ids[]') if str(i).isdigit()]
        # Dispara tarefa assíncrona para processar os documentos
        task = processar_documentos_pendentes_task.delay(document_ids=document_ids)
        return JsonResponse({'success': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)





"""
Retorna status dos workers Celery (detalhado, para dashboard ou AJAX).
"""
@login_required
def celery_status(request): # Esta é chamada pela view celery_status_view
    try:
        # A linha abaixo foi a que eu sugeri na refatoração de executar_coleta_view
        # 'app' deve ser a sua instância Celery importada de diario_oficial.celery
        i = app.control.inspect(timeout=1) # Adicione um timeout aqui também!
        active_tasks = i.active()
        scheduled_tasks = i.scheduled() # Nota: i.scheduled() retorna tarefas agendadas pelo Celery, não necessariamente as da fila do broker.

        is_running = bool(i.ping())

        return JsonResponse({
            'is_running': is_running,
            # Contar corretamente as tarefas ativas e na fila
            'active_tasks': sum(len(tasks) for tasks in active_tasks.values()) if active_tasks else 0,
            'queued_tasks': sum(len(tasks) for tasks in scheduled_tasks.values()) if scheduled_tasks else 0, # Pode não ser a "fila" real do broker
             # Adicionar contagem de workers
            'workers': len(i.ping().keys()) if is_running and i.ping() else 0
        })
    except Exception as e:
        logger.error(f"Erro ao obter status do Celery: {e}", exc_info=True) # Adicionado log
        return JsonResponse({'error': str(e), 'is_running': False}, status=500) # Retorna um status claro de erro



"""
Exibe preview de um documento (visualização rápida).
"""
@login_required
def document_preview(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    context = {'documento': documento}
    return render(request, 'documentos/preview.html', context)

"""
Exibe histórico de verificações de uma norma (para auditoria).
"""
@login_required
def norma_history(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    verificacoes = LogExecucao.objects.filter(
        tipo_execucao='VERIFICACAO_SEFAZ',
        detalhes__contains={'norma_id': norma.id}
    ).order_by('-data_inicio')
    context = {'norma': norma, 'verificacoes': verificacoes}
    return render(request, 'normas/history.html', context)



"""
ListView para exibir relatórios gerados, com filtros e paginação.
"""
class RelatorioListView(LoginRequiredMixin, ListView):
    model = RelatorioGerado
    template_name = 'relatorios/listar_relatorios.html'
    context_object_name = 'relatorios'
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros
        tipo = self.request.GET.get('tipo')
        data_inicio = self.request.GET.get('data_inicio')
        data_fim = self.request.GET.get('data_fim')
        
        if tipo:
            queryset = queryset.filter(tipo=tipo)
        if data_inicio:
            try:
                data = datetime.strptime(data_inicio, '%Y-%m-%d').date()
                queryset = queryset.filter(data_criacao__gte=data)
            except ValueError:
                pass
        if data_fim:
            try:
                data = datetime.strptime(data_fim, '%Y-%m-%d').date()
                queryset = queryset.filter(data_criacao__lte=data)
            except ValueError:
                pass
        
        return queryset.order_by('-data_criacao')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tipo'] = self.request.GET.get('tipo', '')
        context['data_inicio'] = self.request.GET.get('data_inicio', '')
        context['data_fim'] = self.request.GET.get('data_fim', '')
        storage = messages.get_messages(self.request)
        context['messages'] = storage
        return context
    


"""
Dashboard de relatórios: estatísticas, gráficos e totais.
"""
class RelatorioDashboardView(TemplateView):
    template_name = 'relatorios/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Filtros opcionais
        ano = self.request.GET.get('ano')
        tipo_filtro = self.request.GET.get('tipo')
        relatorios = RelatorioGerado.objects.all()
        if ano:
            relatorios = relatorios.filter(data_criacao__year=ano)
        if tipo_filtro:
            relatorios = relatorios.filter(tipo=tipo_filtro)
        # Estatísticas
        context['total_relatorios'] = relatorios.count()
        context['total_contabil'] = relatorios.filter(tipo='CONTABIL').count()
        context['total_downloads'] = relatorios.aggregate(total=Sum('downloads'))['total'] or 0
        # Relatórios deste mês
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
        context['relatorios_mes'] = relatorios.filter(data_criacao__gte=month_start).count()
        # Gráfico por tipo
        tipos = relatorios.values('tipo').annotate(total=Count('id')).order_by('-total')
        context['tipos_labels'] = [t['tipo'] for t in tipos]
        context['tipos_data'] = [t['total'] for t in tipos]
        # Gráfico mensal
        meses = []
        data = []
        hoje = timezone.now()
        for i in range(11, -1, -1):
            ref = hoje - timedelta(days=30*i)
            mes_label = ref.strftime('%b/%Y')
            inicio_mes = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if inicio_mes.month == 12:
                fim_mes = inicio_mes.replace(year=inicio_mes.year+1, month=1)
            else:
                fim_mes = inicio_mes.replace(month=inicio_mes.month+1)
            count_mes = relatorios.filter(data_criacao__gte=inicio_mes, data_criacao__lt=fim_mes).count()
            meses.append(mes_label)
            data.append(count_mes)
        context['meses_labels'] = meses
        context['meses_data'] = data
        # Filtros para o template
        context['ano'] = ano
        context['tipo_filtro'] = tipo_filtro
        # Lista de anos disponíveis para filtro
        anos_disponiveis = RelatorioGerado.objects.dates('data_criacao', 'year')
        context['anos_disponiveis'] = [a.year for a in anos_disponiveis]
        # Lista de tipos disponíveis para filtro
        context['tipos_disponiveis'] = RelatorioGerado.objects.values_list('tipo', flat=True).distinct()
        return context
    

"""
Inicia apenas a coleta dos diários oficiais (sem processamento).
"""
@login_required
@require_POST
def iniciar_apenas_coleta_view(request):
    try:
        dias_retroativos = int(request.POST.get('dias_retroativos_apenas_coleta', 3))
        
        task = coletar_diario_oficial_task.delay(dias_retroativos=dias_retroativos)
        messages.success(request, f"Tarefa de coleta de Diários Oficiais (últimos {dias_retroativos} dias) iniciada. ID da Tarefa: {task.id}")
    except Exception as e:
        logger.error(f"Erro ao iniciar tarefa de coleta isolada: {e}", exc_info=True)
        messages.error(request, f"Erro ao iniciar tarefa de coleta: {str(e)}")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

"""
Dispara processamento de todos os documentos pendentes.
"""
@login_required
@require_POST
def processar_todos_pendentes_view(request):
    try:
        task = processar_documentos_pendentes_task.delay() 
        messages.success(request, f"Tarefa para processar todos os documentos pendentes foi iniciada. ID: {task.id}")
    except Exception as e:
        logger.error(f"Erro ao iniciar processamento de todos pendentes: {e}", exc_info=True)
        messages.error(request, f"Erro ao iniciar processamento de todos os pendentes: {str(e)}")
    return redirect('analise_documentos')

"""
Dispara verificação de todas as normas SEFAZ pendentes/desatualizadas.
"""
@login_required
@require_POST # Esta view já existe e lida com POST para verificar todas as normas
def verificar_normas_view(request): # Renomeada de verificar_todas_normas_sefaz_view para reusar a existente
    # A lógica original do POST já dispara a tarefa para todas as normas pendentes
    if request.method == 'POST':
        try:
            verificacao_task_info = verificar_normas_sefaz_task.delay() # Sem norma_ids, verifica todas as necessárias
            logger.info(f"Tarefa de verificação de todas as normas SEFAZ (pendentes/desatualizadas) disparada com ID: {verificacao_task_info.id}")
            messages.success(request, "Verificação de todas as normas SEFAZ (pendentes/desatualizadas) iniciada em segundo plano.")
        except Exception as e:
            logger.error(f"Erro ao disparar tarefa de verificação SEFAZ: {e}", exc_info=True)
            messages.error(request, f"Erro ao iniciar tarefa de verificação SEFAZ: {str(e)}")
        return redirect('dashboard_vigencia') 
    
    # A lógica GET original para mostrar informações sobre a última execução pode ser mantida
    ultima_execucao = LogExecucao.objects.filter(tipo_execucao='VERIFICACAO_SEFAZ').order_by('-data_inicio').first()
    normas_para_verificar_count = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) |
        Q(data_verificacao__lt=timezone.now() - timedelta(days=30))
    ).count()

    context = {
        'ultima_execucao': ultima_execucao,
        'normas_para_verificar_count': normas_para_verificar_count,
    }
    return render(request, 'monitor/normas/verificar_normas.html', context) # Seu template existente


"""
Inicia pipeline manual completo (coleta, processamento e verificação por datas).
"""
@login_required
def iniciar_pipeline_completo_manual_view(request): # Renomeada de iniciar_pipeline_manual_view
    # from .forms import PipelineManualForm # Se você criar um form
    if request.method == 'POST':
        data_inicio_pipeline = request.POST.get('data_inicio_pipeline', '')
        data_fim_pipeline = request.POST.get('data_fim_pipeline', '')
        erro = None
        if not data_inicio_pipeline or not data_fim_pipeline:
            erro = "Datas de início e fim são obrigatórias para o pipeline manual."
        else:
            try:
                dt_inicio = datetime.strptime(data_inicio_pipeline, '%Y-%m-%d').date()
                dt_fim = datetime.strptime(data_fim_pipeline, '%Y-%m-%d').date()
                if dt_inicio > dt_fim:
                    erro = "Data de início não pode ser posterior à data de fim."
            except ValueError:
                erro = "Formato de data inválido. Use AAAA-MM-DD."
        if erro:
            messages.error(request, erro)
            context = {
                'data_inicio_pipeline': data_inicio_pipeline,
                'data_fim_pipeline': data_fim_pipeline,
                'messages': messages.get_messages(request),
            }
            return render(request, 'iniciar_pipeline_form.html', context)
        # Dispara a tarefa Celery manual
        try:
            task = pipeline_manual_completo.delay(data_inicio_str=data_inicio_pipeline, data_fim_str=data_fim_pipeline)
            messages.success(request, f"Pipeline manual completo (de {data_inicio_pipeline} a {data_fim_pipeline}) iniciado. ID da Tarefa: {task.id}")
            return redirect('iniciar_pipeline_completo_manual')
        except Exception as e:
            logger.error(f"Erro ao iniciar pipeline manual completo: {e}", exc_info=True)
            messages.error(request, f"Erro ao iniciar pipeline manual: {str(e)}")
            context = {
                'data_inicio_pipeline': data_inicio_pipeline,
                'data_fim_pipeline': data_fim_pipeline,
                'messages': messages.get_messages(request),
            }
            return render(request, 'iniciar_pipeline_form.html', context)
    # GET: renderiza o formulário vazio
    context = {
        'data_inicio_pipeline': '',
        'data_fim_pipeline': '',
        'messages': messages.get_messages(request),
    }
    return render(request, 'iniciar_pipeline_form.html', context)


"""
Exclui relatório gerado e remove arquivo físico do servidor.
"""
@login_required
@require_POST # É uma boa prática que ações destrutivas como excluir sejam feitas via POST
def excluir_relatorio_view(request, pk):
    relatorio = get_object_or_404(RelatorioGerado, pk=pk)
    nome_arquivo_log = relatorio.nome_arquivo() # Pega o nome antes de deletar o arquivo

    try:

        if relatorio.caminho_arquivo and hasattr(relatorio.caminho_arquivo, 'path'):
            caminho_fisico_arquivo = relatorio.caminho_arquivo.path
            if os.path.exists(caminho_fisico_arquivo):
                try:
                    os.remove(caminho_fisico_arquivo)
                    logger.info(f"Arquivo físico '{caminho_fisico_arquivo}' removido com sucesso.")
                except OSError as e:
                    logger.error(f"Erro ao tentar remover o arquivo físico '{caminho_fisico_arquivo}': {e}")
                    messages.error(request, f"Erro ao remover o arquivo físico do relatório. O registro do relatório foi excluído, mas o arquivo pode permanecer no servidor.")
            else:
                logger.warning(f"Arquivo físico para o relatório ID {pk} não encontrado em '{caminho_fisico_arquivo}'. Apenas o registro será excluído.")
        else:
            logger.warning(f"Relatório ID {pk} não possui um caminho de arquivo associado para exclusão física.")
            
        if relatorio.caminho_arquivo:
            relatorio.caminho_arquivo.delete(save=False) # save=False para não salvar o modelo agora

        relatorio.delete() # Deleta o registro do banco

        messages.success(request, f"Relatório '{nome_arquivo_log}' excluído com sucesso.")
        logger.info(f"Relatório ID {pk} ('{nome_arquivo_log}') excluído do banco de dados.")

    except Exception as e:
        logger.error(f"Erro ao excluir o relatório ID {pk}: {e}", exc_info=True)
        messages.error(request, f"Ocorreu um erro ao tentar excluir o relatório: {str(e)}")
    
    # Redireciona preservando filtros
    url = reverse('dashboard_relatorios')
    params = []
    for key in ['tipo', 'data_inicio', 'data_fim', 'page']:
        value = request.GET.get(key)
        if value:
            params.append(f'{key}={value}')
    if params:
        url += '?' + '&'.join(params)
    return redirect(url)



@login_required
def visualizar_relatorio(request, pk):
    relatorio = get_object_or_404(RelatorioGerado, pk=pk)
    # Garante que parametros seja um dicionário
    parametros = relatorio.parametros if hasattr(relatorio, 'parametros') and isinstance(relatorio.parametros, dict) else {}
    # Mensagens de feedback
    storage = messages.get_messages(request)
    context = {
        'relatorio': relatorio,
        'parametros': parametros,
        'messages': storage,
    }
    return render(request, 'relatorios/visualizar_relatorios.html', context)

# Dashboard de vigência das normas
@login_required
def dashboard_vigencia(request):
    # Lista normas vigentes e revogadas, com datas e status
    normas_vigentes = NormaVigente.objects.filter(situacao='VIGENTE').order_by('-data_verificacao', '-data_cadastro')
    normas_revogadas = NormaVigente.objects.filter(situacao='REVOGADA').order_by('-data_verificacao', '-data_cadastro')
    total_vigentes = normas_vigentes.count()
    total_revogadas = normas_revogadas.count()
    ultima_execucao = LogExecucao.objects.filter(tipo_execucao='VERIFICACAO_SEFAZ').order_by('-data_inicio').first()
    storage = messages.get_messages(request)
    context = {
        'normas_vigentes': normas_vigentes,
        'normas_revogadas': normas_revogadas,
        'total_vigentes': total_vigentes,
        'total_revogadas': total_revogadas,
        'ultima_execucao': ultima_execucao,
        'messages': storage,
    }
    return render(request, 'monitor/dashboard_vigencia.html', context)