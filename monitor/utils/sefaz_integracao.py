# monitor/utils/sefaz_integracao.py
import re
from datetime import datetime
from venv import logger

import spacy
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
    
    def extrair_normas_do_texto(self, texto):
        """Versão melhorada com spaCy"""
        if not hasattr(self, 'nlp'):
            self.nlp = spacy.load("pt_core_news_sm")
        
        doc = self.nlp(texto)
        normas = []
        
        # Padrão para encontrar sequências do tipo "Lei 1234"
        for match in self.norma_matcher(doc):
            span = doc[match[1]:match[2]]
            tipo = self._determinar_tipo_norma(span.text)
            numero = self._extrair_numero_norma(span.text)
            
            if tipo and numero:
                normas.append((tipo, numero))
        
        return list(set(normas))


    def verificar_vigencia_automatica(self):
        """Verifica normas não validadas nos últimos 30 dias"""
        from datetime import datetime, timedelta
        data_limite = datetime.now() - timedelta(days=30)
        
        normas = NormaVigente.objects.filter(
            Q(data_verificacao__lt=data_limite) | Q(data_verificacao__isnull=True),
            situacao="VIGENTE"
        )
        
        for norma in normas:
            vigente = self.buscar_norma_especifica(norma.tipo, norma.numero)
            norma.situacao = "VIGENTE" if vigente else "REVOGADA"
            norma.data_verificacao = datetime.now()
            norma.save()
    

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