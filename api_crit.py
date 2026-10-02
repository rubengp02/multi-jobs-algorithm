from curl_cffi import requests

url = "https://empleo.grupo-crit.com/ofertas"
try:
    resp = requests.get(url, impersonate="chrome")
    print(resp.status_code)
    print(resp.text[:500])
except Exception as e:
    print(str(e))
