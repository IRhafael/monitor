# monitor/utils/sefaz_integracao.py
import re
from datetime import datetime
from venv import logger
from .diario_scraper import DiarioOficialScraper
from .sefaz_scraper import SEFAZScraper
from ..models import Documento, NormaVigente

class IntegradorSEFAZ:
    
    """
    Classe para integrar dados entre Diário Oficial e SEFAZ
    """
    def __init__(self):
        self.cache = {}  # Simples cache em memória
        self.max_retries = 3

    def buscar_norma_com_cache(self, tipo, numero):
        cache_key = f"{tipo}_{numero}"
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        norma = self.buscar_norma_especifica(tipo, numero)
        if norma:
            self.cache[cache_key] = norma
        return norma
    
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
        documentos = Documento.objects.filter(verificado_sefaz=False)
        logger.info(f"Verificando {documentos.count()} documentos na SEFAZ")
        
        resultados = []
        for doc in documentos:
            try:
                logger.info(f"Verificando documento ID {doc.id} - {doc.titulo}")
                normas = self.verificar_vigencia_normas(doc.id)
                resultados.append({
                    'documento': doc,
                    'normas_encontradas': len(normas),
                    'status': 'sucesso'
                })
            except Exception as e:
                logger.error(f"Erro ao verificar documento ID {doc.id}: {str(e)}")
                resultados.append({
                    'documento': doc,
                    'erro': str(e),
                    'status': 'erro'
                })
        
        logger.info(f"Verificação na SEFAZ concluída. {len(resultados)} documentos processados")
        return resultados
    

    def comparar_mudancas(self):
        """
        Compara as normas do Diário Oficial com as da SEFAZ e identifica mudanças
        Retorna um relatório das mudanças encontradas
        """
        # 1. Obter todas as normas vigentes na SEFAZ
        normas_sefaz = NormaVigente.objects.all()
        
        # 2. Obter todas as normas mencionadas em documentos contábeis
        normas_diario = set()
        for doc in Documento.objects.filter(relevante_contabil=True):
            normas = self.extrair_normas_do_texto(doc.texto_completo)
            normas_diario.update(normas)
        
        # 3. Identificar diferenças
        relatorio = {
            'novas_normas': [],
            'normas_alteradas': [],
            'normas_revogadas': []
        }
        
        # Verificar normas no diário que não estão na SEFAZ (novas)
        for tipo, numero in normas_diario:
            if not NormaVigente.objects.filter(tipo__iexact=tipo, numero__iexact=numero).exists():
                relatorio['novas_normas'].append(f"{tipo} {numero}")
        
        # Verificar normas na SEFAZ que não estão no diário (potencialmente revogadas)
        for norma in normas_sefaz:
            if (norma.tipo.upper(), norma.numero) not in normas_diario:
                relatorio['normas_revogadas'].append(str(norma))
        
        return relatorio