# monitor/utils/enriquecedor.py
from urllib.parse import urlparse
from datetime import datetime

def enriquecer_documento_dict(doc_dict):
    """
    Recebe um dicionário de dados brutos de norma/documento e retorna um dicionário enriquecido
    para preencher todos os campos do modelo Documento.
    """
    enriched = dict(doc_dict)
    # Título
    if not enriched.get('titulo'):
        enriched['titulo'] = enriched.get('ementa') or enriched.get('apelido') or enriched.get('norma') or (enriched.get('texto_completo')[:80] if enriched.get('texto_completo') else None)
    # Data de publicação
    if not enriched.get('data_publicacao'):
        # Tenta converter string para data
        data_str = enriched.get('inicio_vigencia') or ''
        try:
            enriched['data_publicacao'] = datetime.strptime(data_str, '%d/%m/%Y').date() if data_str else None
        except Exception:
            enriched['data_publicacao'] = None
    # Fonte do documento
    if not enriched.get('fonte_documento'):
        if enriched.get('link_publicacao') and isinstance(enriched['link_publicacao'], dict):
            enriched['fonte_documento'] = urlparse(enriched['link_publicacao'].get('url','')).netloc
        else:
            enriched['fonte_documento'] = 'SEFAZ-PI'
    # Tipo do documento
    if not enriched.get('tipo_documento'):
        tipo = enriched.get('norma','').split()[0].upper() if enriched.get('norma') else None
        enriched['tipo_documento'] = tipo if tipo in ['LEI','DECRETO','PORTARIA','RESOLUCAO','INSTRUCAO'] else 'OUTRO'
    # Assunto
    if not enriched.get('assunto'):
        enriched['assunto'] = enriched.get('ementa') or ''
    # Impacto fiscal (exemplo: busca por palavras-chave)
    if not enriched.get('impacto_fiscal'):
        texto = (enriched.get('ementa') or '') + ' ' + (enriched.get('texto_completo') or '')
        if 'tribut' in texto.lower():
            enriched['impacto_fiscal'] = 'Tributário'
        elif 'financeir' in texto.lower():
            enriched['impacto_fiscal'] = 'Financeiro'
        else:
            enriched['impacto_fiscal'] = ''
    # Resumo IA (placeholder)
    if not enriched.get('resumo_ia'):
        enriched['resumo_ia'] = ''
    # Processado e relevante contábil (default)
    enriched['processado'] = True
    enriched['relevante_contabil'] = False
    # Metadados extras
    enriched['metadata'] = {k: v for k, v in doc_dict.items() if k not in enriched}
    return enriched
