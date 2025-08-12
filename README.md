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
wsl -d calculadora --cd /calculadora --exec bash start.sh
celery -A diario_oficial worker -l info

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