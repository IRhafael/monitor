import spacy
from spacy.lang.pt.stop_words import STOP_WORDS

class PDFProcessor:
    def __init__(self):
        self.nlp = spacy.load("pt_core_news_lg")
        self._adicionar_regras_contabeis()
    
    def _adicionar_regras_contabeis(self):
        # Padrões específicos para contabilidade
        ruler = self.nlp.add_pipe("entity_ruler")
        patterns = [
            {"label": "NORMA", "pattern": [{"TEXT": {"REGEX": r"^(Lei|Decreto|Portaria)\s+n?[º°]?\s*\d+"}}]},
            {"label": "IMPOSTO", "pattern": [{"LOWER": {"IN": ["icms", "ipi", "pis", "cofins"]}}]}
        ]
        ruler.add_patterns(patterns)