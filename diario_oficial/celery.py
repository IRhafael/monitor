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

app.conf.task_soft_time_limit = 600  # 10 minutos para tarefas pesadas
app.conf.task_time_limit = 900       # 15 minutos máximo
app.conf.worker_prefetch_multiplier = 1  # Evita acumular tarefas
app.conf.task_acks_late = True  # Reconhecimento tardio
app.conf.worker_max_tasks_per_child = 100  # Reinicia worker periodicamente



# Adicione estas configurações adicionais
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_always_eager=False,
    task_create_missing_queues=True,
    task_default_queue='diario_oficial',
    task_ignore_result=False,  # Alterado para False para melhor debug
    worker_prefetch_multiplier=4,  # Ajustado para melhor performance
    worker_max_memory_per_child=250000,  # 250MB
    broker_connection_retry_on_startup=True
)


@app.task(bind=True)
def health_check(self):
    return {
        'status': 'OK',
        'timestamp': timezone.now().isoformat(),
        'worker': socket.gethostname()
    }