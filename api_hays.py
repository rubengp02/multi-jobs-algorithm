from curl_cffi import requests

url = "https://www.hays.es/api/job-search/es/es/search"
try:
    resp = requests.post(
        url,
        json={"query": "", "location": "", "radius": "", "sort": "", "page": 1},
        impersonate="chrome",
    )
    print(resp.status_code)
    print(resp.text[:500])
except Exception as e:
    print(str(e))
