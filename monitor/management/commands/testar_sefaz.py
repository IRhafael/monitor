from django.core.management.base import BaseCommand

def teste_rapido_shell():
    """
    Teste rápido para verificar apenas a busca via pesquisa avançada
    """
    from monitor.utils.sefaz_scraper import SEFAZScraper
    import logging
    import time
    
    # Configuração do logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    print("\n=== TESTE RÁPIDO DE PESQUISA SEFAZ ===")
    
    # Normas para testar
    normas_teste = [
        ("DECRETO", "23.741/2025"),  # Fake
        ("PORTARIA", "678/2023"),    # Real
        ("LEI", "8.488/24")          # Real
    ]
    
    scraper = SEFAZScraper()
    scraper.timeout = 30
    
    for tipo, numero in normas_teste:
        print(f"\n▶ Testando pesquisa para {tipo} {numero}:")
        
        try:
            # Inicia navegador apenas uma vez
            if not scraper.driver:
                scraper._iniciar_navegador()
                
            # Testa conexão primeiro
            if not scraper.testar_conexao_manual():
                print("❌ Falha na conexão")
                continue
                
            start_time = time.time()
            
            # Teste direto do método de pesquisa avançada
            print("Testando via pesquisa avançada...")
            resultado = scraper._verificar_via_pesquisa_avancada(tipo, numero)
            
            elapsed = time.time() - start_time
            print(f"⏱️ Tempo: {elapsed:.2f} segundos")
            
            if resultado is None:
                print("⚠️ Status indeterminado - Não encontrou resultados claros")
            elif resultado:
                print("✅ VIGENTE - Norma encontrada como vigente")
            else:
                print("❌ REVOGADA/NÃO ENCONTRADA")
                
        except Exception as e:
            print(f"💣 ERRO: {str(e)}")
        
    # Garante fechamento do navegador no final
    try:
        if scraper.driver:
            scraper._fechar_navegador()
    except:
        pass
            
    print("\n=== TESTE CONCLUÍDO ===")

# Adiciona o comando Django
class Command(BaseCommand):
    help = 'Executa teste rápido de pesquisa de normas na SEFAZ'

    def handle(self, *args, **kwargs):
        teste_rapido_shell()



