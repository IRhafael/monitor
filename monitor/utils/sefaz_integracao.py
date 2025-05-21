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
from django.core.exceptions import ImproperlyConfigured

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


    # Modifique o método buscar_norma_especifica para usar check_norm_status diretamente
    def buscar_norma_especifica(self, tipo, numero):
        """Versão simplificada que usa check_norm_status diretamente"""
        try:
            tipo = tipo.upper().strip()
            numero = self._padronizar_numero_norma(numero)
            logger.info(f"Verificando vigência de {tipo} {numero}")
            
            # Verifica cache primeiro
            cache_key = f"sefaz_{tipo}_{numero}"
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result
                
            # Chama o método correto do scraper
            vigente = self.scraper.check_norm_status(tipo, numero)
            
            resultado = {
                'tipo': tipo,
                'numero': numero,
                'vigente': vigente if vigente is not None else False,
                'data_consulta': timezone.now()
            }
            
            # Armazena no cache
            cache.set(cache_key, resultado, 86400)
            return resultado
            
        except Exception as e:
            logger.error(f"Erro ao buscar norma: {str(e)}")
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
    
    def verificar_vigencia_normas_em_lote(self, lista_numeros):

        resultados = {}

        # Busca todas as normas vigentes no banco de dados cujo número esteja na lista
        normas = NormaVigente.objects.filter(numero__in=lista_numeros)

        for norma in normas:
            # Chamada ao método de verificação individual
            status = self.verificar_vigencia(norma.numero)
            resultados[norma.numero] = status

        # Considera como não vigentes os números não encontrados no banco
        numeros_encontrados = set(normas.values_list('numero', flat=True))
        numeros_nao_encontrados = set(lista_numeros) - numeros_encontrados
        for num in numeros_nao_encontrados:
            resultados[num] = False

        return resultados



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
       
        cache_key = f"sefaz_{norma.tipo}_{norma.numero}"
        try:
            cached = cache.get(cache_key)
            if cached:
                if isinstance(cached, dict) and 'vigente' in cached:
                    return cached['vigente']
                return cached
        except Exception as e:
            logger.warning(f"Erro ao acessar cache: {str(e)}")
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
        """Versão simplificada e mais robusta"""
        if not texto:
            return []

        padroes = [
            # Padrões existentes...
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
    

    # Adicione este método à classe IntegradorSEFAZ:
    def verificar_vigencia_com_detalhes(self, tipo, numero):
        """Versão que retorna tanto o status de vigência quanto os detalhes completos"""
        try:
            resultado = self.buscar_norma_especifica(tipo, numero)
            if isinstance(resultado, dict) and 'vigente' in resultado:
                # Se já temos os detalhes no cache
                return resultado['vigente'], resultado.get('detalhes', {})
            
            # Caso contrário, faz uma nova verificação detalhada
            with self.scraper.browser_session():
                vigente = self.scraper.verificar_vigencia(tipo, numero)
                detalhes = self.scraper._coletar_detalhes_norma() if vigente else {}
                
                # Atualiza o cache com os detalhes
                cache_key = f"sefaz_{tipo}_{numero}"
                cache.set(cache_key, {
                    'vigente': vigente,
                    'detalhes': detalhes,
                    'data_consulta': timezone.now()
                }, 86400)  # 24 horas
                
                return vigente, detalhes
                
        except Exception as e:
            logger.error(f"Erro ao verificar vigência com detalhes: {str(e)}")
            return False, {}
        
    def verificar_normas_em_lote(self, normas, batch_size=3):
        """Verifica um lote de normas de forma mais eficiente"""
        resultados = []
        with self.scraper.browser_session():
            for i in range(0, len(normas), batch_size):
                batch = normas[i:i + batch_size]
                for norma in batch:
                    try:
                        vigente = self.scraper.check_norm_status(norma.tipo, norma.numero)
                        norma.situacao = "VIGENTE" if vigente else "REVOGADA"
                        norma.data_verificacao = timezone.now()
                        norma.save()
                        resultados.append(norma)
                    except Exception as e:
                        logger.error(f"Erro na norma {norma}: {e}", exc_info=True)
        return resultados
