import re
import urllib.request

req = urllib.request.Request(
    "https://www.google.com/search?q=site:manpower.es+ofertas+de+empleo",
    headers={"User-Agent": "Mozilla/5.0"},
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")

        links = re.findall(r'https://www.manpower.es[^&"\'<]+', html)
        print("Found links:", list(set(links))[:15])

except Exception as e:
    print("Error:", e)
