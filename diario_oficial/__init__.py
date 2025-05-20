# monitor/monitor/__init__.py

# Isso garante que a aplicação Celery seja importada quando o Django iniciar,
# para que as tarefas sejam registradas.
from .celery import app as celery_app

__all__ = ('celery_app',)