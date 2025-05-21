from datetime import timedelta, datetime
from itertools import count
from urllib import request
from django.db.models import F, ExpressionWrapper, Q # Adicione Q para consultas complexas
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
from .utils.tasks import coletar_diario_oficial_task, processar_documentos_pendentes_task
from datetime import timedelta, date
from .utils.tasks import pipeline_coleta_e_processamento
from .forms import DocumentoUploadForm
from .models import Documento, NormaVigente, LogExecucao, RelatorioGerado
from .utils.sefaz_integracao import IntegradorSEFAZ # Mantida se houver outras funções síncronas aqui que não sejam tarefas
from .utils.relatorio import RelatorioGenerator
from .utils.tasks import coletar_diario_oficial_task, processar_documentos_pendentes_task, verificar_normas_sefaz_task



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
            
            norma.situacao = resultado.get('situacao', 'NAO_ENCONTRADA')
            norma.data_verificacao = timezone.now()
            norma.save()
            
            return JsonResponse({'success': True})
        except NormaVigente.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Norma não encontrada.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Requisição inválida'})


@login_required
def verificar_normas_view(request):
    if request.method == 'POST':
        # Dispara a tarefa Celery para verificar normas da SEFAZ
        verificacao_task_info = verificar_normas_sefaz_task.delay()
        logger.info(f"Tarefa de verificação de normas SEFAZ disparada com ID: {verificacao_task_info.id}")
        
        messages.success(request, "Verificação de normas SEFAZ iniciada em segundo plano. Verifique os logs do Celery worker para o progresso.")
        return redirect('dashboard_vigencia') # Redireciona para o dashboard de vigência
    
    # Mostra informações sobre a última execução da verificação de normas para a view GET
    ultima_execucao = LogExecucao.objects.filter(tipo_execucao='VERIFICACAO_SEFAZ').order_by('-data_inicio').first()
    normas_para_verificar_count = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) |
        Q(data_verificacao__lt=timezone.now() - timedelta(days=30))
    ).count()

    context = {
        'ultima_execucao': ultima_execucao,
        'normas_para_verificar_count': normas_para_verificar_count,
    }
    return render(request, 'normas/verificar_normas.html', context) # Assumindo um template específico


@login_required
def executar_coleta_view(request):
    if request.method == 'POST':
        data_fim = date.today()
        data_inicio = data_fim - timedelta(days=3) # Últimos 3 dias como padrão

        # Dispara o pipeline completo via Celery
        pipeline_task_info = pipeline_coleta_e_processamento.delay(
            data_inicio_str=data_inicio.strftime('%Y-%m-%d'),
            data_fim_str=data_fim.strftime('%Y-%m-%d')
        )
        logger.info(f"Pipeline de coleta, processamento e verificação SEFAZ disparado com ID: {pipeline_task_info.id}")

        messages.success(request,
            f"O fluxo completo de coleta, processamento e verificação de normas foi iniciado em segundo plano. "
            f"ID da tarefa principal: {pipeline_task_info.id}. Acompanhe o progresso no terminal do Celery."
        )
        return redirect('dashboard') # Redireciona para o dashboard após o disparo

    # Parte GET da view: mostra informações sobre a última execução
    ultima_execucao_coleta = LogExecucao.objects.filter(tipo_execucao='COLETA').order_by('-data_inicio').first()
    ultima_execucao_processamento = LogExecucao.objects.filter(tipo_execucao='PROCESSAMENTO_PDF').order_by('-data_inicio').first()
    ultima_execucao_sefaz = LogExecucao.objects.filter(tipo_execucao='VERIFICACAO_SEFAZ').order_by('-data_inicio').first()

    documentos_nao_processados = Documento.objects.filter(processado=False).count()
    normas_nao_verificadas = NormaVigente.objects.filter(data_verificacao__isnull=True).count()
    normas_desatualizadas = NormaVigente.objects.filter(data_verificacao__lt=timezone.now() - timedelta(days=30)).count()


    context = {
        'ultima_execucao_coleta': ultima_execucao_coleta,
        'ultima_execucao_processamento': ultima_execucao_processamento,
        'ultima_execucao_sefaz': ultima_execucao_sefaz,
        'documentos_nao_processados': documentos_nao_processados,
        'normas_nao_verificadas': normas_nao_verificadas,
        'normas_desatualizadas': normas_desatualizadas,
    }
    # Ajuste o caminho do template se necessário
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
            RelatorioGenerator.gerar_relatorio_contabil()  # Método estático
            messages.success(request, "Relatório contábil gerado com sucesso!")
        except Exception as e:
            messages.error(request, f"Erro ao gerar relatório contábil: {e}")
        return redirect('dashboard_relatorios')
    
    # Para GET, renderiza um template com um botão para enviar POST
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