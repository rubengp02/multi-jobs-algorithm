import re
import urllib.request

from bs4 import BeautifulSoup

urls = ["https://autis.es/trabaja-con-nosotros/", "https://autis.com/careers/"]

for url in urls:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            print(f"\n--- Resultados en {url} ---")

            # Autis uses typical WordPress or specific layouts. Let's look for standard job titles.
            found_titles = set()
            for tag in soup.find_all(["h2", "h3", "h4", "a", "strong", "li"]):
                text = tag.get_text(strip=True)
                if 5 < len(text) < 100:
                    if re.search(
                        r"(ingenier|engineer|t[eé]cnic|desarrollador|developer|responsable|jefe|manager|programador|soporte)",
                        text,
                        re.IGNORECASE,
                    ):
                        if "Autis" not in text and "LinkedIn" not in text:
                            found_titles.add(text)

            if found_titles:
                for t in found_titles:
                    print(f"- {t}")
            else:
                print(
                    "No se detectaron ofertas explícitas en el DOM. Mostrando un extracto del texto de la página:"
                )
                text_page = soup.get_text(separator=" ", strip=True)
                print(text_page[300:1000])

    except Exception as e:
        print(f"Error en {url}: {e}")
