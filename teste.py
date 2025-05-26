# test_normas.py
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
import django
django.setup()

from monitor.models import NormaVigente
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from datetime import datetime, timedelta
import time

def criar_norma_testes():
    NormaVigente.objects.filter(descricao__startswith='[TESTE]').delete()
    
    dados_testes = [
        # Normas válidas
        {'tipo': 'DECRETO', 'numero': '21.866', 'descricao': '[TESTE] VP - Decreto válido'},
        {'tipo': 'LEI', 'numero': '4.257', 'descricao': '[TESTE] VP - Lei válida'},
        {'tipo': 'ATO NORMATIVO', 'numero': '25/21', 'descricao': '[TESTE] VP - Ato normativo válido'},
        # Normas inválidas
        {'tipo': 'INVALIDO', 'numero': '123', 'descricao': '[TESTE] FP - Tipo inválido'},
        {'tipo': 'DECRETO', 'numero': '1', 'descricao': '[TESTE] FP - Número muito curto'},
        {'tipo': 'DECRETO', 'numero': '999999', 'descricao': '[TESTE] FP - Número inexistente'},
    ]
    
    # Criação individual com bypass
    for dados in dados_testes:
        norma = NormaVigente(**dados, situacao='NAO_VERIFICADO')
        norma.save(force_insert=True)
    
    print(f"Criadas {len(dados_testes)} normas de teste (3 válidas e 3 inválidas)")

def executar_testes():
    integrador = IntegradorSEFAZ()
    
    # Seleciona apenas as normas de teste
    normas_teste = NormaVigente.objects.filter(descricao__startswith='[TESTE]').order_by('descricao')
    
    print("\n=== Iniciando testes ===")
    resultados = integrador.verificar_normas_em_lote(list(normas_teste))
    
    print("\n=== Resultados ===")
    for norma in normas_teste:

        norma.refresh_from_db()  # Atualiza com dados do banco
        status_color = "\033[92m" if norma.situacao == 'VIGENTE' else "\033[91m" if norma.situacao != 'NAO_VIGENTE' else "\033[93m"
        print(f"{norma.descricao.ljust(40)} | Tipo: {str(norma.tipo).ljust(10)} | Número: {str(norma.numero).ljust(8)} | Status: {status_color}{norma.situacao}\033[0m")
        
    # Estatísticas
    vp = normas_teste.filter(descricao__contains='VP', situacao='VIGENTE')
    fp = normas_teste.filter(descricao__contains='FP', situacao='VIGENTE')
    vn = normas_teste.filter(descricao__contains='FP').exclude(situacao='VIGENTE')
    fn = normas_teste.filter(descricao__contains='VP').exclude(situacao='VIGENTE')

    print("\n=== Estatísticas Detalhadas ===")
    print(f"\033[92mVerdadeiros Positivos (VP): {vp.count()}/{normas_teste.filter(descricao__contains='VP').count()}\033[0m")
    print(f"\033[91mFalsos Positivos (FP):     {fp.count()}/{normas_teste.filter(descricao__contains='FP').count()}\033[0m")
    print(f"\033[93mVerdadeiros Negativos (VN): {vn.count()}/{normas_teste.filter(descricao__contains='FP').count()}\033[0m")
    print(f"\033[91mFalsos Negativos (FN):     {fn.count()}/{normas_teste.filter(descricao__contains='VP').count()}\033[0m")

    # Sugestões de melhoria baseadas nos resultados
    if fp.count() > 0:
        print("\n\033[91mALERTA: Falsos positivos detectados! Verifique:\033[0m")
        for norma in fp:
            print(f"- {norma.descricao} (Tipo: {norma.tipo}, Número: {norma.numero})")
        print("\nRecomendações:")
        print("1. Aumente a validação no método _norma_e_valida()")
        print("2. Revise os critérios de vigência no SEFAZScraper")

    if fn.count() > 0:
        print("\n\033[91mALERTA: Falsos negativos detectados! Verifique:\033[0m")
        for norma in fn:
            print(f"- {norma.descricao} (Tipo: {norma.tipo}, Número: {norma.numero})")
        print("\nRecomendações:")
        print("1. Verifique se as normas existem no portal SEFAZ")
        print("2. Ajuste os critérios de verificação de vigência")

def limpar_testes():
    deleted_count = NormaVigente.objects.filter(descricao__startswith='[TESTE]').delete()[0]
    print(f"\033[93m{deleted_count} normas de teste removidas\033[0m")

if __name__ == '__main__':
    print("\n=== Teste de Verificação de Normas ===")
    print("1. Criar normas de teste")
    print("2. Executar testes")
    print("3. Limpar testes")
    print("4. Sair")
    
    while True:
        opcao = input("\nSelecione uma opção (1-4): ").strip()
        
        if opcao == '1':
            criar_norma_testes()
        elif opcao == '2':
            executar_testes()
        elif opcao == '3':
            limpar_testes()
        elif opcao == '4':
            print("Encerrando...")
            break
        else:
            print("\033[91mOpção inválida. Tente novamente.\033[0m")