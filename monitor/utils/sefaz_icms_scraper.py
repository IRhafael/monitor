from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
import time
import requests
import os
import django
import sys
import re
from datetime import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
django.setup()
from monitor.models import Documento

driver = webdriver.Chrome()
driver.get("https://portaldalegislacao.sefaz.pi.gov.br/inicio")
time.sleep(5)

# Clica em 'Últimas Normas ICMS'
elementos = driver.find_elements(By.CSS_SELECTOR, "div.text-title-content.cursor-pointer")
norma_icms = None
for el in elementos:
    if "Últimas Normas ICMS" in el.text:
        norma_icms = el
        break

if norma_icms:
    ActionChains(driver).move_to_element(norma_icms).click(norma_icms).perform()
    time.sleep(3)

    # Busca todos os cards/títulos
    cards = driver.find_elements(By.CSS_SELECTOR, "h1.cursor-pointer")
    print(f"Encontrados {len(cards)} cards.")
    for card in cards:
        titulo = card.text.strip()
        print(f"Processando card: {titulo}")
        ActionChains(driver).move_to_element(card).click(card).perform()
        time.sleep(5)  # Aguarda o conteúdo do card/modal abrir (aumentado)
        try:
            vigencia = driver.find_element(By.XPATH, "//*[contains(text(),'Início da vigência')]").text
            # Extrai a situação: pega o texto logo após o <strong> Situação:
            try:
                strong_situacao = driver.find_element(By.XPATH, "//strong[contains(text(),'Situação:')]")
                situacao = strong_situacao.find_element(By.XPATH, "following-sibling::text()[1]").strip()
                if not situacao:
                    # Alternativa: pega o texto do pai
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
                # Se não encontrar, usa a data atual
                data_publicacao = datetime.today().date()
            div_baixar = driver.find_element(By.XPATH, "//div[contains(@class, 'button-text') and text()='Baixar']")
            link_baixar = div_baixar.find_element(By.XPATH, "..")
            href_baixar = link_baixar.get_attribute("href")
            print(f"Link PDF: {href_baixar}")
            # Busca qualquer link PDF visível no modal
            pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
            href_baixar = None
            for link in pdf_links:
                if link.is_displayed():
                    href_baixar = link.get_attribute("href")
                    break
            print(f"Link PDF: {href_baixar}")
            # Baixa o PDF e salva no campo docs_sefaz do Documento
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
                    print(f"PDF salvo e Documento criado: {doc}")
                else:
                    print(f"Falha ao baixar PDF: {href_baixar}")
                    print(f"Falha ao baixar PDF: {href_baixar}")
        except Exception as e:
            print(f"Erro ao extrair dados do card '{titulo}': {e}")
        try:
            btn_fechar = driver.find_element(By.CSS_SELECTOR, "button.p-dialog-header-close")
            btn_fechar.click()
            time.sleep(1)
        except Exception as e:
            print(f"Não foi possível fechar o modal: {e}")
else:
    print("Elemento 'Últimas Normas ICMS' NÃO encontrado!")

driver.quit()