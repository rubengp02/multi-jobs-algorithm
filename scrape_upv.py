import urllib.request

from bs4 import BeautifulSoup

url = "https://foroempleo.upv.es/"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")

        # In many UPV formats, companies are listed in specific grids or lists
        text_content = soup.get_text()
        print("Page accessed. Length of text:", len(text_content))
except Exception as e:
    print("Error:", e)
