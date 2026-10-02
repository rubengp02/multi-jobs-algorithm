import re
import urllib.request

req = urllib.request.Request(
    "https://www.manpower.es/es/buscar-trabajo", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
        print("HTML length:", len(html))

        urls = re.findall(r"href=[\"\']([^\"\']*/job-details/[^\"\']+)[\"\']", html)
        print("Job-details:", list(set(urls))[:5])

        urls2 = re.findall(r"href=[\"\']([^\"\']*/oferta/[^\"\']+)[\"\']", html)
        print("Oferta:", list(set(urls2))[:5])

        if "APOLLO_STATE" in html:
            print("Found APOLLO_STATE")
except Exception as e:
    print("Error:", e)
