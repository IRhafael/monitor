# monitor/celery.py
import os
from celery import Celery

# Defina a variável de ambiente DJANGO_SETTINGS_MODULE com o seu módulo de configurações
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'monitor.settings')

# Crie a instância do Celery
app = Celery('monitor')

# Carregue as configurações do Django
app.config_from_object('django.conf:settings', namespace='CELERY')

# Descubra as tasks automaticamente
app.autodiscover_tasks()

