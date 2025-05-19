import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')

app = Celery('diario_oficial')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
app.autodiscover_tasks(['monitor'])