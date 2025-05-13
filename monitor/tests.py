from monitor.utils.sefaz_scraper import SEFAZScraper
import time

def testar_scraper():
    print("=== TESTE COMPLETO DO SEFAZ SCRAPER ===")
    
    scraper = SEFAZScraper()

    print("\n1. Verificação de vigência:")
    testes = [
        ("PORTARIA", "5/2025"),
        ("LEI", "6683/2022"),
        ("DECRETO", "123/2021")
    ]

    for tipo, numero in testes:
        print(f"\nConsultando {tipo} {numero}...")
        try:
            vigente = scraper.verificar_vigencia_norma(tipo, numero)
            print(f"Resultado: {'VIGENTE' if vigente else 'NÃO ENCONTRADA'}")
        except Exception as e:
            print(f"Erro: {e}")
        time.sleep(2)

    print("\n2. Coletando últimas normas...")
    normas = scraper.coletar_normas()
    print(f"Total de normas coletadas: {len(normas)}")

    if normas:
        print("\nPrimeiras 3 normas:")
        for norma in normas[:3]:
            print(f"- {norma['tipo']} {norma['numero']} ({norma['data']})")

    print("\n3. Executando coleta completa...")
    resultado = scraper.iniciar_coleta()
    print(f"Resultado: {resultado['status']}")
    print(f"Normas novas: {resultado.get('normas_novas', 0)}")

# Rodar diretamente
if __name__ == "__main__":
    testar_scraper()
