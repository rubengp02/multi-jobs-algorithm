import re
import urllib.request

from bs4 import BeautifulSoup

url = "https://www.infojobs.net/paterna/ingeniero-automatizacion/of-ideeef9b54b41318a42c3aed0a0870a"
try:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        print("Correos encontrados:", set(emails))
except Exception as e:
    print("Error:", e)
