import re
import urllib.request

req = urllib.request.Request(
    "https://www.manpower.es/es/candidatos", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
        print("HTML length:", len(html))

        job_links = re.findall(r'href=["\']([^"\']*(?:oferta|job)[^"\']+)["\']', html)
        print("Found job links:", list(set(job_links))[:15])

        if "api" in html.lower():
            print("Found API signatures!")

except Exception as e:
    print("Error:", e)
