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


logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.scraper = SEFAZScraper()
        self.max_tentativas = 2  # Reduzido para 2 tentativas
        self.cache = {}
        self.timeout = 40  # Timeout reduzido


    def buscar_norma_especifica(self, tipo, numero):
        """Verifica se uma norma específica está vigente na SEFAZ"""
        try:
            # Padroniza entrada
            tipo = tipo.upper().strip()
            numero = self._padronizar_numero_norma(numero)
            
            logger.info(f"Verificando vigência de {tipo} {numero}")
            
            # Verifica cache primeiro
            cache_key = f"{tipo}_{numero}"
            if cache_key in self.cache:
                return self.cache[cache_key]
                
            vigente = self.scraper.verificar_vigencia_norma(tipo, numero)
            
            resultado = {
                'tipo': tipo,
                'numero': numero,
                'vigente': vigente if vigente is not None else False,
                'data_consulta': timezone.now()
            }
            
            # Armazena no cache por 24 horas
            self.cache[cache_key] = resultado
            return resultado
            
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
        """Versão ultra-otimizada com cache persistente"""
        try:
            documento = Documento.objects.get(id=documento_id)
            if not documento.normas_relacionadas.exists():
                return []

            normas_verificadas = []
            
            for norma in documento.normas_relacionadas.all().order_by('tipo')[:10]:  # Limita a 10 normas
                try:
                    # Verificação com cache e timeout controlado
                    resultado = self._verificar_norma_com_cache(norma)
                    if resultado is not None:
                        norma.situacao = "VIGENTE" if resultado else "REVOGADA"
                        norma.data_verificacao = timezone.now()
                        norma.save()
                        normas_verificadas.append(norma)
                except Exception as e:
                    logger.error(f"Erro na norma {norma}: {str(e)}")
                    continue

            return normas_verificadas
            
        except Exception as e:
            logger.error(f"Erro geral: {str(e)}")
            return []
            
        except Exception as e:
            logger.error(f"Erro ao verificar vigência automática: {str(e)}")
            return []
        

    def _verificar_norma_com_cache(self, norma):
        """Verifica com cache e estratégia de fallback"""
        cache_key = f"{norma.tipo}_{norma.numero}"
        
        # Verifica cache primeiro (válido por 12 horas)
        if cache_key in self.cache:
            cache_data = self.cache[cache_key]
            if (timezone.now() - cache_data['timestamp']) < timedelta(hours=12):
                return cache_data['vigente']
        
        # Tenta verificação rápida
        try:
            resultado = self.scraper.verificar_vigencia_rapida(norma.tipo, norma.numero)
            self.cache[cache_key] = {
                'vigente': resultado,
                'timestamp': timezone.now()
            }
            return resultado
        except Exception as e:
            logger.warning(f"Falha no método rápido: {str(e)}")
            return None
        

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
        """Extrai normas mencionadas no texto"""
        if not texto:
            return []
            
        padroes = [
            r'(?i)(Lei|Decreto|Portaria|Instrução Normativa|Resolução)\s+(?:n?[º°]?\s*)?(\d+[\.\/-]?\d*)',
            r'(?i)(Lei Complementar)\s+(n?[º°]?\s*)?(\d+)',
            r'(?i)(Medida Provisória)\s+(n?[º°]?\s*)?(\d+)'
        ]
        
        normas = []
        for padrao in padroes:
            matches = re.finditer(padrao, texto)
            for match in matches:
                try:
                    tipo = self._determinar_tipo_norma(match.group(1))
                    numero = self._extrair_numero_norma(match.group(2))
                    if tipo and numero:
                        normas.append((tipo, numero))
                except (IndexError, AttributeError):
                    continue
                    
        return list(set(normas))

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