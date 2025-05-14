# monitor/utils/sefaz_integracao.py
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Silencia completamente o TensorFlow
import re
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
from monitor.models import Documento, NormaVigente
from .sefaz_scraper import SEFAZScraper
from selenium.common.exceptions import WebDriverException
import urllib.parse
from django.core.cache import cache
from django.conf import settings
# Verifique se o cache está configurado no settings.py
if not hasattr(settings, 'CACHES'):
    raise ImproperlyConfigured("Por favor, configure o backend de cache no settings.py")


logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.scraper = SEFAZScraper()
        self.max_tentativas = 2  # Reduzido para 2 tentativas
        #self.cache = {}
        self.timeout = 40  # Timeout reduzido


    def buscar_norma_especifica(self, tipo, numero):
        """Verifica se uma norma específica está vigente na SEFAZ"""
        try:
            tipo = tipo.upper().strip()
            numero = self._padronizar_numero_norma(numero)
            logger.info(f"Verificando vigência de {tipo} {numero}")
            
            # Verifica cache primeiro (usando Django cache)
            cache_key = f"sefaz_{tipo}_{numero}"
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result
                
            vigente = self.scraper.verificar_vigencia_norma(tipo, numero)
            
            resultado = {
                'tipo': tipo,
                'numero': numero,
                'vigente': vigente if vigente is not None else False,
                'data_consulta': timezone.now()
            }
            
            # Armazena no cache por 24 horas
            cache.set(cache_key, resultado, 86400)  # 24 horas em segundos
            return resultado
            
        except WebDriverException as e:
            logger.error(f"Erro de navegador ao buscar norma {tipo} {numero}: {str(e)}")
            return {
                'tipo': tipo,
                'numero': numero,
                'vigente': False,
                'erro': "Erro de conexão com o portal"
            }
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar norma {tipo} {numero}: {str(e)}")
            return {
                'tipo': tipo,
                'numero': numero,
                'vigente': False,
                'erro': str(e)
            }
            
        except Exception as e:
            logger.error(f"Erro ao buscar norma {tipo} {numero}: {str(e)}")
            return {
                'tipo': tipo,
                'numero': numero,
                'vigente': False,
                'erro': str(e)
            }



    def verificar_vigencia_normas(self, documento_id):
        """Versão melhorada para verificar múltiplas normas"""
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
        """Versão otimizada com batch processing"""
        try:
            documento = Documento.objects.get(id=documento_id)
            if not documento.normas_relacionadas.exists():
                return []

            normas_verificadas = []
            normas_para_verificar = documento.normas_relacionadas.all().order_by('tipo')[:15]  # Aumentado para 15
            
            for norma in normas_para_verificar:
                try:
                    # Usa verificação rápida com fallback
                    vigente = self._verificar_norma_eficiente(norma)
                    
                    norma.situacao = "VIGENTE" if vigente else "REVOGADA"
                    norma.data_verificacao = timezone.now()
                    norma.save()
                    normas_verificadas.append(norma)
                    
                except Exception as e:
                    logger.error(f"Erro na norma {norma}: {str(e)}")
                    continue

            return normas_verificadas
            
        except Documento.DoesNotExist:
            logger.error(f"Documento {documento_id} não encontrado")
            return []
        except Exception as e:
            logger.error(f"Erro geral em verificar_vigencia_automatica: {str(e)}")
            return []

    def _verificar_norma_eficiente(self, norma):
        """Estratégia de verificação em camadas"""
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
                }, 43200)  # 12 horas em segundos
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
            logger.error(f"Erro completo em _verificar_norma_eficiente para {norma}: {str(e)}")
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
        """Extrai normas mencionadas no texto com melhor precisão"""
        if not texto:
            return []
            
        padroes = [
            # Padrão para Leis Complementares
            r'(?i)(Lei\s+Complementar|LC)\s*(?:n?[º°]?\s*)?(\d+)',
            # Padrão para Medidas Provisórias
            r'(?i)(Medida\s+Provisória|MP)\s*(?:n?[º°]?\s*)?(\d+)',
            # Padrão genérico para outros tipos
            r'(?i)(Lei|Decreto|Portaria|Instrução Normativa|Resolução|Deliberação)\s+(?:n?[º°]?\s*)?(\d+[\/-]\d{2,4})',
            # Padrão para normas sem tipo explícito (apenas número)
            r'(?i)(?:n?[º°]\s*)?(\d+[\/-]\d{2,4})'
        ]
        
        normas_encontradas = set()
        
        for padrao in padroes:
            matches = re.finditer(padrao, texto)
            for match in matches:
                try:
                    grupos = match.groups()
                    if len(grupos) >= 2:  # Temos tipo e número
                        tipo = self._determinar_tipo_norma(grupos[0])
                        numero = self._extrair_numero_norma(grupos[1])
                    else:  # Apenas número
                        tipo = None
                        numero = self._extrair_numero_norma(grupos[0])
                    
                    if numero:
                        if not tipo:
                            # Tenta inferir o tipo pelo contexto
                            contexto = texto[max(0, match.start()-50):match.end()+50]
                            tipo = self._inferir_tipo_pelo_contexto(contexto) or "DESCONHECIDO"
                        
                        normas_encontradas.add((tipo, numero))
                except (IndexError, AttributeError) as e:
                    continue
                    
        return list(normas_encontradas)

    def comparar_mudancas(self, dias_retroativos=30):
        """
        Compara as normas do Diário Oficial com as da SEFAZ e identifica mudanças
        Args:
            dias_retroativos: número de dias para analisar (padrão: 30)
        """
        data_corte = timezone.now() - timedelta(days=dias_retroativos)
        
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
        documento = Documento.objects.filter(
            texto_completo__icontains=norma.numero,
            normas_relacionadas=norma
        ).order_by('-data_publicacao').first()
        
        return documento.data_publicacao.strftime("%d/%m/%Y") if documento else "Nunca mencionada"

    def _padronizar_numero_norma(self, numero):
        """Padroniza o formato do número da norma"""
        numero = re.sub(r'[^\d/]', '', str(numero))
        return numero.strip()
    
    def _inferir_tipo_pelo_contexto(self, contexto):
        contexto = contexto.lower()
        if 'lei complementar' in contexto or ' lc ' in contexto:
            return 'LC'
        elif 'decreto' in contexto:
            return 'DECRETO'
        elif 'portaria' in contexto:
            return 'PORTARIA'
        elif 'instrução normativa' in contexto:
            return 'INSTRUCAO NORMATIVA'
        return None

    def _eh_numero_valido(self, numero):
        """Verifica se o número parece ser uma norma válida"""
        partes = re.split(r'[/-]', numero)
        if len(partes) != 2:
            return False
        return partes[0].isdigit() and partes[1].isdigit()