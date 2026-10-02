import json
import re

from bs4 import BeautifulSoup
from curl_cffi import requests


def fetch_synergie_jobs():
    resp = requests.get("https://www.synergie.es/busco-trabajo/", impersonate="chrome")
    soup = BeautifulSoup(resp.text, "html.parser")
    island = soup.find("astro-island", attrs={"opts": lambda x: x and "OfferList" in x})
    if not island:
        print("No Astro island found")
        return

    # Extract the JSON array
    json_str = island.text
    try:
        data = json.loads(json_str)
        # Astro serializes data as a massive flat array, and objects are represented as nested arrays referencing indices.
        # But we can just convert it to string and regex for job data!
        flat_str = json.dumps(data)

        # In Astro: {"id":[0,146746],"reference":[0,null]} and the title is somewhere nearby.
        # But wait! A simpler way is to find all dictionaries in the parsed data that have 'id' and 'title'.

        def find_dicts_with_keys(obj, keys, results):
            if isinstance(obj, dict):
                if all(k in obj for k in keys):
                    results.append(obj)
                for v in obj.values():
                    find_dicts_with_keys(v, keys, results)
            elif isinstance(obj, list):
                for item in obj:
                    find_dicts_with_keys(item, keys, results)

        jobs = []
        find_dicts_with_keys(data, ["id", "title"], jobs)
        print(f"Found {len(jobs)} jobs via dict structure")

        # If that fails due to Astro tuple format, we can regex the raw JSON
        if not jobs:
            # Astro tuples: "title":[0,"Operario/a de producción"]
            # We can find all titles
            titles = re.findall(r'"title":\[\d+,"([^"]+)"\]', flat_str)
            ids = re.findall(r'"job_request":\[\d+,\{"id":\[\d+,(\d+)\]', flat_str)
            locations = re.findall(r'"NOMBRE_PROV":\[\d+,"([^"]+)"\]', flat_str)
            print(
                f"Regex found: {len(titles)} titles, {len(ids)} ids, {len(locations)} locations"
            )
            for i in range(min(len(titles), len(ids))):
                print(f"- {titles[i]} (ID: {ids[i]})")

    except Exception as e:
        print(f"Error parsing JSON: {e}")


fetch_synergie_jobs()
