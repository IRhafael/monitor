# monitor/utils/sefaz_integracao.py
import re
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q
from monitor.models import Documento, NormaVigente
from .sefaz_scraper import SEFAZScraper

logger = logging.getLogger(__name__)

class IntegradorSEFAZ:
    def __init__(self):
        self.cache = {}
        self.max_retries = 3
        self.scraper = SEFAZScraper()

    def buscar_norma_especifica(self, tipo, numero):
        """Verifica se uma norma específica está vigente na SEFAZ"""
        vigente = self.scraper.verificar_vigencia_norma(tipo, numero)
        return {
            'tipo': tipo.upper(),
            'numero': self._padronizar_numero_norma(numero),
            'vigente': vigente
        }



    def verificar_vigencia_norma(self, tipo, numero):
        """Versão melhorada com mais tentativas e logs detalhados"""
        for tentativa in range(1, self.max_retries + 1):
            try:
                if not self._iniciar_navegador():
                    logger.error("Falha ao iniciar navegador")
                    return False
                    
                logger.info(f"Verificando norma {tipo} {numero} (tentativa {tentativa})")
                
                # Codificação segura para URLs
                query = f"{tipo}+{numero}"
                url = f"{self.search_url}?q={urllib.parse.quote_plus(query)}"
                self.driver.get(url)
                
                # Aguardar e processar resultados
                WebDriverWait(self.driver, self.timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".result-item"))
                )
                
                resultados = self.driver.find_elements(By.CSS_SELECTOR, ".result-item")
                for resultado in resultados:
                    texto = resultado.text.lower()
                    if str(numero).lower() in texto and tipo.lower() in texto:
                        return "revogado" not in texto and "cancelado" not in texto
                        
                logger.warning(f"Norma {tipo} {numero} não encontrada nos resultados")
                return False
                
            except Exception as e:
                logger.error(f"Erro na tentativa {tentativa}: {str(e)}")
                time.sleep(2)  # Espera entre tentativas
            finally:
                self._fechar_navegador()
        
        return False

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

    def verificar_vigencia_automatica(self, documento):
        """Verifica normas não validadas nos últimos 30 dias"""
        data_limite = timezone.now() - timedelta(days=30)
        
        normas = NormaVigente.objects.filter(
            Q(data_verificacao__lt=data_limite) | Q(data_verificacao__isnull=True),
            situacao="VIGENTE"
        )
        
        for norma in normas:
            resultado = self.buscar_norma_especifica(norma.tipo, norma.numero)
            norma.situacao = "VIGENTE" if resultado['vigente'] else "REVOGADA"
            norma.data_verificacao = timezone.now()
            norma.save()

        return []

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