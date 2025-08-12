import re
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from monitor.models import Documento, NormaVigente
from .sefaz_scraper import SEFAZScraper
from .enriquecedor import enriquecer_documento_dict
from django.core.cache import cache
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

# Verifique se o cache está configurado no settings.py
if not hasattr(settings, 'CACHES'):
    raise ImproperlyConfigured("Por favor, configure o backend de cache no settings.py")

logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self._scraper = None
        self.max_tentativas = 2
        self.timeout = 40

    @property
    def scraper(self):
        # Lazy load do scraper
        if self._scraper is None:
            self._scraper = SEFAZScraper()
        return self._scraper

    def buscar_norma_especifica(self, tipo, numero):
        try:
            tipo = tipo.upper().strip()
            numero = self._padronizar_numero_norma(numero)
            logger.info(f"Verificando vigência de {tipo} {numero}")
            cache_key = f"sefaz_{tipo}_{numero}"
            cached_result = cache.get(cache_key)
            if cached_result:
                return cached_result
            # Primeiro tenta o método rápido (requests+BeautifulSoup)
            vigente_rapido = self.scraper.verificar_vigencia_rapida(tipo, numero)
            if vigente_rapido is not None:
                resultado = {
                    'tipo': tipo,
                    'numero': numero,
                    'vigente': bool(vigente_rapido),
                    'data_consulta': timezone.now(),
                    'detalhes': {'metodo': 'rapido', 'vigente': bool(vigente_rapido)}
                }
                cache.set(cache_key, resultado, 86400)
                return resultado
            # Se não conseguir, cai no Selenium
            vigente_info = self.scraper.check_norm_status(tipo, numero)
            resultado = {
                'tipo': tipo,
                'numero': numero,
                'vigente': vigente_info.get('vigente', False) if isinstance(vigente_info, dict) else bool(vigente_info),
                'data_consulta': timezone.now(),
                'detalhes': vigente_info if isinstance(vigente_info, dict) else {}
            }
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
        documento = Documento.objects.get(id=documento_id)
        normas_verificadas = []
        for norma in documento.normas_relacionadas.all():
            try:
                resultado = self.buscar_norma_especifica(norma.tipo, norma.numero)
                norma.situacao = "VIGENTE" if resultado['vigente'] else "REVOGADA"
                norma.data_verificacao = timezone.now()
                # Atualiza metadados se disponíveis
                if 'detalhes' in resultado and resultado['detalhes']:
                    if hasattr(norma, 'metadados') and isinstance(norma.metadados, dict):
                        norma.metadados.update(resultado['detalhes'])
                    else:
                        norma.metadados = resultado['detalhes']
                norma.save()
                normas_verificadas.append(norma)
            except Exception as e:
                logger.error(f"Erro ao verificar norma {norma}: {str(e)}")
                continue
        # Enriquecimento do documento após atualização das normas
        doc_dict = documento.to_dict() if hasattr(documento, 'to_dict') else documento.__dict__
        doc_dict = enriquecer_documento_dict(doc_dict)
        for k, v in doc_dict.items():
            if hasattr(documento, k):
                setattr(documento, k, v)
        documento.verificado_sefaz = True
        documento.data_verificacao = timezone.now()
        documento.save()
        return normas_verificadas

    def verificar_documentos_nao_verificados(self):
        documentos = Documento.objects.filter(verificado_sefaz=False)
        logger.info(f"Verificando {documentos.count()} documentos na SEFAZ")
        resultados = []
        for doc in documentos:
            try:
                normas = self.verificar_vigencia_normas(doc.id)
                # Enriquecimento e atualização do documento
                doc_dict = doc.to_dict() if hasattr(doc, 'to_dict') else doc.__dict__
                doc_dict = enriquecer_documento_dict(doc_dict)
                for k, v in doc_dict.items():
                    if hasattr(doc, k):
                        setattr(doc, k, v)
                doc.verificado_sefaz = True
                doc.data_verificacao = timezone.now()
                doc.save()
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
            # Enriquecimento do documento após atualização das normas prioritárias
            doc_dict = documento.to_dict() if hasattr(documento, 'to_dict') else documento.__dict__
            doc_dict = enriquecer_documento_dict(doc_dict)
            for k, v in doc_dict.items():
                if hasattr(documento, k):
                    setattr(documento, k, v)
            documento.verificado_sefaz = True
            documento.data_verificacao = timezone.now()
            documento.save()
            return normas_verificadas
        except Exception as e:
            logger.error(f"Erro em verificar_vigencia_automatica: {str(e)}")
            return []

    def _verificar_norma_eficiente(self, norma):
        try:
            cache_key = f"sefaz_{norma.tipo}_{norma.numero}"
            cached = cache.get(cache_key)
            if cached and (timezone.now() - cached['data_consulta']) < timedelta(hours=12):
                logger.debug(f"Cache encontrado para {norma.tipo} {norma.numero}")
            try:
                vigente = self.scraper.verificar_vigencia_rapida(norma.tipo, norma.numero)
                cache.set(cache_key, {
                    'vigente': vigente,
                    'data_consulta': timezone.now()
                }, 43200)
                return vigente
            except Exception as e:
                logger.warning(f"Falha no método rápido para {norma}: {str(e)}")
            vigente = self.scraper.verificar_vigencia_norma(norma.tipo, norma.numero)
            cache.set(cache_key, {
                'vigente': vigente if vigente is not None else False,
                'data_consulta': timezone.now()
            }, 43200)
            return vigente
        except Exception as e:
            logger.error(f"Falha crítica ao verificar norma {norma.tipo} {norma.numero}: {str(e)}", exc_info=True)
        return False

    def _determinar_tipo_norma(self, texto):
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
        match = re.search(r'(\d+[/-]?\d*)', texto)
        return re.sub(r'[^\d/]', '', match.group(1)) if match else None

    def extrair_normas_do_texto(self, texto):
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
        numero = re.sub(r'[^\d/]', '', str(numero))
        return numero.strip()

    def verificar_normas_em_lote(self, normas, batch_size=2):  # batch_size menor para evitar lentidão
        resultados = []
        with transaction.atomic():
            for norma in normas:
                try:
                    if not self._norma_e_valida(norma):
                        NormaVigente.objects.filter(pk=norma.pk).update(
                            situacao="DADOS_INVALIDOS",
                            data_verificacao=timezone.now()
                        )
                        norma.situacao = "DADOS_INVALIDOS"
                        norma.data_verificacao = timezone.now()
                    else:
                        NormaVigente.objects.filter(pk=norma.pk).update(
                            situacao="EM_VERIFICACAO"
                        )
                        norma.situacao = "EM_VERIFICACAO"
                except Exception as e:
                    logger.error(f"Erro ao classificar norma {norma}: {str(e)}")
                    continue
        # Processa em lotes menores para não travar o browser
        normas_para_verificar = [n for n in normas if n.situacao == "EM_VERIFICACAO"]
        for i in range(0, len(normas_para_verificar), batch_size):
            batch = normas_para_verificar[i:i+batch_size]
            with self.scraper.browser_session():
                for norma in batch:
                    try:
                        resultado = self.scraper.check_norm_status(norma.tipo, norma.numero)
                        nova_situacao = "VIGENTE" if resultado.get('status') == "VIGENTE" else "NAO_VIGENTE"
                        with transaction.atomic():
                            NormaVigente.objects.filter(pk=norma.pk).update(
                                situacao=nova_situacao,
                                data_verificacao=timezone.now()
                            )
                            norma.situacao = nova_situacao
                            norma.data_verificacao = timezone.now()
                        resultados.append(norma)
                    except Exception as e:
                        logger.error(f"Erro ao verificar norma {norma}: {str(e)}")
                        continue
        resultados.extend([n for n in normas if n.situacao == "DADOS_INVALIDOS"])
        return resultados

    def _norma_e_valida(self, norma):
        if not norma.tipo or not norma.numero:
            return False
        tipos_validos = ["LEI", "DECRETO", "PORTARIA", "ATO NORMATIVO", "MP", "LC", "RESOLUCAO"]
        if norma.tipo.upper() not in tipos_validos:
            return False
        if len(norma.numero.strip()) < 3:
            return False
        padrao_numero = re.compile(r'^(\d{1,4}[\/\-\.]?\d{0,4}|\d\/\d{2})$')
        if not padrao_numero.match(norma.numero):
            return False
        return True

