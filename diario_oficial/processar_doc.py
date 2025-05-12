#!/usr/bin/env python
"""Script para processar documentos do Diário Oficial"""

import os
import sys
import django
from pathlib import Path

# 1. Configuração inicial do ambiente
try:
    # Configura caminhos absolutos
    BASE_DIR = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(BASE_DIR))
    
    # Desativa Celery se não for necessário
    os.environ['DISABLE_CELERY'] = 'True'
    
    # Configura Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
    django.setup()
    
except Exception as e:
    print(f"⛔ Erro na configuração inicial: {e}")
    sys.exit(1)

# 2. Importações após Django configurado
try:
    from monitor.utils.pdf_processor import PDFProcessor
    from monitor.models import Documento
except ImportError as e:
    print(f"⛔ Erro ao importar módulos: {e}")
    sys.exit(1)

# 3. Função principal
def processar_documentos():
    """Processa todos os documentos não processados"""
    try:
        print("\n🔍 Verificando documentos...")
        processor = PDFProcessor()
        qtd_nao_processados = Documento.objects.filter(processado=False).count()
        
        if qtd_nao_processados == 0:
            print("✅ Nenhum documento novo para processar.")
            return
            
        print(f"📄 Documentos a processar: {qtd_nao_processados}")
        processor.processar_todos_documentos()
        
        # Verificação final
        qtd_processados = Documento.objects.filter(processado=True).count()
        print(f"\n🎉 Processamento concluído! Total processados: {qtd_processados}/{Documento.objects.count()}")
        
    except Exception as e:
        print(f"\n❌ Erro durante o processamento: {e}")
        sys.exit(1)

# 4. Ponto de entrada
if __name__ == "__main__":
    print("="*50)
    print("SISTEMA DE PROCESSAMENTO DE DOCUMENTOS")
    print("="*50)
    
    processar_documentos()



class SimplePDFProcessor:
    def processar_documento(self, documento):
        try:
            print(f"\nProcessando documento {documento.id}...")
            
            # Extração básica de texto
            texto = self.extrair_texto(documento.arquivo_pdf.path)
            if not texto:
                return False
                
            documento.texto_completo = texto
            documento.relevante_contabil = self.is_relevante(texto)
            documento.processado = True
            documento.save()
            return True
            
        except Exception as e:
            print(f"Erro no documento {documento.id}: {e}")
            return False

    def extrair_texto(self, caminho):
        try:
            with open(caminho, 'rb') as f:
                from PyPDF2 import PdfReader
                reader = PdfReader(f)
                return " ".join(page.extract_text() for page in reader.pages if page.extract_text())
        except Exception as e:
            print(f"Erro ao extrair texto: {e}")
            return ""

    def is_relevante(self, texto):
        termos = ['tribut', 'imposto', 'fiscal', 'ICMS', 'ISS', 'receita']
        return any(termo.lower() in texto.lower() for termo in termos)