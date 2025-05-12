# monitor/__init__.py

from __future__ import absolute_import, unicode_literals

# Isso garante que o Celery seja carregado quando Django iniciar
#from .celery_app import app as celery_app

__all__ = ('celery_app',)
