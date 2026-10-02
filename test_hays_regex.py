import re
import urllib.request

req = urllib.request.Request(
    "https://www.hays.es/busqueda-empleo", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")

        # Regex to find all: \&q;title\&q;:\&q;(.*?)\&q;
        titles = re.findall(r"\\&q;title\\&q;:\\&q;(.*?)\\&q;", html)
        urls = re.findall(r"\\&q;trackingUrl\\&q;:\\&q;(.*?)\\&q;", html)

        print(f"Found {len(titles)} titles and {len(urls)} urls")
        for i in range(min(5, len(titles))):
            print(f"{titles[i]} - {urls[i]}")

except Exception as e:
    print("Error:", e)
