import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Silencia completamente o TensorFlow
import re
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from monitor.models import Documento, NormaVigente
from .sefaz_scraper import SEFAZScraper
from django.core.cache import cache
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Verifique se o cache está configurado no settings.py
if not hasattr(settings, 'CACHES'):
    raise ImproperlyConfigured("Por favor, configure o backend de cache no settings.py")

logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.scraper = SEFAZScraper()
        self.max_tentativas = 2
        self.timeout = 40

    def buscar_norma_especifica(self, tipo, numero):
        """Verifica vigência de uma norma específica com tratamento robusto"""
        try:
            tipo = tipo.upper().strip()
            numero = self._padronizar_numero_norma(numero)
            logger.info(f"Verificando vigência de {tipo} {numero}")
            
            # Verifica cache primeiro
            cache_key = f"sefaz_{tipo}_{numero}"
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result
                
            # Chama o método do scraper
            resultado = self.scraper.check_norm_status(tipo, numero)
            
            if not resultado:
                raise ValueError("Nenhum resultado retornado pelo scraper")
                
            resultado_completo = {
                'tipo': tipo,
                'numero': numero,
                'vigente': resultado.get('vigente', False),
                'data_consulta': timezone.now(),
                'detalhes': resultado
            }
            
            # Armazena no cache
            cache.set(cache_key, resultado_completo, 86400)  # 24 horas
            return resultado_completo
            
        except Exception as e:
            logger.error(f"Erro ao buscar norma {tipo} {numero}: {str(e)}")
            return {
                'tipo': tipo,
                'numero': numero,
                'vigente': False,
                'erro': str(e),
                'data_consulta': timezone.now()
            }

    def verificar_vigencia_normas(self, documento_id):
        """Verifica múltiplas normas de um documento"""
        documento = Documento.objects.get(id=documento_id)
        normas_verificadas = []
        
        for norma in documento.normas_relacionadas.all():
            try:
                resultado = self.buscar_norma_especifica(norma.tipo, norma.numero)
                
                # Atualiza status da norma
                norma.situacao = "VIGENTE" if resultado['vigente'] else "REVOGADA"
                norma.data_verificacao = timezone.now()
                norma.save()
                
                normas_verificadas.append(norma)
                
            except Exception as e:
                logger.error(f"Erro ao verificar norma {norma}: {str(e)}")
                continue
                
        return normas_verificadas
    
    def verificar_documentos_nao_verificados(self):
        """Verifica todos os documentos não verificados"""
        documentos = Documento.objects.filter(verificado_sefaz=False)
        logger.info(f"Verificando {documentos.count()} documentos na SEFAZ")
        
        resultados = []
        for doc in documentos:
            try:
                normas = self.verificar_vigencia_normas(doc.id)
                resultados.append({
                    'documento': doc,
                    'normas_encontradas': len(normas),
                    'status': 'sucesso'
                })
            except Exception as e:
                resultados.append({
                    'documento': doc,
                    'erro': str(e),
                    'status': 'erro'
                })
        
        return resultados

    def verificar_vigencia_automatica(self, documento_id):
        try:
            documento = Documento.objects.get(id=documento_id)
            if not documento.normas_relacionadas.exists():
                return []

            # Prioriza normas dos termos monitorados
            normas_prioritarias = documento.normas_relacionadas.filter(
                Q(tipo='DECRETO', numero='21.866') |
                Q(tipo='LEI', numero='4.257') |
                Q(tipo='ATO NORMATIVO', numero__in=['25/21', '26/21', '27/21'])
            ).distinct()

            normas_verificadas = []
            for norma in normas_prioritarias:
                try:
                    vigente = self._verificar_norma_eficiente(norma)
                    norma.situacao = "VIGENTE" if vigente else "REVOGADA"
                    norma.data_verificacao = timezone.now()
                    norma.save()
                    normas_verificadas.append(norma)
                except Exception as e:
                    logger.error(f"Erro na norma {norma}: {str(e)}")
                    continue

            return normas_verificadas
            
        except Exception as e:
            logger.error(f"Erro em verificar_vigencia_automatica: {str(e)}")
            return []

    def _verificar_norma_eficiente(self, norma):
        """Método otimizado que tenta várias estratégias para verificar a norma"""
        try:
            # 1. Tentar cache
            cache_key = f"sefaz_{norma.tipo}_{norma.numero}"
            cached = cache.get(cache_key)
            if cached and (timezone.now() - cached['data_consulta']) < timedelta(hours=12):
                return cached['vigente']
            
            # 2. Tentar método rápido
            try:
                vigente = self.scraper.verificar_vigencia_rapida(norma.tipo, norma.numero)
                cache.set(cache_key, {
                    'vigente': vigente,
                    'data_consulta': timezone.now()
                }, 43200)  # 12 horas
                return vigente
            except Exception as e:
                logger.warning(f"Falha no método rápido para {norma}: {str(e)}")
            
            # 3. Método completo como fallback
            vigente = self.scraper.verificar_vigencia_norma(norma.tipo, norma.numero)
            cache.set(cache_key, {
                'vigente': vigente if vigente is not None else False,
                'data_consulta': timezone.now()
            }, 43200)
            return vigente
            
        except Exception as e:
            logger.error(f"Erro em _verificar_norma_eficiente para {norma}: {str(e)}")
            return False

    def _determinar_tipo_norma(self, texto):
        """Determina o tipo da norma com base no texto"""
        texto = texto.lower()
        
        if "lei complementar" in texto:
            return "LC"
        elif "medida provisória" in texto:
            return "MP"
        elif "portaria" in texto:
            return "PORTARIA"
        elif "decreto" in texto:
            return "DECRETO"
        elif "lei" in texto:
            return "LEI"
        return None

    def _extrair_numero_norma(self, texto):
        """Extrai o número da norma do texto"""
        match = re.search(r'(\d+[/-]?\d*)', texto)
        return re.sub(r'[^\d/]', '', match.group(1)) if match else None

    def extrair_normas_do_texto(self, texto):
        """Extrai normas do texto usando padrões específicos"""
        if not texto:
            return []

        padroes = [
            r'(?i)(Decreto)\s+(?:n?[º°]?\s*)?(21\.?866)',
            r'(?i)(Lei)\s+(?:n?[º°]?\s*)?(4\.?257)',
            r'(?i)(Ato Normativo)\s+(?:n?[º°]?\s*)?(2[5-7]/21)'
        ]
        
        normas = set()
        for padrao in padroes:
            for match in re.finditer(padrao, texto):
                try:
                    tipo = self._determinar_tipo_norma(match.group(1))
                    numero = self._padronizar_numero_norma(match.group(2))
                    if tipo and numero:
                        normas.add((tipo.upper(), numero))
                except (IndexError, AttributeError):
                    continue
                    
        return list(normas)

    def _padronizar_numero_norma(self, numero):
        """Padroniza o formato do número da norma"""
        numero = re.sub(r'[^\d/]', '', str(numero))
        return numero.strip()
    
    def verificar_normas_em_lote(self, normas):
        """Versão robusta com tratamento de erros completo"""
        resultados = []
        
        try:
            with self.scraper.browser_session():
                for norma in normas:
                    try:
                        # Extrai componentes da norma
                        tipo = norma.tipo.upper()
                        numero = self._padronizar_numero_norma(norma.numero)
                        
                        # Verifica a norma
                        resultado = self.scraper.check_norm_status(tipo, numero)
                        
                        # Processa resultado
                        if resultado:
                            vigente = resultado.get('vigente', False)
                            norma.situacao = 'VIGENTE' if vigente else 'REVOGADA'
                            norma.data_verificacao = timezone.now()
                            norma.fonte_confirmacao = 'SEFAZ' if resultado.get('sefaz') else 'BING'
                            norma.resumo_ia = resultado.get('resumo_ia')
                            norma.detalhes = resultado
                            norma.save()
                            
                            resultados.append(norma)
                        else:
                            logger.error(f"Resultado vazio para norma {norma.id}")
                            
                    except Exception as e:
                        logger.error(f"Erro ao processar norma {norma.id}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.error(f"Erro geral na verificação em lote: {str(e)}")
        
        return resultados

    def _extrair_components_norma(self, norma):
        """Extrai tipo, número e ano de uma norma"""
        tipo = norma.tipo.upper()
        numero = norma.numero
        
        # Extrai ano do formato "NÚMERO/ANO"
        if '/' in numero:
            partes = numero.split('/')
            if len(partes) == 2 and partes[1].isdigit():
                return tipo, partes[0], partes[1]
        
        return tipo, numero, None