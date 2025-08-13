wsl -d calculadora --cd /calculadora --exec bash start.sh

# Monitor Receita Federal - Coleta e Orquestração

Este projeto realiza a coleta automatizada de dados importantes da Receita Federal, Diário Oficial e integrações SEFAZ, utilizando Django, Celery, MySQL e Redis.

## Principais Funcionalidades
- Coleta de dados da API da Receita Federal
- Coleta e processamento de documentos do Diário Oficial
- Verificação de normas SEFAZ
- Orquestração de tarefas com Celery (worker e beat)
- Interface web Django para visualização e administração

## Como rodar localmente (Windows)
1. Instale o Python 3.11+ e o MySQL e Redis localmente
2. Crie e ative um ambiente virtual:
	```sh
	python -m venv venv311
	venv311\Scripts\activate
	pip install -r requirements.txt
	```
3. Rode as migrations e crie um superusuário:
	```sh
	python manage.py migrate
	python manage.py createsuperuser
	```
4. Inicie os serviços necessários:
	```sh
	python manage.py runserver
	celery -A diario_oficial worker -l info
	celery -A diario_oficial beat -l info
	wsl -d calculadora --cd /calculadora --exec bash start.sh
	```
5. Acesse o sistema em: http://localhost:8000

## Comandos úteis
### Orquestração via monitor_tool.py

```sh
# Coletar documentos do Diário Oficial (com filtro de termos)
python monitor_tool.py coletar_diario --dias 3

# Coletar TODOS os PDFs do Diário Oficial (sem filtro de termos)
python monitor_tool.py coletar_diario_todos --dias 3

# Processar documentos pendentes
python monitor_tool.py processar_documentos

# Verificar normas SEFAZ
python monitor_tool.py verificar_normas

# Coletar dados da Receita Federal
python monitor_tool.py coletar_receita

# Executar pipeline automático (coleta/processa/verifica tudo)
python monitor_tool.py pipeline_auto --dias 3

# Executar pipeline manual (datas customizadas)
python monitor_tool.py pipeline_manual --inicio 2025-08-01 --fim 2025-08-13

# Gerar relatório contábil avançado
python monitor_tool.py gerar_relatorio

# Iniciar o worker do Celery em um novo terminal
python monitor_tool.py start_celery

# Iniciar a API (calculadora) via WSL em um novo terminal
python monitor_tool.py start_api

# Consultar status/resultados de uma task Celery pelo Task ID
python monitor_tool.py status_task --id <ID_DA_TASK>
```

## Dependências principais
- Python 3.11+
- Django
- Celery
- MySQL
- Redis
- mysql-connector-python (ou mysqlclient)

## Observações
- O projeto já está pronto para produção e desenvolvimento.
- Para customizações, consulte o arquivo `monitor_tool.py` para orquestração via CLI.
- Para dúvidas ou problemas, abra uma issue.

## Dependências principais
- Python 3.11+
- Django
- Celery
- MySQL
- Redis
- mysql-connector-python (ou mysqlclient)

## Observações
- O projeto já está pronto para produção e desenvolvimento.
- Para customizações, consulte o arquivo `monitor_tool.py` para orquestração via CLI.
- Para dúvidas ou problemas, abra uma issue.