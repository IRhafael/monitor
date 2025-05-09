# monitor/utils/sefaz_integracao.py
import re
from datetime import datetime
from .diario_scraper import DiarioOficialScraper
from .sefaz_scraper import SEFAZScraper
from ..models import Documento, NormaVigente

class IntegradorSEFAZ:
    """
    Classe para integrar dados entre Diário Oficial e SEFAZ
    """
    
    @staticmethod
    def extrair_normas_do_texto(texto):
        """
        Extrai referências a normas do texto do documento
        """
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução)\s+(n?[º°]?\s*\.?\s*\d+[\.\-\d]*)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO)\s+(N?[º°]?\s*\.?\s*\d+[\.\-\d]*)'
        ]
        
        normas = []
        for padrao in padroes:
            matches = re.finditer(padrao, texto, re.IGNORECASE)
            for match in matches:
                tipo = match.group(1).upper()
                numero = match.group(2).replace(" ", "").replace(".", "")
                normas.append((tipo, numero))
        
        return list(set(normas))  # Remove duplicatas

    def verificar_vigencia_normas(self, documento_id):
        """
        Verifica se as normas mencionadas em um documento estão vigentes na SEFAZ
        """
        documento = Documento.objects.get(pk=documento_id)
        normas_do_documento = self.extrair_normas_do_texto(documento.texto_completo)
        
        normas_vigentes = []
        
        for tipo, numero in normas_do_documento:
            # Verifica se a norma já existe no banco de dados
            norma = NormaVigente.objects.filter(
                tipo__iexact=tipo,
                numero__iexact=numero
            ).first()
            
            if norma:
                normas_vigentes.append(norma)
            else:
                # Se não encontrou, verifica no site da SEFAZ
                scraper = SEFAZScraper()
                norma_sefaz = scraper.buscar_norma_especifica(tipo, numero)
                
                if norma_sefaz:
                    # Cria novo registro de norma vigente
                    nova_norma = NormaVigente.objects.create(
                        tipo=tipo.upper(),
                        numero=numero,
                        data=datetime.now().date(),
                        situacao="VIGENTE",
                        descricao=f"Norma mencionada no documento {documento.titulo}"
                    )
                    normas_vigentes.append(nova_norma)
        
        # Atualiza o documento com as normas relacionadas
        documento.normas_relacionadas.set(normas_vigentes)
        documento.verificado_sefaz = True
        documento.save()
        
        return normas_vigentes

    def verificar_documentos_nao_verificados(self):
        """
        Verifica todos os documentos que ainda não foram verificados na SEFAZ
        """
        documentos = Documento.objects.filter(verificado_sefaz=False)
        resultados = []
        
        for documento in documentos:
            try:
                normas = self.verificar_vigencia_normas(documento.id)
                resultados.append({
                    'documento': documento,
                    'normas_encontradas': len(normas),
                    'status': 'sucesso'
                })
            except Exception as e:
                resultados.append({
                    'documento': documento,
                    'erro': str(e),
                    'status': 'erro'
                })
        
        return resultados