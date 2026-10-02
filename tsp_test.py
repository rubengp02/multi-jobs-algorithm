import re
import urllib.request

req = urllib.request.Request(
    "https://www.talentsearchpeople.com/es/trabajos/",
    headers={"User-Agent": "Mozilla/5.0"},
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")
        print("HTML length:", len(html))

        # Look for job titles
        titles = re.findall(r'"title"\s*:\s*"([^"]+)"', html)
        print("Found titles:", titles[:15])

        # Look for job links
        job_links = re.findall(
            r'"href"\s*:\s*"([^"]*(?:/es/trabajos/|/oferta/)[^"]+)"', html
        )
        if not job_links:
            job_links = re.findall(
                r'href="([^"]*(?:/es/trabajos/|/oferta/)[^"]+)"', html
            )
        print("Found job links:", job_links[:15])

except Exception as e:
    print("Error:", e)
