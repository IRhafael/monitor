from django.urls import path
from . import views

urlpatterns = [
    # Dashboard e páginas principais
    path('', views.dashboard, name='dashboard'),
    path('vigencia/', views.dashboard_vigencia, name='dashboard_vigencia'), # Movi para cá para agrupamento

    # Documentos
    # Adaptei 'documentos_list' para 'analise_documentos' que lista os não processados
    # Se você precisar de uma lista de TODOS os documentos, precisará criar uma nova view em views.py
    path('documentos/analise/', views.analise_documentos, name='analise_documentos'),
    path('documentos/resultados/', views.resultados_analise, name='resultados_analise'), # Documentos já processados
    path('documentos/upload/', views.upload_documento, name='upload_documento'), # Renomeada
    path('documentos/<int:pk>/', views.detalhe_documento, name='documento_detail'), # Usando pk
    path('documentos/<int:pk>/editar/', views.editar_documento, name='editar_documento'), # Adicionei a rota de edição
    path('documentos/<int:pk>/reprocessar/', views.reprocessar_documento, name='reprocessar_documento'), # Adicionei a rota de reprocessamento
    path('documentos/<int:pk>/marcar-irrelevante/', views.marcar_documento_irrelevante, name='marcar_documento_irrelevante'), # Adicionei a rota para marcar como irrelevante
    
    # Normas
    # Adaptei 'normas_list' para 'validacao_normas' que lista as normas para validação/verificação
    path('normas/validacao/', views.validacao_normas, name='validacao_normas'),
    path('normas/revogadas/', views.normas_revogadas, name='normas_revogadas'), # Adicionada rota para normas revogadas
    path('normas/adicionar/', views.adicionar_norma, name='adicionar_norma'), # Rota para adicionar norma (se implementar o form)
    path('normas/<int:pk>/', views.detalhe_norma, name='detalhe_norma'), # Usando pk
    path('verificar-normas/', views.verificar_normas_view, name='verificar_normas'),
    path('normas/<int:pk>/historico/', views.norma_historico, name='norma_historico'),
    path('normas/<str:tipo>/<path:numero>/verificar/', views.verificar_norma_ajax, name='verificar_norma_ajax'),
    

    # Coleta e processamento
    path('executar-coleta/', views.executar_coleta_view, name='executar_coleta'),
    
    # Relatórios
    path('relatorios/', views.dashboard_relatorios, name='dashboard_relatorios'), # Dashboard dos relatórios gerados
    path('relatorios/gerar/', views.gerar_relatorio_contabil_view, name='gerar_relatorio'), # Renomeada
    path('relatorios/<int:pk>/download/', views.download_relatorio, name='download_relatorio'), 
    path('relatorios/<int:pk>/excluir/', views.excluir_relatorio_view, name='excluir_relatorio'),

    # Logs
    path('logs/', views.logs_execucao, name='logs_execucao'),


    path('celery/control/', views.celery_control, name='celery_control'),
    path('celery/status/', views.celery_status, name='celery_status'),
    path('celery/start/', views.start_celery_worker, name='start_celery_worker'),
    path('celery/stop/', views.stop_celery_worker, name='stop_celery_worker'),
    path('celery/tasks/', views.get_celery_tasks, name='get_celery_tasks'),
    path('normas/verify-batch/', views.verify_normas_batch, name='verify_normas_batch'),

    path('documentos/process-batch/', views.process_document_batch, name='process_document_batch'),
    path('documentos/<int:pk>/preview/', views.document_preview, name='document_preview'),
    path('normas/verify-batch/', views.verify_normas_batch, name='verify_normas_batch'),
    path('normas/<int:pk>/history/', views.norma_history, name='norma_history'),
    path('coleta/iniciar-apenas-coleta/', views.iniciar_apenas_coleta_view, name='iniciar_apenas_coleta'),
    path('documentos/processar-todos-pendentes/', views.processar_todos_pendentes_view, name='processar_todos_pendentes'),
    path('pipeline/iniciar-completo-manual/', views.iniciar_pipeline_completo_manual_view, name='iniciar_pipeline_completo_manual'),



    ]