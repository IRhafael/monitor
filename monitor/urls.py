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
    
    # Logs
    path('logs/', views.logs_execucao, name='logs_execucao'),
]