from curl_cffi import requests

r = requests.get(
    "https://www.infojobs.net/ofertas-trabajo/valencia/python", impersonate="chrome120"
)
print("Status:", r.status_code)
print("Redirects:", r.history)
print("Current URL:", r.url)
print("HTML snipp:", r.text[:1000])
