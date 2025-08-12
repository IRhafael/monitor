# monitor/utils/resumo_util.py
from typing import List, Dict, Any

def gerar_resumo_documentos(documentos: List[Any], campos_exemplo=None) -> Dict[str, Any]:
    """
    Gera um resumo compacto para uma lista de documentos.
    :param documentos: lista de objetos Documento (Django model ou dict-like)
    :param campos_exemplo: lista de campos para mostrar exemplos (ex: ['nome', 'data_upload', 'titulo', 'data_publicacao'])
    :return: dict com total e exemplos dos campos principais
    """
    if campos_exemplo is None:
        campos_exemplo = ['nome', 'data_upload', 'titulo', 'data_publicacao']
    resumo = {
        'total': len(documentos),
        'exemplos': {}
    }
    if documentos:
        doc_exemplo = documentos[0]
        for campo in campos_exemplo:
            valor = getattr(doc_exemplo, campo, None)
            if not valor and isinstance(doc_exemplo, dict):
                valor = doc_exemplo.get(campo)
            if valor:
                resumo['exemplos'][campo] = valor
    return resumo
