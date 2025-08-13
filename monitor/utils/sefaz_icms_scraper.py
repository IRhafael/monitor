
class SEFAZICMSScraper:
    def __init__(self):
        from selenium.webdriver.chrome.options import Options
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless=new')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--window-size=1920,1080')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    def coletar_documentos(self):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        import time
        import requests
        import os
        import re
        from datetime import datetime
        from monitor.models import Documento

        driver = webdriver.Chrome(options=self.chrome_options)
        driver.get("https://portaldalegislacao.sefaz.pi.gov.br/inicio")
        time.sleep(5)

        documentos_salvos = []
        elementos = driver.find_elements(By.CSS_SELECTOR, "div.text-title-content.cursor-pointer")
        norma_icms = None
        for el in elementos:
            if "Últimas Normas ICMS" in el.text:
                norma_icms = el
                break

        if norma_icms:
            ActionChains(driver).move_to_element(norma_icms).click(norma_icms).perform()
            time.sleep(3)

            cards = driver.find_elements(By.CSS_SELECTOR, "h1.cursor-pointer")
            for card in cards:
                titulo = card.text.strip()
                ActionChains(driver).move_to_element(card).click(card).perform()
                time.sleep(5)
                try:
                    vigencia = driver.find_element(By.XPATH, "//*[contains(text(),'Início da vigência')]").text
                    try:
                        strong_situacao = driver.find_element(By.XPATH, "//strong[contains(text(),'Situação:')]")
                        situacao = strong_situacao.find_element(By.XPATH, "following-sibling::text()[1]").strip()
                        if not situacao:
                            situacao = strong_situacao.find_element(By.XPATH, "..") .text.replace('Situação:', '').strip()
                    except Exception:
                        situacao = ''
                    publicacao = driver.find_element(By.XPATH, "//*[contains(text(),'Publicação')]").text
                    ementa = driver.find_element(By.XPATH, "//*[contains(text(),'Ementa')]").text
                    match = re.search(r'em (\d{2}/\d{2}/\d{4})', publicacao)
                    data_publicacao = None
                    if match:
                        data_str = match.group(1)
                        data_publicacao = datetime.strptime(data_str, '%d/%m/%Y').date()
                    if not data_publicacao:
                        data_publicacao = datetime.today().date()
                    div_baixar = driver.find_element(By.XPATH, "//div[contains(@class, 'button-text') and text()='Baixar']")
                    link_baixar = div_baixar.find_element(By.XPATH, "..")
                    href_baixar = link_baixar.get_attribute("href")
                    pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
                    href_baixar = None
                    for link in pdf_links:
                        if link.is_displayed():
                            href_baixar = link.get_attribute("href")
                            break
                    if href_baixar:
                        response = requests.get(href_baixar)
                        if response.status_code == 200:
                            nome_arquivo = href_baixar.split('/')[-1]
                            caminho_arquivo = os.path.join('pdfs_sefaz', nome_arquivo)
                            os.makedirs('pdfs_sefaz', exist_ok=True)
                            with open(caminho_arquivo, 'wb') as f:
                                f.write(response.content)
                            doc = Documento(
                                titulo=titulo,
                                data_publicacao=data_publicacao,
                                url_original=href_baixar,
                                docs_sefaz=caminho_arquivo,
                                resumo=ementa,
                                texto_completo='',
                                fonte_documento=publicacao,
                                metadata={
                                    'vigencia': vigencia,
                                    'situacao': situacao
                                }
                            )
                            doc.save()
                            documentos_salvos.append(doc)
                        else:
                            pass
                except Exception as e:
                    pass
                try:
                    btn_fechar = driver.find_element(By.CSS_SELECTOR, "button.p-dialog-header-close")
                    btn_fechar.click()
                    time.sleep(1)
                except Exception as e:
                    pass
        driver.quit()
        return documentos_salvos