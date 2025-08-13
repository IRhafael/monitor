import requests
from bs4 import BeautifulSoup
from datetime import datetime

class ContabeisScraper:
    BASE_URL = "https://www.contabeis.com.br/conteudo/noticias/"

    def buscar_noticias(self, palavra_chave=None, pagina=1):
        """
        Busca notícias recentes ou por palavra-chave.
        Retorna lista de dicts: [{titulo, url, resumo, data}]
        Agora captura link e título diretamente da tag <ul class="compartilhamento">.
        """
        params = {}
        if palavra_chave:
            params['q'] = palavra_chave
        if pagina > 1:
            url = f"{self.BASE_URL}?pagina={pagina}"
        else:
            url = self.BASE_URL
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        noticias = []
        for artigo in soup.select("article"):
            compartilhamento = artigo.select_one("ul.compartilhamento")
            titulo = compartilhamento.get("titulo") if compartilhamento else None
            url_noticia = compartilhamento.get("href") if compartilhamento else None
            texto_tag = artigo.select_one("div.texto")
            resumo = texto_tag.text.strip() if texto_tag else None
            data_tag = artigo.select_one("em.timestamp")
            data = data_tag.text.strip() if data_tag else None
            noticias.append({
                'titulo': titulo,
                'url': url_noticia,
                'resumo': resumo,
                'data': data
            })
        return noticias

    def extrair_detalhes_noticia(self, url):
        """
        Extrai detalhes de uma notícia individual.
        Retorna dict: {titulo, texto, data, autor}
        """
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Tenta capturar o título
        titulo_tag = soup.select_one("div.tituloInterno") or soup.select_one("h1")
        titulo = titulo_tag.text.strip() if titulo_tag else None
        # Tenta capturar o texto principal
        texto_tag = soup.select_one("div.materia-conteudo") or soup.select_one("div.texto")
        if texto_tag:
            texto = texto_tag.get_text("\n", strip=True)
        else:
            texto = ""
        # Tenta capturar a data
        data_tag = soup.select_one("em.timestamp")
        data = data_tag.text.strip() if data_tag else None
        # Tenta capturar o autor
        autor_tag = soup.select_one("span.autor")
        autor = autor_tag.text.strip() if autor_tag else None
        return {
            'titulo': titulo,
            'texto': texto,
            'data': data,
            'autor': autor
        }
