from curl_cffi import requests

resp = requests.get(
    "https://jobs.eurofirms.com/es/es/", impersonate="chrome", timeout=10
)
lines = resp.text.split("\n")
for i, line in enumerate(lines):
    if "ef-api-frontoffice" in line:
        print(f"Line {i}: {line}")
    if "apiUrl" in line or "fetch(" in line or "url:" in line:
        if len(line) < 500:
            print(f"Line {i}: {line}")
