from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('upload/', views.upload_documento, name='upload_documento'),
    path('coletar/', views.coletar_dados_receita_view, name='coletar_dados_receita'),
]