# C:\Users\RRCONTAS\Documents\GitHub\monitor\diario_oficial\celery.py

import os
from celery import Celery

# Define o módulo de configurações padrão do Django para o programa 'celery'.
# MUDAR 'monitor.settings' para 'diario_oficial.settings'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings') # <-- CORREÇÃO AQUI

# Cria uma instância da aplicação Celery.
# O nome 'diario_oficial' aqui deve ser o mesmo usado no comando 'celery -A'
app = Celery('diario_oficial') # <-- RECOMENDADO MUDAR AQUI TAMBÉM PARA CONSISTÊNCIA

# Usa as configurações do Django para o Celery.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Carrega módulos de tarefas de todos os apps Django registrados.
app.autodiscover_tasks()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')