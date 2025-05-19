from datetime import timedelta, datetime
from itertools import count
from django.db.models import F, ExpressionWrapper
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

from .forms import DocumentoUploadForm
from .models import Documento, NormaVigente, LogExecucao, RelatorioGerado
from .utils import PDFProcessor
from .utils.diario_scraper import DiarioOficialScraper
from .utils.sefaz_integracao import IntegradorSEFAZ
from .utils.relatorio import RelatorioGenerator
from .tasks import executar_coleta_completa

logger = logging.getLogger(__name__)

@login_required
def dashboard(request):
    # Estatísticas para o dashboard
    total_documentos = Documento.objects.count()
    documentos_recentes = Documento.objects.order_by('-data_publicacao')[:5]
    total_normas = NormaVigente.objects.count()
    
    # Normas que precisam de verificação
    normas_para_verificar = NormaVigente.objects.filter(
        data_verificacao__isnull=True
    ).order_by('-documentos__data_publicacao')[:5]
    
    context = {
        'total_documentos': total_documentos,
        'documentos_recentes': documentos_recentes,
        'total_normas': total_normas,
        'ultima_execucao': LogExecucao.objects.last(),
        'normas_para_verificar': normas_para_verificar,
        'documentos_nao_processados': Documento.objects.filter(processado=False).count(),
    }
    return render(request, 'dashboard.html', context)

@login_required
def documentos_list(request):
    # Filtros
    status = request.GET.get('status', 'todos')
    
    documentos = Documento.objects.all().order_by('-data_publicacao')
    
    if status == 'processados':
        documentos = documentos.filter(processado=True)
    elif status == 'pendentes':
        documentos = documentos.filter(processado=False)
    
    context = {
        'documentos': documentos,
        'filtro_atual': status,
    }
    return render(request, 'documentos/documentos_list.html', context)

