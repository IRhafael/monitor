# monitor/management/commands/testar_sefaz.py
from django.core.management.base import BaseCommand
from monitor.utils.sefaz_integracao import IntegradorSEFAZ

class Command(BaseCommand):
    help = 'Testa especificamente a integração com a SEFAZ'

    def handle(self, *args, **options):
        integrador = IntegradorSEFAZ()
        
        # Teste com normas conhecidas
        normas_teste = [
            ('LEI', ' 8.488/24'),
            ('DECRETO', '23.623/2025'),
            ('PORTARIA', '6/2025')
        ]
        
        for tipo, numero in normas_teste:
            resultado = integrador.buscar_norma_especifica(tipo, numero)
            status = "VIGENTE" if resultado['vigente'] else "REVOGADA"
            self.stdout.write(f"{tipo} {numero}: {status}")