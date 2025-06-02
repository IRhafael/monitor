# diario_oficial/settings.py
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-c+!j04o8ab6!*1ts^0t!-d&eondxnja+j9o14!2pdqt0rvob!f'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'monitor.apps.MonitorConfig',
    'django_extensions',
    'django_celery_results',
    'django_celery_beat', 
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'diario_oficial.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'monitor' / 'frontend' / 'templates'],  # Aqui, adiciona o caminho absoluto para a pasta de templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'diario_oficial.wsgi.application'


ANTHROPIC_API_KEY = "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" 

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'monitor',
        'USER': 'root',     # <--- Usando 'root'
        'PASSWORD': '1234', # <--- Usando '1234'
        'HOST': '127.0.0.1', # <--- Usando IP para forçar TCP/IP
        'PORT': '3306',
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'


USE_I18N = True

USE_TZ = False 
TIME_ZONE = 'America/Fortaleza'


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/admin/login/'  # Usando o admin como login temporário

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CELERY_BROKER_URL = 'redis://localhost:6379/0'  # Altere para a URL do seu broker (Redis)
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0' # Onde os resultados das tarefas são armazenados
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'America/Sao_Paulo' # Ou seu timezone local
CELERY_ENABLE_UTC = True # Recomendado para lidar com fusos horários




LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'monitor.utils.tasks': { # O nome do logger deve ser o caminho do seu arquivo de tarefas
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Adicione outros loggers de apps Django se quiser ver seus logs
        'django': {
            'handlers': ['console'],
            'level': 'INFO', # Ou WARNING/ERROR se quiser menos verbosidade
            'propagate': False,
        },
    },
}