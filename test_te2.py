import re

from curl_cffi import requests

r = requests.get(
    "https://www.tecnoempleo.com/ofertas-trabajo/?te=python", impersonate="chrome"
)
print("/rf-" in r.text)
matches = re.findall(r"href=[\"\']([^\"\']+)[\"\']", r.text)
print([m for m in matches if "tecnoempleo.com" in m][:5])
