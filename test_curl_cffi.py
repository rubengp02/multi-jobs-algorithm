from curl_cffi import requests

try:
    r = requests.get("https://www.infojobs.net/", impersonate="chrome120")
    print("Status:", r.status_code)
    print("Length:", len(r.text))
except Exception as e:
    print("Error:", e)
