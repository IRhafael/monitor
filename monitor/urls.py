from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('documentos/', views.documentos_list, name='documentos_list'),
    path('documentos/upload/', views.documento_upload, name='documento_upload'),
    path('normas/', views.normas_list, name='normas_list'),
    path('normas/<str:tipo>/<str:numero>/verificar/', views.verificar_norma, name='verificar_norma'),
    path('executar-coleta/', views.executar_coleta_view, name='executar_coleta'),
    path('gerar-relatorio/', views.gerar_relatorio, name='gerar_relatorio'),
    path('download-relatorio/<int:relatorio_id>/', views.download_relatorio, name='download_relatorio'),
]