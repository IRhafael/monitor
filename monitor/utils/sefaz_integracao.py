import os
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

# Verifique se o cache está configurado no settings.py
if not hasattr(settings, 'CACHES'):
    raise ImproperlyConfigured("Por favor, configure o backend de cache no settings.py")

logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.scraper = SEFAZScraper()
        self.max_tentativas = 3
        self.timeout = 60
        self.browser_session = None

    def __enter__(self):
        """Implementação para uso com 'with'"""
        self.browser_session = self.scraper.browser_session()
        self.browser_session.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Garante que a sessão seja fechada corretamente"""
        if self.browser_session:
            self.browser_session.__exit__(exc_type, exc_val, exc_tb)
            self.browser_session = None

    def buscar_norma_especifica(self, tipo, numero):
            """Versão mais robusta com tratamento de erros"""
            try:
                tipo = tipo.upper().strip()
                numero = self._padronizar_numero_norma(numero)
                
                logger.info(f"Verificando vigência de {tipo} {numero}")
                
                # Tenta usar cache primeiro
                cache_key = f"sefaz_{tipo}_{numero}"
                cached_result = cache.get(cache_key)
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
                    cache.set(cache_key, resultado, 86400)
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
        """Método otimizado que tenta várias estratégias para verificar a norma"""
        cache_key = f"sefaz_{norma.tipo}_{norma.numero}"
        
        # 1. Tentar cache
        cached = cache.get(cache_key)
        if cached and (timezone.now() - cached['data_consulta']) < timedelta(hours=12):
            return self._formatar_resultado_para_json(cached)
            
        # 2. Verificação via scraper
        try:
            resultado = self.scraper.check_norm_status(norma.tipo, norma.numero)
            
            # Garantir que o resultado não é None
            if resultado is None:
                raise ValueError("Resposta do scraper é None")
                
            # Formatar resultado consistentemente
            if not isinstance(resultado, dict):
                resultado = {
                    'vigente': bool(resultado),
                    'irregular': False,
                    'status': 'VIGENTE' if resultado else 'REVOGADA',
                    'data_consulta': timezone.now().isoformat()  # Serializa datetime para string
                }
            else:
                # Garantir que datas são strings
                if 'data_consulta' in resultado and isinstance(resultado['data_consulta'], datetime):
                    resultado['data_consulta'] = resultado['data_consulta'].isoformat()
            
            # Armazena no cache
            cache.set(cache_key, resultado, 43200)  # 12 horas
            return resultado
            
        except Exception as e:
            logger.error(f"Erro ao verificar norma {norma}: {e}")
            return {
                'tipo': norma.tipo,
                'numero': norma.numero,
                'vigente': False,
                'irregular': False,
                'status': 'ERRO',
                'erro': str(e),
                'data_consulta': timezone.now().isoformat()  # Serializa datetime
            }

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
        """Versão com tratamento completo de erros"""
        resultados = []
        try:
            with self.scraper.browser_session():
                for norma in normas:
                    try:
                        # Verificação segura
                        if not hasattr(norma, 'tipo') or not hasattr(norma, 'numero'):
                            continue
                            
                        resultado = self._verificar_norma_eficiente(norma)
                        
                        # Garante que temos um dicionário válido
                        if not isinstance(resultado, dict):
                            resultado = {
                                'vigente': False,
                                'irregular': False,
                                'status': 'ERRO',
                                'error': 'Resultado inválido'
                            }
                        
                        # Atualização segura da norma
                        norma.situacao = resultado.get('status', 'INDETERMINADO')
                        norma.data_verificacao = timezone.now()
                        
                        # Remove campos datetime antes de salvar
                        if 'data_consulta' in resultado:
                            resultado['data_consulta'] = str(resultado['data_consulta'])
                        
                        norma.detalhes = resultado
                        norma.save()
                        resultados.append(norma)
                        
                    except Exception as e:
                        logger.error(f"Erro ao processar norma {norma}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.error(f"Erro na sessão do browser: {str(e)}")
            
        return resultados

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
