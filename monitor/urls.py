from django.urls import path
from . import views

urlpatterns = [
    # Dashboard e páginas principais
    path('', views.dashboard, name='dashboard'),
    
    # Documentos
    path('documentos/', views.documentos_list, name='documentos_list'),
    path('documentos/upload/', views.documento_upload, name='documento_upload'),
    path('documentos/<int:documento_id>/', views.documento_detail, name='documento_detail'),
    
    # Normas
    path('normas/', views.normas_list, name='normas_list'),
    path('normas/<int:norma_id>/', views.norma_detail, name='norma_detail'),
    path('normas/<str:tipo>/<str:numero>/verificar/', views.verificar_norma, name='verificar_norma'),
    
    # Coleta e processamento
    path('executar-coleta/', views.executar_coleta_view, name='executar_coleta'),
    
    # Relatórios
    path('relatorios/', views.gerar_relatorio, name='gerar_relatorio'),
    path('relatorios/<int:relatorio_id>/', views.relatorio_detail, name='relatorio_detail'),
    path('relatorios/<int:relatorio_id>/download/', views.download_relatorio, name='download_relatorio'),
    
    # Vigência
    path('vigencia/', views.dashboard_vigencia, name='dashboard_vigencia'),
]