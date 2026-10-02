from curl_cffi import requests

url = "https://ef-api-frontoffice.eurofirms.es/FrontOffice/v9/Offers"
try:
    resp = requests.get(url, impersonate="chrome")
    print("GET Offers:", resp.status_code, resp.text[:200])
except Exception as e:
    print(str(e))

try:
    resp = requests.post(
        "https://ef-api-frontoffice.eurofirms.es/FrontOffice/v9/Offers/Search",
        json={},
        impersonate="chrome",
    )
    print("POST Search:", resp.status_code, resp.text[:200])
except Exception as e:
    print(str(e))
