from monitor.utils.sefaz_scraper import SEFAZScraper
from bs4 import BeautifulSoup
import time

def testar_scraper():
    print("=== TESTE DO SCRAPER SEFAZ ===")

    # 1. Testar conexão
    scraper = SEFAZScraper()
    print("\n1. Testando conexão básica...")
    response = scraper.fazer_requisicao(scraper.base_url)
    if not response:
        print("Falha na conexão básica")
        return

    print(f"Status: {response.status_code}")
    print(f"Título: {BeautifulSoup(response.text, 'html.parser').title.text}")

    # 2. Testar com norma conhecida
    print("\n2. Testando norma específica...")
    testes = [
        ("LEI", "6683/2022"),
        ("PORTARIA", "5/2025"),
        ("DECRETO", "456/23.741/2025")
    ]

    for tipo, numero in testes:
        print(f"\nConsultando {tipo} {numero}...")
        vigente = scraper.verificar_vigencia_norma(tipo, numero)
        print(f"Resultado: {'VIGENTE' if vigente else 'NÃO ENCONTRADA'}")
        time.sleep(2)

# Chamada da função
testar_scraper()