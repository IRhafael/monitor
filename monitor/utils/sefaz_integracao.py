import threading  
import os
import signal
import time
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Silencia completamente o TensorFlow
import re
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
from monitor.models import Documento, NormaVigente
from .sefaz_scraper import SEFAZScraper
from django.core.cache import cache
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from selenium.webdriver.support.ui import WebDriverWait

# Verifique se o cache está configurado no settings.py
if not hasattr(settings, 'CACHES'):
    raise ImproperlyConfigured("Por favor, configure o backend de cache no settings.py")

logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.scraper = SEFAZScraper()
        self.session_timeout = 600  # 10 minutos por sessão
        
    def __enter__(self):
        self.start_time = time.time()
        try:
            if not hasattr(self.scraper, 'driver') or not self.scraper.driver:
                self.scraper.init_driver()
        except Exception as e:
            logger.error(f"Erro ao iniciar driver: {str(e)}")
            raise
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.scraper.close()
        

    def check_chrome_version(self):
        try:
            self.driver.get("chrome://version/")
            version_text = WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(By.XPATH, "//*[contains(text(), 'Google Chrome')]").text
            )
            logger.info(f"Versão do Chrome: {version_text.split()[-1]}")
            return True
        except Exception:
            logger.warning("Não foi possível verificar a versão do Chrome")
            return False

    def buscar_norma_especifica(self, tipo, numero):
            """Versão mais robusta com tratamento de erros"""
            try:
                tipo = tipo.upper().strip()
                numero = self._padronizar_numero_norma(numero)
                
                logger.info(f"Verificando vigência de {tipo} {numero}")
                
                # Tenta usar cache primeiro
                cache_key = f"sefaz_{tipo}_{numero}"
                cached_result = cache.get(cache_key)
                CACHE_DURATION = {
                    'VIGENTE': 86400,  # 24 horas
                    'REVOGADA': 2592000,  # 30 dias
                    'ERRO': 3600  # 1 hora
                    }
                if cached_result:
                    return cached_result
                    
                # Verificação com timeout
                with self.scraper.browser_session():
                    vigente = self.scraper.check_norm_status(tipo, numero)
                    
                    resultado = {
                        'tipo': tipo,
                        'numero': numero,
                        'vigente': vigente.get('vigente', False) if isinstance(vigente, dict) else False,
                        'irregular': vigente.get('irregular', False) if isinstance(vigente, dict) else False,
                        'status': vigente.get('status', 'INDETERMINADO') if isinstance(vigente, dict) else 'ERRO',
                        'data_consulta': timezone.now()
                    }
                    
                    # Armazena no cache por 24 horas
                    cache.set(cache_key, resultado, CACHE_DURATION.get(resultado['status'], 3600))
                    return resultado
                    
            except Exception as e:
                logger.error(f"Erro ao buscar norma {tipo} {numero}: {str(e)}")
                return {
                    'tipo': tipo,
                    'numero': numero,
                    'vigente': False,
                    'irregular': False,
                    'status': 'ERRO',
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
        """Método otimizado com timeout e retry"""
        try:
            # Configura timeout
            signal.signal(signal.SIGALRM, self._handle_timeout)
            signal.alarm(self.timeout)
            
            resultado = self.scraper.check_norm_status(
                norma.tipo, 
                norma.numero
            )
            
            signal.alarm(0)  # Cancela timeout
            
            return {
                'status': resultado.get('status', 'INDETERMINADO'),
                'vigente': resultado.get('vigente', False),
                'irregular': resultado.get('irregular', False)
            }
            
        except Exception as e:
            logger.warning(f"Timeout/erro na norma {norma}: {str(e)}")
            return {
                'status': 'ERRO',
                'vigente': False,
                'irregular': False
            }

    def _handle_timeout(self, signum, frame):
        raise TimeoutError("Tempo excedido na consulta à SEFAZ")

    def _formatar_resultado_para_json(self, resultado):
        """Garante que todos os campos datetime são convertidos para strings"""
        if isinstance(resultado, dict):
            for key, value in resultado.items():
                if isinstance(value, datetime):
                    resultado[key] = value.isoformat()
        return resultado

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
    
    def verificar_normas_em_lote(self, normas, batch_size=10):
        """Processamento em lote com gerenciamento de tempo"""
        resultados = []
        normas_verificadas = 0
        
        try:
            for i in range(0, len(normas), batch_size):
                batch = normas[i:i + batch_size]
                
                # Verifica timeout global
                if time.time() - self.start_time > self.session_timeout:
                    raise TimeoutError("Tempo máximo de sessão excedido")
                
                for norma in batch:
                    try:
                        resultado = self.scraper.check_norm_status(norma.tipo, norma.numero)
                        resultados.append(resultado)
                        normas_verificadas += 1
                    except Exception as e:
                        logger.error(f"Erro na norma {norma}: {str(e)}")
                        continue
                        
                # Pausa estratégica entre batches
                time.sleep(1)
                
            return resultados
        finally:
            self.scraper.close()

    def _validar_status_norma(self, norma, status_response):
        # Se a resposta for apenas um booleano, precisamos melhorar o scraper para retornar mais detalhes
        if isinstance(status_response, bool):
            # Neste caso, confiamos na verificação básica, mas registramos para futura melhoria
            logger.info(f"Validação simplificada para norma {norma} - considerar aprimorar o scraper")
            return status_response
        
        # Se recebemos um objeto com mais detalhes, podemos fazer verificações mais robustas
        try:
            # Verificar se há indicadores de norma irregular
            # Exemplos (ajuste conforme a estrutura real de seus dados):
            if hasattr(status_response, 'status_text'):
                texto_status = status_response.status_text.lower()
                if any(termo in texto_status for termo in ["revogad", "cancelad", "substituíd", "irregular", "inválid"]):
                    return False
            
            # Verificar data de validade, se disponível
            if hasattr(status_response, 'data_vigencia_final') and status_response.data_vigencia_final:
                data_final = status_response.data_vigencia_final
                if data_final < timezone.now().date():
                    return False
            
            # Verificar status numérico, se aplicável
            if hasattr(status_response, 'status_code'):
                # Supondo que códigos diferentes de 1 indicam que não está vigente
                if status_response.status_code != 1:
                    return False
            
            # Se passou por todas as verificações
            return True
        
        except Exception as e:
            logger.error(f"Erro na validação avançada para norma {norma}: {e}", exc_info=True)
            # Em caso de erro na validação avançada, usar a verificação simples como fallback
            return bool(status_response)
        

    # Adicione estes métodos à classe IntegradorSEFAZ:
    def verificar_norma_individual_com_timeout(self, norma, timeout=120):
        """Verificação com timeout individual para cada norma"""
        start_time = time.time()
        result = None
        
        try:
            # Implementação com thread para timeout
            def worker():
                nonlocal result
                result = self.scraper.check_norm_status(norma.tipo, norma.numero)
            
            thread = threading.Thread(target=worker)
            thread.daemon = True
            thread.start()
            thread.join(timeout)
            
            if thread.is_alive():
                raise TimeoutError(f"Timeout após {timeout} segundos")
                
            return result
            
        except Exception as e:
            logger.error(f"Erro ao verificar norma {norma}: {str(e)}")
            return {
                'status': 'ERRO',
                'error': str(e),
                'norma': f"{norma.tipo} {norma.numero}"
            }

    # Substitua o método verificar_normas_em_lote por esta versão mais robusta:
    def verificar_normas_em_lote(self, normas, batch_size=5):
        """Processamento em lote com gerenciamento de tempo"""
        resultados = []
        
        try:
            with self.scraper.browser_session():
                for norma in normas:
                    try:
                        # Verificação individual com timeout
                        resultado = self.verificar_norma_individual_com_timeout(norma)
                        resultados.append(resultado)
                        
                        # Pequena pausa entre verificações
                        time.sleep(0.5)
                        
                    except Exception as e:
                        logger.error(f"Erro na norma {norma}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.error(f"Erro no lote: {str(e)}")
            
        return resultados




# Adicione esta classe
class CircuitBreaker:
    def __init__(self, max_failures=3, reset_timeout=300):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure = None
        
    def is_open(self):
        if self.failures >= self.max_failures:
            if time.time() - self.last_failure > self.reset_timeout:
                self.reset()
                return False
            return True
        return False
        
    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        
    def reset(self):
        self.failures = 0
        self.last_failure = None