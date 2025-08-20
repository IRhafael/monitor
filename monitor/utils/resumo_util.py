# monitor/utils/resumo_util.py

from typing import List, Dict, Any
from transformers import pipeline

def gerar_resumo_documentos(documentos: List[Any], campo_texto='texto_completo', max_input_length=1024) -> Dict[str, Any]:
    """
    Gera um resumo automático para uma lista de documentos usando IA HuggingFace (DistilBART).
    :param documentos: lista de objetos Documento (Django model ou dict-like)
    :param campo_texto: campo do documento que contém o texto a ser resumido
    :param max_input_length: máximo de caracteres para entrada do modelo
    :return: dict com total e resumo gerado
    """
    resumo = {
        'total': len(documentos),
        'resumo_ia': None
    }
    if not documentos:
        return resumo

    # Extrai textos dos documentos
    textos = []
    for doc in documentos:
        texto = getattr(doc, campo_texto, None)
        if not texto and isinstance(doc, dict):
            texto = doc.get(campo_texto)
        if texto:
            textos.append(str(texto))

    if not textos:
        return resumo

    # Junta textos e limita tamanho
    texto_input = '\n'.join(textos)
    texto_input = texto_input[:max_input_length]

    # Inicializa pipeline de sumarização
    summarizer = pipeline('summarization', model='sshleifer/distilbart-cnn-12-6')
    resultado = summarizer(texto_input, max_length=120, min_length=30, do_sample=False)
    resumo['resumo_ia'] = resultado[0]['summary_text'] if resultado and 'summary_text' in resultado[0] else None
    return resumo
