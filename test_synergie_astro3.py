import json

from bs4 import BeautifulSoup
from curl_cffi import requests


def parse_astro_tuples(data):
    # Astro devalue deserializer for our specific needs
    jobs = []

    # We will just traverse all arrays/dicts recursively
    def traverse(obj):
        if isinstance(obj, dict):
            if "job_request" in obj and "title" in obj:
                # We found a job object!
                # obj["job_request"] -> [0, {"id": [0, 146746]}]
                try:
                    job_req = obj["job_request"]
                    if isinstance(job_req, list) and len(job_req) > 1:
                        job_req_dict = job_req[1]
                        if isinstance(job_req_dict, dict) and "id" in job_req_dict:
                            id_tuple = job_req_dict["id"]
                            if isinstance(id_tuple, list) and len(id_tuple) > 1:
                                job_id = id_tuple[1]

                                title_tuple = obj["title"]
                                if (
                                    isinstance(title_tuple, list)
                                    and len(title_tuple) > 1
                                ):
                                    title = title_tuple[1]
                                    jobs.append({"id": job_id, "title": title})
                except Exception:
                    pass
            for v in obj.values():
                traverse(v)
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)

    traverse(data)
    return jobs


def fetch_synergie_jobs():
    resp = requests.get("https://www.synergie.es/busco-trabajo/", impersonate="chrome")
    soup = BeautifulSoup(resp.text, "html.parser")
    island = soup.find("astro-island", attrs={"opts": lambda x: x and "OfferList" in x})

    if island and island.get("props"):
        props = island.get("props")
        data = json.loads(props)
        jobs = parse_astro_tuples(data)
        for j in jobs[:20]:
            print(f"Found Job: {j['title']} (ID: {j['id']})")
        print(f"Total jobs extracted: {len(jobs)}")


fetch_synergie_jobs()
