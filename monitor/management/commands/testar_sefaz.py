from django.core.management.base import BaseCommand
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
import time
import json


class Command(BaseCommand):
    help = 'Testa especificamente a integração com a SEFAZ'

    def handle(self, *args, **options):
        integrador = IntegradorSEFAZ()
        
        # Teste com normas conhecidas
        normas_teste = [
            ('LEI', '8.488/24'),
            ('DECRETO', '23.623/2025'),
            ('PORTARIA', '6/2025'),
            ('LEI COMPLEMENTAR', '123/2020')
        ]
        
        for tipo, numero in normas_teste:
            self.stdout.write(f"\nVerificando {tipo} {numero}...")
            
            start_time = time.time()
            resultado = integrador.buscar_norma_especifica(tipo, numero)
            elapsed_time = time.time() - start_time
            
            status = "VIGENTE" if resultado.get('vigente', False) else "REVOGADA/NÃO ENCONTRADA"
            
            if 'erro' in resultado:
                self.stdout.write(self.style.ERROR(f"ERRO: {resultado['erro']}"))
            
            self.stdout.write(f"Resultado: {status} (Tempo: {elapsed_time:.2f}s)")
            self.stdout.write(f"Detalhes: {json.dumps(resultado, indent=2, default=str)}")