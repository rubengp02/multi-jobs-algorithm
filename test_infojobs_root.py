import requests

r = requests.get(
    "https://www.infojobs.net/",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    },
)
print(r.status_code)
