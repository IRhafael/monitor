#!/usr/bin/env python3
"""
monitor_tool.py - CLI para orquestração das principais rotinas do sistema Monitor

Comandos disponíveis:
    - coletar_diario: Coleta documentos do Diário Oficial (com filtro de termos)
    - coletar_diario_todos: Coleta TODOS os PDFs do Diário Oficial (sem filtro de termos)
    - processar_documentos: Processa documentos pendentes
    - verificar_normas: Verifica normas SEFAZ
    - coletar_receita: Coleta dados da Receita Federal
    - pipeline_auto: Executa pipeline automático (coleta/processa/verifica tudo)
    - pipeline_manual: Executa pipeline manual (datas customizadas)
    - gerar_relatorio: Gera relatório contábil avançado
    - start_celery: Inicia o worker do Celery em um novo terminal
    - start_api: Inicia a API (calculadora) via WSL em um novo terminal
    - status_task: Consulta o status/resultados de uma task Celery pelo Task ID

Uso:
    python monitor_tool.py <comando> [opções]
"""
import argparse
import os
import sys
import django
import logging

# Configura o ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
django.setup()

from monitor.tasks import (
    coletar_diario_oficial_task,
    processar_documentos_pendentes_task,
    verificar_normas_sefaz_task,
    coletar_dados_receita_task,
    pipeline_coleta_e_processamento_automatica,
    pipeline_manual_completo,
    gerar_relatorio_task
    # Os comandos start_celery, start_api e status_task não são tasks Celery, são utilitários implementados diretamente no CLI
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Monitor CLI - Orquestração de rotinas')
    subparsers = parser.add_subparsers(dest='comando', required=True)
    # Coletar todos os PDFs do Diário Oficial (sem filtro de termos)
    sp_diario_all = subparsers.add_parser('coletar_diario_todos', help='Coletar TODOS os PDFs do Diário Oficial (sem filtro de termos)')
    sp_diario_all.add_argument('--dias', type=int, default=3, help='Dias retroativos para coleta (padrão: 3)')

    # Coletar Diário Oficial
    sp_diario = subparsers.add_parser('coletar_diario', help='Coletar documentos do Diário Oficial')
    sp_diario.add_argument('--dias', type=int, default=3, help='Dias retroativos para coleta (padrão: 3)')

    # Processar documentos
    subparsers.add_parser('processar_documentos', help='Processar documentos pendentes')

    # Verificar normas SEFAZ
    subparsers.add_parser('verificar_normas', help='Verificar normas SEFAZ')

    # Coletar dados Receita Federal
    subparsers.add_parser('coletar_receita', help='Coletar dados da Receita Federal')

    # Pipeline automático
    sp_pipe = subparsers.add_parser('pipeline_auto', help='Executa pipeline automático (coleta/processa/verifica tudo)')
    sp_pipe.add_argument('--dias', type=int, default=3, help='Dias retroativos para coleta (padrão: 3)')

    # Pipeline manual
    sp_pipe_manual = subparsers.add_parser('pipeline_manual', help='Executa pipeline manual (datas customizadas)')
    sp_pipe_manual.add_argument('--inicio', required=True, help='Data início (YYYY-MM-DD)')
    sp_pipe_manual.add_argument('--fim', required=True, help='Data fim (YYYY-MM-DD)')

    # Gerar relatório
    subparsers.add_parser('gerar_relatorio', help='Gera relatório contábil avançado')

    # Comando para iniciar o worker do Celery
    subparsers.add_parser('start_celery', help='Inicia o worker do Celery em um novo terminal')
    # Comando para iniciar a API via WSL
    subparsers.add_parser('start_api', help='Inicia a API (calculadora) via WSL em um novo terminal')

    # Comando para consultar status/resultados de uma task Celery
    sp_status = subparsers.add_parser('status_task', help='Consulta o status/resultados de uma task Celery pelo Task ID')
    sp_status.add_argument('--id', required=True, help='Task ID do Celery')

    args = parser.parse_args()

    if args.comando == 'coletar_diario':
        res = coletar_diario_oficial_task.apply_async(kwargs={'dias_retroativos': args.dias})
        print(f"Task coletar_diario_oficial_task disparada! Task ID: {res.id}")
    elif args.comando == 'coletar_diario_todos':
        # Chama o scraper diretamente, ignorando filtro de termos
        from monitor.utils.diario_scraper import DiarioOficialScraper
        from datetime import timedelta
        dias = args.dias
        data_fim = None
        try:
            data_fim = django.utils.timezone.now().date()
        except Exception:
            from datetime import date
            data_fim = date.today()
        data_inicio = data_fim - timedelta(days=dias-1)
        print(f"Coletando TODOS os PDFs do Diário Oficial de {data_inicio} até {data_fim}...")
        scraper = DiarioOficialScraper()
        documentos = scraper.coletar_e_salvar_documentos(data_inicio=data_inicio, data_fim=data_fim, dias_retroativos=dias)
        print(f"Total de documentos salvos: {len(documentos)}")
    elif args.comando == 'processar_documentos':
        res = processar_documentos_pendentes_task.apply_async()
        print(f"Task processar_documentos_pendentes_task disparada! Task ID: {res.id}")
    elif args.comando == 'verificar_normas':
        res = verificar_normas_sefaz_task.apply_async()
        print(f"Task verificar_normas_sefaz_task disparada! Task ID: {res.id}")
    elif args.comando == 'coletar_receita':
        res = coletar_dados_receita_task.apply_async()
        print(f"Task coletar_dados_receita_task disparada! Task ID: {res.id}")
    elif args.comando == 'pipeline_auto':
        res = pipeline_coleta_e_processamento_automatica.apply_async(args=[args.dias])
        print(f"Pipeline automático disparado! Task ID: {res.id}")
    elif args.comando == 'pipeline_manual':
        res = pipeline_manual_completo.apply_async(args=[args.inicio, args.fim])
        print(f"Pipeline manual disparado! Task ID: {res.id}")
    elif args.comando == 'gerar_relatorio':
        res = gerar_relatorio_task.apply_async()
        print(f"Task gerar_relatorio_task disparada! Task ID: {res.id}")
    elif args.comando == 'start_celery':
        # Inicia o worker do Celery em um novo terminal
        import subprocess
        print("Iniciando o worker do Celery em um novo terminal...")
        subprocess.Popen([
            'start', 'cmd', '/k',
            f"cd /d {os.getcwd()} && venv311\\Scripts\\activate && celery -A diario_oficial worker -l info"
        ], shell=True)
        print("Worker do Celery iniciado!")
    elif args.comando == 'start_api':
        # Inicia a API via WSL em um novo terminal
        import subprocess
        print("Iniciando a API (calculadora) via WSL em um novo terminal...")
        subprocess.Popen([
            'start', 'cmd', '/k',
            "wsl -d calculadora --cd /calculadora --exec bash start.sh"
        ], shell=True)
        print("API (calculadora) iniciada!")
    elif args.comando == 'status_task':
        # Consulta status/resultados de uma task Celery
        from django_celery_results.models import TaskResult
        task_id = args.id
        try:
            task = TaskResult.objects.get(task_id=task_id)
            print(f"Status: {task.status}")
            print(f"Data de conclusão: {task.date_done}")
            print(f"Resultado: {task.result}")
            if task.traceback:
                print(f"Traceback:\n{task.traceback}")
        except TaskResult.DoesNotExist:
            print(f"Task ID {task_id} não encontrada no banco de resultados do Celery.")
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
