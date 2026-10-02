import re
import urllib.request

req = urllib.request.Request(
    "https://www.ananda.es/ofertas-de-empleo/", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")
        print("HTML length:", len(html))

        job_links = re.findall(r'href=["\']([^"\']*(?:oferta)[^"\']+)["\']', html)
        print("Found job links:", list(set(job_links))[:15])

except Exception as e:
    print("Error:", e)
