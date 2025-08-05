from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('upload/', views.upload_documento, name='upload_documento'),
    path('coletar/', views.coletar_dados_receita_view, name='coletar_dados_receita_view'),
    path('coletar-diario/', views.coletar_diario_oficial_view, name='coletar_diario_oficial_view'),
    path('processar-documentos/', views.processar_documentos_view, name='processar_documentos_view'),
    path('verificar-normas/', views.verificar_normas_sefaz_view, name='verificar_normas_sefaz_view'),
    path('gerar-relatorio/', views.gerar_relatorio_view, name='gerar_relatorio_view'),
    path('pipeline-manual/', views.pipeline_manual_view, name='pipeline_manual_view'),
    path('monitoramento/', views.monitoramento_tasks, name='monitoramento_tasks'),
    path('painel-tasks/', views.painel_tasks, name='painel_tasks'),
]