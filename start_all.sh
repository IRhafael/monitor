#!/bin/bash
# Script para iniciar todos os serviços do sistema Monitor em Linux
# Ativa o ambiente virtual
source venv311/bin/activate

# Inicia o worker do Celery em background
celery -A diario_oficial worker -l info &

# Inicia o beat do Celery em background
celery -A diario_oficial beat -l info &

# Inicia a API calculadora (ajuste o caminho conforme necessário)
(cd /caminho/para/calculadora && bash start.sh &)

# Mensagem de status
echo "Todos os serviços foram iniciados em background!"
