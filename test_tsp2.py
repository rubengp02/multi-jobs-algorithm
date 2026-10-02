import requests
from bs4 import BeautifulSoup

r = requests.get("https://www.talentsearchpeople.com/es/trabajos/")
soup = BeautifulSoup(r.text, "html.parser")

links = [a.get("href") for a in soup.select('a[href*="/es/trabajos/"]')]
print("Total links found with /es/trabajos/:", len(links))
for l in links[:20]:
    print(l)
