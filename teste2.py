# Script de teste (salve como test_relatorio.py na mesma pasta do manage.py)
"""
Teste para o sistema de relatórios com Mistral AI
"""

if __name__ == "__main__":
    import os
    import django
    from datetime import datetime, timedelta
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
    django.setup()
    
    from monitor.models import Documento, NormaVigente
    from monitor.utils.relatorio import RelatorioAvancado
    
    def gerar_dados_teste():
        """Gera dados de teste se não existirem"""
        if not Documento.objects.exists():
            Documento.objects.create(
                titulo="Portaria SECAP 123/2024 - Alteração regime de tributação",
                assunto="Modificação no regime especial de tributação para MEI",
                data_publicacao=datetime.now() - timedelta(days=5),
                relevante_contabil=True,
                processado=True
            )
            Documento.objects.create(
                titulo="Lei Complementar 192/2024 - Novas alíquotas ICMS",
                assunto="Ajuste nas alíquotas interestaduais de ICMS",
                data_publicacao=datetime.now() - timedelta(days=15),
                relevante_contabil=True,
                processado=True
            )
        
        if not NormaVigente.objects.exists():
            NormaVigente.objects.create(
                tipo="Lei Complementar",
                numero="192/2024",
                ementa="Altera alíquotas de ICMS para operações interestaduais",
                situacao="VIGENTE",
                data_verificacao=datetime.now().date()
            )
    
    print("🔄 Gerando dados de teste...")
    gerar_dados_teste()
    
    print("🚀 Iniciando geração de relatório...")
    relatorio = RelatorioAvancado()
    caminho = relatorio.gerar_relatorio_completo()
    
    print(f"✅ Relatório gerado com sucesso: {caminho}")
    print("👉 Verifique o arquivo Excel gerado na pasta de mídia do projeto")