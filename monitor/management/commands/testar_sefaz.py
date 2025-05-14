from django.core.management.base import BaseCommand
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from django.utils import timezone
import time

class Command(BaseCommand):
    help = 'Testa apenas a integração com o portal da SEFAZ'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== INICIANDO TESTE SEFAZ ==='))
        
        integrador = IntegradorSEFAZ()
        
        # 1. Teste de conexão básica
        self.stdout.write('\n1. Testando conexão com o portal...')
        start_time = time.time()
        try:
            if integrador.scraper.testar_conexao():
                elapsed = time.time() - start_time
                self.stdout.write(self.style.SUCCESS(f'✅ Conexão bem-sucedida ({elapsed:.2f}s)'))
            else:
                self.stdout.write(self.style.ERROR('❌ Falha na conexão'))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro na conexão: {str(e)}'))
            return

        # 2. Teste com normas de exemplo
        normas_teste = [
            ('LEI', '1234/2020'),
            ('DECRETO', '4567/2021'),
            ('PORTARIA', '8910/2022')
        ]
        
        self.stdout.write('\n2. Testando verificação de vigência:')
        for tipo, numero in normas_teste:
            start_time = time.time()
            try:
                resultado = integrador.buscar_norma_especifica(tipo, numero)
                elapsed = time.time() - start_time
                
                status = "VIGENTE" if resultado['vigente'] else "REVOGADA"
                msg = f"- {tipo} {numero}: {status} ({elapsed:.2f}s)"
                
                if 'erro' in resultado:
                    self.stdout.write(self.style.WARNING(msg + f" | Erro: {resultado['erro']}"))
                else:
                    self.stdout.write(self.style.SUCCESS(msg))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"- ❌ Falha ao verificar {tipo} {numero}: {str(e)}"))

        # 3. Teste de cache
        self.stdout.write('\n3. Testando sistema de cache:')
        norma_teste = ('LEI', '9999/2023')
        try:
            # Primeira consulta (deve ir ao site)
            start_time = time.time()
            resultado1 = integrador.buscar_norma_especifica(*norma_teste)
            elapsed1 = time.time() - start_time
            
            # Segunda consulta (deve usar cache)
            start_time = time.time()
            resultado2 = integrador.buscar_norma_especifica(*norma_teste)
            elapsed2 = time.time() - start_time
            
            self.stdout.write(f"- Primeira consulta: {elapsed1:.2f}s")
            self.stdout.write(f"- Segunda consulta: {elapsed2:.2f}s")
            
            if elapsed2 < elapsed1 * 0.5:  # Cache deve ser pelo menos 2x mais rápido
                self.stdout.write(self.style.SUCCESS("✅ Cache funcionando corretamente"))
            else:
                self.stdout.write(self.style.WARNING("⚠️ Cache pode não estar funcionando como esperado"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Erro no teste de cache: {str(e)}"))

        self.stdout.write(self.style.SUCCESS('\n=== TESTE CONCLUÍDO ==='))