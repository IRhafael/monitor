# monitor/utils/sefaz_integracao.py
import re
from datetime import datetime
from venv import logger
from .diario_scraper import DiarioOficialScraper
from .sefaz_scraper import SEFAZScraper
from ..models import Documento, NormaVigente

class IntegradorSEFAZ:
    BASE_URL = "https://www.sefaz.pi.gov.br"
    
    """
    Classe para integrar dados entre Diário Oficial e SEFAZ
    """
    def buscar_norma_especifica(self, tipo, numero):
        scraper = SEFAZScraper()
        vigente = scraper.verificar_vigencia_norma(tipo, numero)
    
        return {
            'tipo': tipo.upper(),
            'numero': self._padronizar_numero_norma(numero),
            'vigente': vigente
        }
    
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
    def extrair_normas_do_texto(self, texto):
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução)\s+(n?[º°]?\s*[.-]?\s*\d+[/-]?\d*)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO)\s+(N?[º°]?\s*[.-]?\s*\d+[/-]?\d*)'
        ]
        
        normas = []
        for padrao in padroes:
            matches = re.finditer(padrao, texto, re.IGNORECASE)
            for match in matches:
                tipo = match.group(1).upper()
                numero = re.sub(r'\s+', '', match.group(2))  # Remove todos os espaços
                numero = re.sub(r'[º°]', 'º', numero)  # Padroniza símbolo de ordinal
                normas.append((tipo, numero))
        
        return list(set(normas))  # Remove duplicatas

    def verificar_vigencia_normas(self, documento_id):
        documento = Documento.objects.get(pk=documento_id)
        normas_do_documento = self.extrair_normas_do_texto(documento.texto_completo)
        normas_vigentes = []
        
        for tipo, numero in normas_do_documento:
            # Verifica no cache/local primeiro
            norma = NormaVigente.objects.filter(
                tipo__iexact=tipo,
                numero__iexact=numero
            ).first()
            
            if norma:
                normas_vigentes.append(norma)
                continue
                
            # Verificação real na SEFAZ
            try:
                scraper = SEFAZScraper()
                vigente = scraper.verificar_vigencia_norma(tipo, numero)
                
                nova_norma = NormaVigente.objects.create(
                    tipo=tipo,
                    numero=numero,
                    data=datetime.now().date(),
                    situacao="VIGENTE" if vigente else "NAO_ENCONTRADA",
                    fonte="SEFAZ" if vigente else "DIARIO_OFICIAL"
                )
                normas_vigentes.append(nova_norma)
            except Exception as e:
                logger.error(f"Erro ao verificar norma {tipo} {numero}: {str(e)}")
        
        return normas_vigentes
    

    def _padronizar_numero_norma(self, numero):
        """Padroniza o formato do número da norma"""
        numero = numero.upper()
        # Remove caracteres especiais e espaços extras
        numero = re.sub(r'[^\d/]', '', numero)
        return numero.strip()

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
    

    def comparar_mudancas(self, dias_retroativos=30):
        from datetime import datetime, timedelta
        """
        Compara as normas do Diário Oficial com as da SEFAZ e identifica mudanças
        Args:
            dias_retroativos: número de dias para analisar (padrão: 30)
        """
        data_corte = datetime.now() - timedelta(days=dias_retroativos)
        
        # Normas vigentes na SEFAZ
        normas_sefaz = NormaVigente.objects.filter(fonte="SEFAZ", situacao="VIGENTE")
        
        # Normas mencionadas em documentos recentes
        normas_diario = set()
        documentos_recentes = Documento.objects.filter(
            data_publicacao__gte=data_corte,
            relevante_contabil=True
        )
        
        for doc in documentos_recentes:
            normas = self.extrair_normas_do_texto(doc.texto_completo)
            normas_diario.update(normas)
        
        relatorio = {
            'novas_normas': [],
            'normas_revogadas': [],
            'normas_desatualizadas': []
        }
        
        # 1. Novas normas (no diário mas não na SEFAZ)
        for tipo, numero in normas_diario:
            if not normas_sefaz.filter(tipo__iexact=tipo, numero__iexact=numero).exists():
                relatorio['novas_normas'].append(f"{tipo} {numero}")
        
        # 2. Normas revogadas (na SEFAZ mas não mencionadas recentemente)
        for norma in normas_sefaz:
            if (norma.tipo.upper(), norma.numero) not in normas_diario:
                relatorio['normas_revogadas'].append({
                    'norma': str(norma),
                    'ultima_menção': self._obter_ultima_menção(norma)
                })
        
        return relatorio

    def _obter_ultima_menção(self, norma):
        """Obtém a última data em que a norma foi mencionada"""
        documentos = Documento.objects.filter(
            texto_completo__icontains=norma.numero,
            normas_relacionadas=norma
        ).order_by('-data_publicacao').first()
        
        return documentos.data_publicacao if documentos else "Nunca mencionada"