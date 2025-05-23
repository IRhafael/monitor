from __future__ import absolute_import
import os
from celery import Celery
from django.conf import settings

# Configurações específicas para Windows
os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')

app = Celery('diario_oficial')

# Usar 'solo' como pool no Windows
app.conf.worker_pool = 'solo'  # Ou 'threads' para múltiplas threads

# Desativar soft timeouts
app.conf.worker_disable_rate_limits = True
app.conf.worker_enable_remote_control = False

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)