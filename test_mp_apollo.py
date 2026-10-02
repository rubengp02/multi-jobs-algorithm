import re
import urllib.request

req = urllib.request.Request(
    "https://www.manpower.es/es/buscar-trabajo", headers={"User-Agent": "Mozilla/5.0"}
)
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
        print("HTML length:", len(html))

        match = re.search(r'APOLLO_STATE":(\{.*?\})\s*\}<\/script>', html)
        if match:
            state_str = match.group(1)
            # Find jobs in the string without parsing the whole json if it's broken
            titles = re.findall(r'"title":"([^"]+)"', state_str)
            job_ids = re.findall(r'"jobId":"([^"]+)"', state_str)
            print("Found titles in APOLLO_STATE:", titles[:5])
            print("Found jobIds in APOLLO_STATE:", job_ids[:5])

            # Look for other keys
            keys = re.findall(r'"([^"]+)":', state_str)
            print("Keys in APOLLO_STATE:", list(set(keys))[:20])
except Exception as e:
    print("Error:", e)
