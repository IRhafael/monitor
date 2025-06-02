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


inspector = app.control.inspect()




logger = logging.getLogger(__name__)

@login_required
def dashboard(request):
    # Estatísticas para o dashboard
    total_documentos = Documento.objects.count()
    documentos_recentes = Documento.objects.order_by('-data_publicacao')[:5]
    total_normas = NormaVigente.objects.count()
    
    # Normas que precisam de verificação (ex: não verificadas ou verificadas há mais de 30 dias)
    normas_para_verificar = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) | Q(data_verificacao__lt=timezone.now() - timedelta(days=30))
    ).order_by('-data_cadastro')[:5]

    context = {
        'total_documentos': total_documentos,
        'documentos_recentes': documentos_recentes,
        'total_normas': total_normas,
        'normas_para_verificar': normas_para_verificar,
    }
    return render(request, 'dashboard.html', context)


@login_required
def dashboard_vigencia(request):
    # Calcula a data de 7 dias atrás e 30 dias atrás e 90 dias atrás
    sete_dias_atras = timezone.now() - timedelta(days=7)
    trinta_dias_atras = timezone.now() - timedelta(days=30)
    noventa_dias_atras = timezone.now() - timedelta(days=90)
    normas = NormaVigente.objects.annotate(
        dias_desde_verificacao=ExpressionWrapper(
            timezone.now() - F('data_verificacao'),
            output_field=DurationField()
        )
    ).order_by('situacao', 'dias_desde_verificacao') # Mantém a ordenação se desejar

    context = {
        'normas': normas,
        # Filtra normas verificadas nos últimos 7 dias (excluindo nulas)
        'recentemente_verificadas': normas.filter(
            data_verificacao__gte=sete_dias_atras
        ),
        'para_verificar': normas.filter(
            Q(data_verificacao__isnull=True) | Q(data_verificacao__lte=trinta_dias_atras)
        ),
        'alertas': normas.filter(
            Q(data_verificacao__isnull=True) | Q(data_verificacao__lte=noventa_dias_atras)
        ),
    }
    return render(request, 'dashboard.html', context)


@login_required
def analise_documentos(request):
    documentos = Documento.objects.filter(processado=False).order_by('-data_publicacao')
    context = {
        'documentos': documentos
    }
    return render(request, 'processamento/analise.html', context)

@login_required
def resultados_analise(request):
    documentos = Documento.objects.filter(processado=True).order_by('-data_publicacao')
    context = {
        'documentos': documentos
    }
    return render(request, 'processamento/resultados.html', context)

@login_required
def validacao_normas(request):
    # Esta view pode mostrar todas as normas e seu status de validação/verificação
    normas = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) | 
        Q(data_verificacao__lt=timezone.now()-timedelta(days=30))
    ).order_by('tipo', 'numero')
    
    context = {
        'normas': normas
    }
    return render(request, 'normas/validacao.html', context)