def executar_teste_normas():
    integrador = IntegradorSEFAZ()

    NormaVigente.objects.filter(observacao__in=["TESTE_POSITIVO", "TESTE_NEGATIVO"]).delete()

    normas_validas = [
        NormaVigente(tipo="LEI", numero="4257", observacao="TESTE_POSITIVO"),
        NormaVigente(tipo="DECRETO", numero="21866", observacao="TESTE_POSITIVO"),
        NormaVigente(tipo="ATO NORMATIVO", numero="25/21", observacao="TESTE_POSITIVO"),
        NormaVigente(tipo="PORTARIA", numero="1234", observacao="TESTE_POSITIVO"),
        NormaVigente(tipo="MP", numero="1/22", observacao="TESTE_POSITIVO"),
    ]

    normas_invalidas = [
        NormaVigente(tipo="CIRCULAR", numero="123", observacao="TESTE_NEGATIVO"),
        NormaVigente(tipo="LEI", numero="12", observacao="TESTE_NEGATIVO"),
        NormaVigente(tipo="DECRETO", numero="ABC123", observacao="TESTE_NEGATIVO"),
        NormaVigente(tipo="", numero="123/21", observacao="TESTE_NEGATIVO"),
        NormaVigente(tipo="PORTARIA", numero="", observacao="TESTE_NEGATIVO"),
    ]

    for norma in normas_validas + normas_invalidas:
        norma.data_verificacao = None
        norma.situacao = None
        norma.save()

    todas_normas = normas_validas + normas_invalidas
    resultados = integrador.verificar_normas_em_lote(todas_normas)

    print("\n=== RESULTADOS DO TESTE ===")
    for norma in resultados:
        print(f"{norma.tipo} {norma.numero} → {norma.situacao}")

    return resultados