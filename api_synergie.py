from curl_cffi import requests

url = "https://www.synergie.es/wp-admin/admin-ajax.php"
try:
    data = {"action": "job_search_results", "page": 1}
    resp = requests.post(url, data=data, impersonate="chrome")
    print(resp.status_code)
    print(resp.text[:500])
except Exception as e:
    print(str(e))