def verificar_norma_ajax(request, tipo, numero):
    print(f"Verificando norma: tipo={tipo}, numero={numero}")  # DEBUG
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            norma = NormaVigente.objects.get(tipo=tipo, numero=numero)
            integrador = IntegradorSEFAZ()
            resultado = integrador.buscar_norma_especifica(norma.tipo, norma.numero)
            
            # Corrigido aqui: mapeia corretamente o resultado
            status = 'VIGENTE' if resultado.get('vigente') else 'REVOGADA'
            norma.situacao = status
            norma.data_verificacao = timezone.now()
            norma.save()
            
            return JsonResponse({
                'success': True,
                'status': status,
                'data_verificacao': norma.data_verificacao.strftime('%d/%m/%Y %H:%M')
            })
        except NormaVigente.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Norma não encontrada.'}, status=404)
        except Exception as e:
            logger.error(f"Erro ao verificar norma {tipo} {numero}: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Requisição inválida'}, status=400)


@login_required
def executar_coleta_view(request):
    if request.method == 'POST':
        try:
            dias_retroativos = int(request.POST.get('days_back', 3))
            
            # Use o nome da tarefa refatorada
            task_info = pipeline_coleta_e_processamento_automatica.delay(
                dias_retroativos_coleta=dias_retroativos
            )
            
            messages.success(request, 
                f"Pipeline automático (coleta dos últimos {dias_retroativos} dias, processamento e verificação SEFAZ) iniciado. "
                f"ID da tarefa: {task_info.id}"
            )
        except Exception as e:
            logger.error(f"Erro ao disparar pipeline automático: {e}", exc_info=True)
            messages.error(request, f"Erro ao iniciar pipeline: {str(e)}")
        return redirect('dashboard')

    # ... (resto da lógica GET da view, incluindo a busca por celery_status)
    # Certifique-se que 'app' (instância do Celery) está corretamente importada e usada para app.control.inspect()
    celery_worker_status = {'is_running': False, 'active_tasks': 0, 'queued_tasks': 0, 'workers': 0}
    try:
        inspector = app.control.inspect(timeout=1) 
        active = inspector.active()
        scheduled = inspector.scheduled()
        ping_result = inspector.ping()

        if ping_result:
            celery_worker_status['is_running'] = True
            celery_worker_status['workers'] = len(ping_result.keys())
        if active:
            celery_worker_status['active_tasks'] = sum(len(tasks) for tasks in active.values())
        if scheduled:
            celery_worker_status['queued_tasks'] = sum(len(tasks) for tasks in scheduled.values())
    except Exception as e:
        logger.warning(f"Não foi possível obter status do Celery em executar_coleta_view: {e}")
        # Não mostre uma mensagem de erro aqui, a menos que seja crítico para esta view

    context = {
        # ... (seu contexto existente) ...
        'celery_status': celery_worker_status,
    }
    return render(request, 'executar_coleta.html', context)

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

@login_required
def detalhe_documento(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    return render(request, 'documentos/detalhe.html', {'documento': documento})

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

@login_required
def gerar_relatorio_contabil_view(request):
    if request.method == 'POST':
        try:
            relatorio = RelatorioAvancado()
            caminho_do_relatorio = relatorio.gerar_relatorio_completo()
            
            if caminho_do_relatorio:
                messages.success(request, "Relatório contábil gerado com sucesso!")
            else:
                messages.error(request, "Falha ao gerar o relatório contábil.")

        except Exception as e:
            logger.error(f"Erro ao gerar relatório contábil: {e}", exc_info=True)
            messages.error(request, f"Erro ao gerar relatório contábil: {e}")
        return redirect('dashboard_relatorios')

    return render(request, 'relatorios/gerar_relatorio.html')

@login_required
def dashboard_relatorios(request):
    relatorios = RelatorioGerado.objects.order_by('-data_criacao')
    return render(request, 'relatorios/listar_relatorios.html', {'relatorios': relatorios})


@login_required
def download_relatorio(request, pk):
    relatorio = get_object_or_404(RelatorioGerado, pk=pk)
    # Garante que o caminho seja seguro para evitar Directory Traversal
    file_path = os.path.join(settings.MEDIA_ROOT, relatorio.caminho_arquivo)
    
    # Verifica se o arquivo realmente existe e está dentro de MEDIA_ROOT
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise Http404("Arquivo não encontrado.")

    abs_media_root = os.path.abspath(settings.MEDIA_ROOT)
    abs_file_path = os.path.abspath(file_path)
    if not abs_file_path.startswith(abs_media_root):
        raise Http404("Acesso negado: Caminho de arquivo inválido.")

    with open(file_path, 'rb') as fh:
        # Define o tipo de conteúdo como Excel (xlsx)
        response = HttpResponse(fh.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
        return response
    raise Http404("Erro ao abrir o arquivo para download.")

# Exemplo de uma view para exibir logs de execução
@login_required
def logs_execucao(request):
    logs = LogExecucao.objects.all().order_by('-data_inicio')
    context = {
        'logs': logs
    }
    return render(request, 'monitor/logs_execucao.html', context)


@login_required
def normas_revogadas(request):
    normas = NormaVigente.objects.filter(situacao='REVOGADA').order_by('-data_verificacao', '-data_cadastro')
    context = {
        'normas': normas
    }
    return render(request, 'normas/normas_revogadas.html', context)

def norma_historico(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    return render(request, 'normas/historico.html', {'norma': norma})

@login_required
def adicionar_norma(request):

    if request.method == 'POST':

        messages.error(request, "Funcionalidade de adicionar norma manual não implementada.")
        return redirect('validacao_normas')
    return render(request, 'normas/adicionar_norma.html', {}) # Criar template

# Uma view para detalhe de uma norma específica
@login_required
def detalhe_norma(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    context = {
        'norma': norma
    }
    return render(request, 'normas/detalhe_norma.html', context)

# Exemplo de view para marcar um documento como irrelevante (se for uma ação manual)
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
@login_required
def logs_execucao(request):
    logs = LogExecucao.objects.all().order_by('-data_inicio')
    context = {
        'logs': logs
    }
    return render(request, 'logs_execucao.html', context)


@login_required
def normas_revogadas(request):
    normas = NormaVigente.objects.filter(situacao='REVOGADA').order_by('-data_verificacao', '-data_cadastro')
    context = {
        'normas': normas
    }
    return render(request, 'normas/normas_revogadas.html', context)

@login_required
def adicionar_norma(request):
    # from .forms import NormaVigenteForm # Descomente e crie este formulário
    
    if request.method == 'POST':
        messages.error(request, "Funcionalidade de adicionar norma manual não implementada ainda.")
        return redirect('validacao_normas') # Ou renderiza o formulário novamente com erros
    return render(request, 'normas/adicionar_norma.html', {}) # Criar template 'adicionar_norma.html'

# Uma view para detalhe de uma norma específica
@login_required
def detalhe_norma(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    context = {
        'norma': norma
    }
    return render(request, 'normas/detalhe_norma.html', context)

# Exemplo de view para marcar um documento como irrelevante (se for uma ação manual)
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



@login_required
def celery_control(request):
    return render(request, 'celery/celery_control.html')

@login_required
def celery_status(request):
    try:
        i = inspect()
        active_tasks = len(i.active() or {})
        scheduled_tasks = len(i.scheduled() or {})
        
        # Verifica se o worker está ativo
        is_running = bool(i.ping())
        
        return JsonResponse({
            'is_running': is_running,
            'active_tasks': active_tasks,
            'queued_tasks': scheduled_tasks
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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

@login_required
def verify_normas_batch(request):
    if request.method == 'POST':
        norma_ids = request.POST.getlist('ids[]')
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

@require_POST
@login_required
def process_document_batch(request):
    try:
        document_ids = request.POST.getlist('ids[]')
        # Dispara tarefa assíncrona para processar os documentos
        task = processar_documentos_pendentes_task.delay(document_ids=document_ids)
        return JsonResponse({'success': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_POST
@login_required
def verify_normas_batch(request):
    try:
        norma_ids = request.POST.getlist('ids[]')
        # Dispara tarefa assíncrona para verificar as normas
        task = verificar_normas_sefaz_task.delay(norma_ids=norma_ids)
        return JsonResponse({'success': True, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def document_preview(request, pk):
    documento = get_object_or_404(Documento, pk=pk)
    context = {'documento': documento}
    return render(request, 'documentos/preview.html', context)

@login_required
def norma_history(request, pk):
    norma = get_object_or_404(NormaVigente, pk=pk)
    verificacoes = LogExecucao.objects.filter(
        tipo_execucao='VERIFICACAO_SEFAZ',
        detalhes__contains={'norma_id': norma.id}
    ).order_by('-data_inicio')
    context = {'norma': norma, 'verificacoes': verificacoes}
    return render(request, 'normas/history.html', context)



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
    


class RelatorioDashboardView(TemplateView):
    template_name = 'relatorios/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Estatísticas básicas
        context['total_relatorios'] = RelatorioGerado.objects.count()
        context['total_contabil'] = RelatorioGerado.objects.filter(tipo='CONTABIL').count()
        context['total_downloads'] = RelatorioGerado.objects.aggregate(
            total=Sum('downloads')
        )['total'] or 0
        
        # Relatórios deste mês
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
        context['relatorios_mes'] = RelatorioGerado.objects.filter(
            data_criacao__gte=month_start
        ).count()
        
        # Dados para gráficos
        tipos = RelatorioGerado.objects.values('tipo').annotate(
            total=Count('id')
        ).order_by('-total')
        
        context['tipos_labels'] = [t['tipo'] for t in tipos]
        context['tipos_data'] = [t['total'] for t in tipos]
        
        # Últimos 12 meses
        meses = []
        data = []
        hoje = timezone.now()
        
        for i in range(11, -1, -1):
            month = hoje.month - i
            year = hoje.year
            if month < 1:
                month += 12
                year -= 1
            
            start_date = timezone.datetime(year, month, 1)
            end_date = timezone.datetime(
                year, month, 
                calendar.monthrange(year, month)[1],
                23, 59, 59
            )
            
            count = RelatorioGerado.objects.filter(
                data_criacao__range=(start_date, end_date)
            ).count()
            
            meses.append(calendar.month_abbr[month])
            data.append(count)
        
        context['meses_labels'] = meses
        context['meses_data'] = data
        
        return context
    

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


@login_required
def iniciar_pipeline_completo_manual_view(request): # Renomeada de iniciar_pipeline_manual_view
    # from .forms import PipelineManualForm # Se você criar um form
    if request.method == 'POST':
        data_inicio_str = request.POST.get('data_inicio_pipeline')
        data_fim_str = request.POST.get('data_fim_pipeline')

        if not data_inicio_str or not data_fim_str:
            messages.error(request, "Datas de início e fim são obrigatórias para o pipeline manual.")
        else:
            try:
                data_i = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                data_f = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                if data_i > data_f:
                    messages.error(request, "Data de início não pode ser posterior à data de fim.")
                else:
                    task = pipeline_manual_completo.delay(data_inicio_str=data_inicio_str, data_fim_str=data_fim_str)
                    messages.success(request, f"Pipeline manual completo (de {data_inicio_str} a {data_fim_str}) iniciado. ID da Tarefa: {task.id}")
                    return redirect('logs_execucao')
            except ValueError:
                messages.error(request, "Formato de data inválido. Use AAAA-MM-DD.")
            except Exception as e:
                logger.error(f"Erro ao iniciar pipeline manual completo: {e}", exc_info=True)
                messages.error(request, f"Erro ao iniciar pipeline manual: {str(e)}")
        # Se houver erro ou for GET, renderiza o formulário novamente
        return render(request, 'monitor/iniciar_pipeline_form.html', {'data_inicio': data_inicio_str, 'data_fim': data_fim_str})

    return render(request, 'monitor/iniciar_pipeline_form.html')