# monitor/utils/pdf_processor.py
import os
import logging
import re
import PyPDF2
import nltk
from nltk.tokenize import sent_tokenize
from datetime import datetime
from django.conf import settings
from monitor.models import Documento
import nltk
nltk.download('punkt')
nltk.download('punkt_tab')

logger = logging.getLogger(__name__)

class PDFProcessor:
    def __init__(self):
        self._baixar_recursos_nltk()
        # Padrões relevantes para contabilidade - Expandidos e ponderados
        self.padroes_contabeis = [
            # Termos com alto peso (3 pontos)
            (r'icms|ipi|iss|pis|cofins|csll|irpj|itr|iptu|itbi|itcd', 3),  # Impostos específicos
            (r'sped|efd|dctf|dirf|gia|dmed', 3),  # Obrigações fiscais específicas
            (r'nf-e|nfc-e|cte|mdfe|efd-reinf|esocial', 3),  # Documentos fiscais eletrônicos
            
            # Termos com peso médio (2 pontos)
            (r'tribut[aá]r[ií][ao]|fiscal[ií]za[cç][aã]o', 2),
            (r'receita federal|sefaz|secretaria d[ae] fazenda', 2),
            (r'cont[aá]bil|escritura[cç][aã]o|balancete|balan[cç]o patrimonial', 2),
            (r'simples nacional|lucro real|lucro presumido|mei', 2),
            (r'darf|gnre|guia|recolhimento|d[eé]bito autom[aá]tico', 2),
            
            # Termos com peso normal (1 ponto)
            (r'imposto|contribui[cç][aã]o|taxa', 1),
            (r'declara[cç][aã]o|fiscal', 1),
            (r'certid[aã]o negativa|d[ií]vida ativa', 1),
            (r'cr[eé]dito tribut[aá]rio|compensa[cç][aã]o', 1),
            (r'parcelamento|auto de infra[cç][aã]o', 1),
            (r'multa|juro|atualiza[cç][aã]o monet[aá]ria', 1),
            (r'audit[oó]ria|demonstra[cç][oõ]es financeiras', 1),
        ]
        
        self.padroes_relevantes = [
            r'decreto n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'lei n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'portaria n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'resolução n[º°]?\s*\.?\s*(\d+[\.\d]*\/?\d*)',
            r'instrução normativa',
            r'medida provisória',
        ]
        
        # Limite mínimo de relevância para manter o documento
        self.limite_relevancia = 4

    def _baixar_recursos_nltk(self):
        """Garante que todos os recursos do NLTK estão disponíveis"""
        try:
            nltk.data.find('tokenizers/punkt')
            nltk.data.find('tokenizers/punkt_tab/portuguese')
        except LookupError:
            nltk.download('punkt')
            nltk.download('punkt_tab')
            # Para português, pode ser necessário baixar recursos adicionais
            nltk.download('stopwords')

    def avaliar_relevancia_contabil(self, texto):
        """
        Avalia a relevância contábil do texto com base em critérios ponderados
        Retorna: pontuação de relevância e dicionário com termos encontrados
        """
        texto = texto.lower()
        pontuacao = 0
        termos_encontrados = {}
        
        # Verifica padrões contábeis com seus respectivos pesos
        for padrao, peso in self.padroes_contabeis:
            matches = re.findall(padrao, texto, re.IGNORECASE)
            if matches:
                termo_chave = matches[0] if isinstance(matches[0], str) else matches[0][0]
                pontuacao += peso * len(matches)
                termos_encontrados[termo_chave] = len(matches)
        
        # Verifica menções a normas
        normas = self.extrair_normas_do_texto(texto)
        for tipo, numero in normas:
            # Normas fiscais/tributárias específicas têm peso maior
            if re.search(r'tribut|fiscal|icms|ipi', tipo, re.IGNORECASE):
                pontuacao += 2
            else:
                pontuacao += 1
            
        # Se tem muitas seções sobre impostos/tributação, aumenta relevância
        secoes_fiscais = re.findall(r'(capítulo|seção|artigo)[\s\d]+[–-][\s]*(tribut|fiscal|imposto)', texto, re.IGNORECASE)
        pontuacao += len(secoes_fiscais) * 2
                
        return pontuacao, termos_encontrados

    def processar_documento(self, documento):
        """Processa o documento e mantém apenas se for contábil"""
        logger.info(f"Processando documento ID {documento.id}")

        try:
            # Verifica se o arquivo existe
            if not documento.arquivo_pdf or not os.path.exists(documento.arquivo_pdf.path):
                logger.warning(f"Arquivo PDF não encontrado para documento ID {documento.id}")
                documento.delete()  # Remove documento sem arquivo
                return False

            # Extrai texto
            texto = self.extrair_texto_pdf(documento.arquivo_pdf.path)
            if not texto:
                logger.warning(f"Não foi possível extrair texto do documento ID {documento.id}")
                documento.delete()  # Remove documento sem texto
                return False

            # Verifica relevância contábil
            if not self.is_contabil(texto):
                logger.info(f"Documento ID {documento.id} não é contábil - será removido")
                documento.arquivo_pdf.delete()  # Remove o arquivo PDF
                documento.delete()  # Remove o registro do banco
                return False

            # Se for contábil, processa completamente
            documento.texto_completo = texto
            documento.resumo = self.gerar_resumo_contabil(texto)
            documento.relevante_contabil = True
            documento.processado = True
            documento.save()
            
            logger.info(f"Documento ID {documento.id} processado e mantido (contábil)")
            return True

        except Exception as e:
            logger.error(f"Erro ao processar documento {documento.id}: {str(e)}")
            return False

    def _excluir_documento(self, documento):
        """Exclui o arquivo e opcionalmente o registro do documento não relevante"""
        try:
            # Remove o arquivo físico
            if documento.arquivo_pdf and os.path.exists(documento.arquivo_pdf.path):
                caminho = documento.arquivo_pdf.path
                documento.arquivo_pdf.delete(save=False)  # Remove o arquivo sem salvar o modelo
                logger.info(f"Arquivo excluído: {caminho}")
            
            # Se configurado para excluir também o registro
            if hasattr(settings, 'EXCLUIR_REGISTRO_NAO_CONTABEIS') and settings.EXCLUIR_REGISTRO_NAO_CONTABEIS:
                logger.info(f"Excluindo registro do documento ID {documento.id}")
                documento.delete()
            else:
                # Atualiza o registro para indicar que o arquivo foi removido
                documento.arquivo_removido = True
                documento.save()
                
            logger.info(f"Documento não contábil ID {documento.id} foi processado e excluído")
        except Exception as e:
            logger.error(f"Erro ao excluir documento {documento.id}: {str(e)}")

    def extrair_texto_pdf(self, caminho_pdf):
        """Extrai texto de PDFs com tratamento robusto de erros"""
        try:
            with open(caminho_pdf, 'rb') as f:
                texto = ""
                try:
                    leitor = PyPDF2.PdfReader(f)
                    for pagina in leitor.pages:
                        try:
                            conteudo = pagina.extract_text()
                            if conteudo:
                                # Normaliza quebras de linha e espaços
                                texto += re.sub(r'\s+', ' ', conteudo) + " "
                        except Exception as e:
                            logger.warning(f"Erro na página: {str(e)}")
                            continue
                except PyPDF2.PdfReadError:
                    # Tentativa alternativa para PDFs problemáticos
                    texto = self._extrair_texto_pdf_fallback(caminho_pdf)
                
                return texto.strip()
        except Exception as e:
            logger.error(f"Erro grave ao processar PDF: {str(e)}")
            return ""

    def _extrair_texto_pdf_fallback(self, caminho_pdf):
        """Método alternativo para extração de texto"""
        try:
            import pdftotext
            with open(caminho_pdf, "rb") as f:
                pdf = pdftotext.PDF(f)
                return "\n\n".join(pdf)
        except:
            return ""

    def gerar_resumo_contabil(self, texto):
        """Gera um resumo focado em informações contábeis com melhor contextualização"""
        if not texto or len(texto.strip()) < 50:
            return "Documento sem conteúdo textual relevante."
        
        try:
            # Pré-processamento do texto
            texto = self._limpar_texto(texto)
            
            # Divisão em parágrafos (melhor que frases para contexto)
            paragrafos = [p for p in texto.split('\n') if p.strip()]
            
            # Selecionar parágrafos mais relevantes
            paragrafos_relevantes = []
            for p in paragrafos:
                relevancia = self._calcular_relevancia_paragrafo(p)
                if relevancia > 0:
                    paragrafos_relevantes.append((relevancia, p))
            
            # Ordenar por relevância e selecionar os melhores
            paragrafos_relevantes.sort(reverse=True, key=lambda x: x[0])
            melhores_paragrafos = [p for (_, p) in paragrafos_relevantes[:3]]
            
            # Se não encontrou parágrafos relevantes, usar abordagem alternativa
            if not melhores_paragrafos:
                return self._gerar_resumo_fallback(texto)
            
            # Pós-processamento para melhor coerência
            resumo = self._pos_processar_resumo(melhores_paragrafos)
            return resumo
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo: {str(e)}")
            return "Erro ao gerar resumo do documento."

    def _limpar_texto(self, texto):
        """Remove formatação e caracteres especiais"""
        texto = re.sub(r'\s+', ' ', texto)  # Remove múltiplos espaços
        texto = re.sub(r'-\n', '', texto)  # Junta palavras quebradas
        return texto.strip()

    def _calcular_relevancia_paragrafo(self, paragrafo):
        """Calcula a relevância de um parágrafo para contabilidade"""
        pontos = 0
        
        # Verifica padrões contábeis
        for padrao, peso in self.padroes_contabeis:
            matches = re.findall(padrao, paragrafo, re.IGNORECASE)
            if matches:
                pontos += peso
        
        # Verifica menções a normas
        normas = self.extrair_normas_do_texto(paragrafo)
        pontos += len(normas)
        
        # Penaliza parágrafos muito curtos
        if len(paragrafo) < 100:
            pontos -= 1
        
        return pontos

    def _gerar_resumo_fallback(self, texto):
        """Método alternativo quando não encontra parágrafos relevantes"""
        # Usa as primeiras linhas que contenham termos contábeis
        linhas_relevantes = []
        for linha in texto.split('\n'):
            if len(linhas_relevantes) >= 3:
                break
            for padrao, _ in self.padroes_contabeis:
                if re.search(padrao, linha, re.IGNORECASE):
                    linhas_relevantes.append(linha[:300])  # Limita o tamanho
                    break
        
        if linhas_relevantes:
            return " | ".join(linhas_relevantes)
        return "Documento contém informações contábeis não estruturadas."

    def _pos_processar_resumo(self, paragrafos):
        """Melhora a formatação do resumo final"""
        resumo = "\n\n".join(paragrafos)
        
        # Remove múltiplas quebras de linha
        resumo = re.sub(r'\n{3,}', '\n\n', resumo)
        
        # Limita o tamanho total
        if len(resumo) > 1500:
            resumo = resumo[:1500] + "... [continua]"
        
        return resumo
        
    def processar_todos_documentos(self):
        """Processa todos os documentos não processados no banco de dados"""
        documentos = Documento.objects.filter(processado=False)
        logger.info(f"Iniciando processamento de {documentos.count()} documentos")
        
        resultados = {
            'total': documentos.count(),
            'processados': 0,
            'relevantes': 0,
            'nao_relevantes': 0,
            'erros': 0
        }
        
        for documento in documentos:
            try:
                logger.info(f"Processando documento ID {documento.id} - {documento.titulo}")
                
                # Verifica se o arquivo existe
                if not documento.arquivo_pdf:
                    logger.warning(f"Documento ID {documento.id} não tem arquivo PDF associado")
                    continue
                    
                if not os.path.exists(documento.arquivo_pdf.path):
                    logger.warning(f"Arquivo PDF não encontrado no caminho: {documento.arquivo_pdf.path}")
                    continue
                
                resultado = self.processar_documento(documento)
                resultados['processados'] += 1
                if resultado:
                    resultados['relevantes'] += 1
                else:
                    resultados['nao_relevantes'] += 1
                
            except Exception as e:
                logger.error(f"Erro ao processar documento ID {documento.id}: {str(e)}", exc_info=True)
                resultados['erros'] += 1
        
        logger.info(f"Processamento concluído: {resultados['relevantes']} documentos relevantes, "
                   f"{resultados['nao_relevantes']} não relevantes, {resultados['erros']} erros")
        return resultados
    
    def extrair_normas_do_texto(self, texto):
        """Extrai normas com formatação consistente"""
        padroes = [
            r'(Lei|Decreto|Portaria|Instrução Normativa|Resolução)\s+(n?[º°]?\s*[.-]?\s*\d+[/-]?\d*)',
            r'(LEI|DECRETO|PORTARIA|INSTRUÇÃO NORMATIVA|RESOLUÇÃO)\s+(N?[º°]?\s*[.-]?\s*\d+[/-]?\d*)'
        ]
        
        normas = []
        for padrao in padroes:
            matches = re.finditer(padrao, texto, re.IGNORECASE)
            for match in matches:
                tipo = match.group(1).upper()
                numero = match.group(2)
                
                # Padronização do número
                numero = re.sub(r'\s+', '', numero)  # Remove espaços
                numero = re.sub(r'[º°]', 'º', numero)  # Padroniza ordinal
                numero = re.sub(r'[.-](\d)', r'\1', numero)  # Remove pontos/hífens antes de números
                
                # Validação básica
                if re.match(r'^\d+[/-]?\d*$', numero.split('º')[-1]):
                    normas.append((tipo, numero))
        
        # Remove duplicatas mantendo a ordem
        seen = set()
        return [x for x in normas if not (x in seen or seen.add(x))]
    
        # Em pdf_processor.py, adicione:
    def is_contabil(self, texto):
        """Verifica se o texto contém termos contábeis relevantes"""
        if not texto:
            return False
            
        texto = texto.lower()
        termos_contabeis = [
            'tribut', 'imposto', 'icms', 'ipi', 'iss', 'receita federal',
            'declaração', 'fiscal', 'contábil', 'escrituração', 'lucro real',
            'simples nacional', 'mei', 'darf', 'efd', 'sped'
        ]
        
        return any(termo in texto for termo in termos_contabeis)