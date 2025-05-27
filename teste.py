import os
import django
import pandas as pd
from datetime import datetime, timedelta

# Configuração do ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')  # Substitua pelo seu módulo de settings
django.setup()

from monitor.models import NormaVigente
from django.utils import timezone

def gerar_relatorio_completo():
    print("\n=== RELATÓRIO COMPLETO DE NORMAS ===")
    
    try:
        # Dados consolidados
        total_normas = NormaVigente.objects.count()
        normas_verificadas = NormaVigente.objects.exclude(data_verificacao__isnull=True)
        normas_nao_verificadas = NormaVigente.objects.filter(data_verificacao__isnull=True)
        
        # Cálculo de métricas
        vigentes = normas_verificadas.filter(situacao='VIGENTE').count()
        nao_vigentes = normas_verificadas.filter(situacao='NAO_VIGENTE').count()
        invalidas = normas_verificadas.filter(situacao='DADOS_INVALIDOS').count()
        
        # Coleta de dados para DataFrame
        dados = []
        for norma in NormaVigente.objects.all().only('id', 'tipo', 'numero', 'situacao', 'data_verificacao'):
            dados.append({
                'ID': norma.id,
                'Tipo': norma.tipo,
                'Número': norma.numero,
                'Situação': norma.situacao or 'NÃO VERIFICADA',
                'Última Verificação': norma.data_verificacao.strftime('%d/%m/%Y') if norma.data_verificacao else 'Nunca verificada',
                'Dias desde verificação': (timezone.now() - norma.data_verificacao).days if norma.data_verificacao else 'N/A'
            })
        
        df = pd.DataFrame(dados)
        
        # Exibir relatório
        print(f"\n🔍 Total de normas: {total_normas}")
        print(f"✅ Vigentes: {vigentes} | ❌ Não vigentes: {nao_vigentes}")
        print(f"⚠️ Inválidas: {invalidas} | � Não verificadas: {normas_nao_verificadas.count()}")
        
        print("\n📊 Distribuição por tipo:")
        print(df['Tipo'].value_counts().to_string())
        
        print("\n📅 Status por verificação:")
        print(pd.crosstab(df['Situação'], df['Última Verificação']))
        
        print("\n🧐 Normas que precisam de atenção:")
        print(df[df['Situação'].isin(['NAO_VIGENTE', 'DADOS_INVALIDOS'])].to_string(index=False))
        
        # Salvar relatório
        df.to_csv('relatorio_normas.csv', index=False)
        print("\n💾 Relatório salvo como 'relatorio_normas.csv'")
    
    except Exception as e:
        print(f"\n❌ Erro ao gerar relatório: {str(e)}")
        if 'df' in locals():
            print("\n⚠️ Dados parciais coletados:")
            print(df.head().to_string())

if __name__ == '__main__':
    gerar_relatorio_completo()