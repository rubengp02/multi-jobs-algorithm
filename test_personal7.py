import re
import urllib.request

req = urllib.request.Request(
    "https://personal7.es/ofertas-de-empleo/", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")
        print("HTML length:", len(html))

        job_links = re.findall(r'href=["\']([^"\']*(?:oferta)[^"\']+)["\']', html)
        print("Found job links:", list(set(job_links))[:15])

        if "DataTable" in html or "ajax" in html.lower():
            print("Found AJAX/DataTable signatures!")

except Exception as e:
    print("Error:", e)