@login_required
def documento_detail(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    
    if request.method == 'POST' and 'processar' in request.POST:
        processor = PDFProcessor()
        if processor.processar_documento(documento):
            messages.success(request, "Documento processado com sucesso!")
        else:
            messages.warning(request, "Documento processado, mas sem normas relevantes encontradas.")
        return redirect('documento_detail', documento_id=documento.id)
    
    context = {
        'documento': documento,
        'normas': documento.normas_relacionadas.all(),
    }
    return render(request, 'documentos/documento_detail.html', context)

@login_required
def documento_upload(request):
    if request.method == 'POST':
        form = DocumentoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    documento = Documento(
                        titulo=form.cleaned_data['title'],
                        data_publicacao=form.cleaned_data['publication_date'],
                        arquivo_pdf=request.FILES['pdf_file'],
                        relevante_contabil=True  # Assume relevância para upload manual
                    )
                    documento.save()
                    
                    # Processa imediatamente
                    processor = PDFProcessor()
                    if processor.processar_documento(documento):
                        messages.success(request, "Documento processado com sucesso!")
                    else:
                        messages.warning(request, "Documento salvo, mas sem normas relevantes encontradas.")
                    
                    return redirect('documentos_list')
            
            except Exception as e:
                logger.error(f"Erro no upload manual: {str(e)}", exc_info=True)
                messages.error(request, f"Erro ao processar documento: {str(e)}")
    else:
        form = DocumentoUploadForm(initial={
            'publication_date': timezone.now().date()
        })
    
    return render(request, 'documentos/documento_upload.html', {'form': form})

from django.db.models import Count

@login_required
def normas_list(request):
    status = request.GET.get('status', 'todos')

    normas = NormaVigente.objects.all().annotate(
        num_documentos=Count('documentos')
    ).order_by('-data_verificacao')

    if status == 'vigentes':
        normas = normas.filter(situacao='VIGENTE')
    elif status == 'revogadas':
        normas = normas.filter(situacao='REVOGADA')

    context = {
        'normas': normas,
        'filtro_atual': status,
    }
    return render(request, 'normas/normas_list.html', context)

@login_required
def norma_detail(request, norma_id):
    norma = get_object_or_404(NormaVigente, id=norma_id)
    documentos = norma.documentos.all().order_by('-data_publicacao')
    
    context = {
        'norma': norma,
        'documentos': documentos,
    }
    return render(request, 'normas/historico.html', context)

@login_required
def verificar_norma(request, tipo, numero):
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Requisição inválida'}, status=400)
    
    try:
        integrador = IntegradorSEFAZ()
        vigente, detalhes = integrador.verificar_vigencia_com_detalhes(tipo, numero)
        
        norma, created = NormaVigente.objects.update_or_create(
            tipo=tipo,
            numero=numero,
            defaults={
                'situacao': 'VIGENTE' if vigente else 'REVOGADA',
                'data_verificacao': timezone.now(),
                'detalhes': detalhes,
            }
        )
        
        return JsonResponse({
            'success': True,
            'vigente': vigente,
            'norma_id': norma.id,
            'situacao': norma.get_situacao_display(),
            'data_verificacao': norma.data_verificacao.strftime("%d/%m/%Y %H:%M") if norma.data_verificacao else "",
        })
    
    except Exception as e:
        logger.error(f"Erro ao verificar norma {tipo} {numero}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def executar_coleta_view(request):
    if request.method == 'POST':
        try:
            # Executa a coleta de forma assíncrona
            task = executar_coleta_completa.delay()
            
            messages.info(request, 
                "Coleta iniciada em segundo plano. Você será notificado quando concluir."
            )
            return redirect('dashboard')
            
        except Exception as e:
            logger.error(f"Erro ao iniciar coleta: {str(e)}", exc_info=True)
            messages.error(request, f"Erro ao iniciar coleta: {str(e)}")
            return redirect('executar_coleta')
    
    # Mostra informações sobre a última execução
    ultima_execucao = LogExecucao.objects.last()
    documentos_nao_processados = Documento.objects.filter(processado=False).count()
    
    context = {
        'ultima_execucao': ultima_execucao,
        'documentos_nao_processados': documentos_nao_processados,
    }
    return render(request, 'executar_coleta.html', context)

@login_required
def gerar_relatorio(request):
    if request.method == 'POST':
        tipo_relatorio = request.POST.get('tipo_relatorio')
        
        try:
            if tipo_relatorio == 'completo':
                data_inicio = request.POST.get('data_inicio')
                data_fim = request.POST.get('data_fim')
                formato = request.POST.get('formato', 'xlsx')
                
                # Valida datas
                if data_inicio and data_fim:
                    data_inicio = datetime.strptime(data_inicio, '%Y-%m-%d').date()
                    data_fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
                else:
                    data_inicio = data_fim = None
                
                # Gera relatório
                caminho = RelatorioGenerator.gerar_relatorio_contabil(
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    formato=formato
                )
                
            elif tipo_relatorio == 'mudancas':
                dias_retroativos = int(request.POST.get('dias_retroativos', 15))
                caminho = RelatorioGenerator.gerar_relatorio_mudancas(dias_retroativos)
            
            else:
                raise ValueError("Tipo de relatório inválido")
            
            if caminho:
                # Salva registro do relatório gerado
                relatorio = RelatorioGerado(
                    tipo=tipo_relatorio,
                    caminho_arquivo=caminho,
                    gerado_por=request.user,
                    parametros={
                        'data_inicio': data_inicio.isoformat() if data_inicio else None,
                        'data_fim': data_fim.isoformat() if data_fim else None,
                        'dias_retroativos': dias_retroativos if tipo_relatorio == 'mudancas' else None,
                        'formato': formato if tipo_relatorio == 'completo' else 'xlsx',
                    }
                )
                relatorio.save()
                
                messages.success(request, "Relatório gerado com sucesso!")
                return redirect('relatorio_detail', relatorio_id=relatorio.id)
            
            messages.error(request, "Falha ao gerar relatório.")
            return redirect('gerar_relatorio')
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {str(e)}", exc_info=True)
            messages.error(request, f"Erro ao gerar relatório: {str(e)}")
            return redirect('gerar_relatorio')
    
    # Lista os últimos relatórios gerados
    relatorios = RelatorioGerado.objects.order_by('-data_criacao')[:10]
    
    context = {
        'relatorios': relatorios,
    }
    return render(request, 'relatorios/gerar_relatorio.html', context)

@login_required
def relatorio_detail(request, relatorio_id):
    relatorio = get_object_or_404(RelatorioGerado, id=relatorio_id)
    
    context = {
        'relatorio': relatorio,
    }
    return render(request, 'relatorios/visualizar.html', context)

@login_required
def download_relatorio(request, relatorio_id):
    relatorio = get_object_or_404(RelatorioGerado, id=relatorio_id)
    
    if not os.path.exists(relatorio.caminho_arquivo):
        raise Http404("Arquivo do relatório não encontrado")
    
    filename = os.path.basename(relatorio.caminho_arquivo)
    response = FileResponse(open(relatorio.caminho_arquivo, 'rb'))
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Atualiza contador de downloads
    relatorio.downloads += 1
    relatorio.save()
    
    return response

@login_required
def dashboard_vigencia(request):
    normas = NormaVigente.objects.annotate(
        dias_desde_verificacao=ExpressionWrapper(
            timezone.now() - F('data_verificacao'),
            output_field=DurationField()
        )
    ).order_by('dias_desde_verificacao')
    
    context = {
        'normas_vigentes': normas.filter(situacao="VIGENTE"),
        'normas_revogadas': normas.filter(situacao="REVOGADA"),
        'normas_nao_verificadas': normas.filter(data_verificacao__isnull=True),
        'alertas': normas.filter(dias_desde_verificacao__gt=timedelta(days=90)),
    }
    return render(request, 'monitor/dashboard_vigencia.html', context)

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
    normas = NormaVigente.objects.filter(
        Q(data_verificacao__isnull=True) | 
        Q(data_verificacao__lt=timezone.now()-timedelta(days=30))
    ).order_by('tipo', 'numero')
    
    context = {
        'normas': normas
    }
    return render(request, 'normas/validacao.html', context)