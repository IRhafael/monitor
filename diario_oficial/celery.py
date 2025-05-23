# C:\Users\RRCONTAS\Documents\GitHub\monitor\diario_oficial\celery.py

import os
from celery import Celery
from django.utils import timezone # Adicionado para 'timezone.now()' na health_check
import socket 
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')


app = Celery('diario_oficial')

app.config_from_object('django.conf:settings', namespace='CELERY')


app.autodiscover_tasks()

@app.task(bind=True, ignore_result=True)
def debug_task(self):

    print(f'Request: {self.request!r}')


app.conf.task_soft_time_limit = 600  # Tempo limite suave (10 minutos)
app.conf.task_time_limit = 900       # Tempo limite rígido (15 minutos)
app.conf.worker_prefetch_multiplier = 1  # Evita que o worker pegue muitas tarefas de uma vez
app.conf.task_acks_late = True      # Reconhecimento de tarefa após a execução
app.conf.worker_max_tasks_per_child = 100  # Reinicia o worker após X tarefas para evitar vazamentos de memória

# Adicione estas configurações adicionais (idealmente em settings.py)
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_always_eager=False, # Definido como False para usar o broker (Redis), True executa imediatamente
    task_create_missing_queues=True, # Cria filas automaticamente se não existirem
    task_default_queue='diario_oficial', # Nome da fila padrão para as tarefas
    task_ignore_result=False, # Alterado para False para que os resultados das tarefas sejam armazenados (útil para Django-Celery-Results)
    worker_prefetch_multiplier=4, # Ajustado para 4, um bom equilíbrio para performance
    worker_max_memory_per_child=250000, # Limite de memória por worker child (250MB)
    broker_connection_retry_on_startup=True # Tenta reconectar ao broker na inicialização
)

@app.task(bind=True)
def health_check(self):

    return {
        'status': 'OK',
        'timestamp': timezone.now().isoformat(),
        'worker': socket.gethostname()
    }