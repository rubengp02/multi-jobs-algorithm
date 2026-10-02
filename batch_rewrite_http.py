import os
import re

providers = ['providers/tecnoempleo.py', 'providers/remoteok.py', 'providers/wwr.py']

for path in providers:
    if not os.path.exists(path):
        continue
    with open(path, 'r', encoding='utf-8') as f:
        code = f.read()

    # Imports
    code = code.replace('import requests', 'import httpx')
    if 'import httpx' not in code:
        code = 'import httpx\n' + code

    # Class initialization
    code = code.replace('self.session = requests.Session()', 'self.headers = {}')
    code = code.replace('self.session.headers.update(', 'self.headers.update(')
    code = code.replace('self.session.headers =', 'self.headers =')

    # check_session
    code = re.sub(
        r'def check_session\(self\)\s*->\s*tuple\[bool, str\]:\s*try:\s*r = self.session.get\(([^)]+)\)',
        r'def check_session(self) -> tuple[bool, str]:\n        try:\n            import httpx\n            with httpx.Client() as client:\n                r = client.get(\1)',
        code
    )

    # Convert fetch_jobs
    code = re.sub(r'def fetch_jobs\(self([^)]*)\)\s*->\s*list\[JobItem\]:', r'async def fetch_jobs(self\1) -> list[JobItem]:', code)
    
    # In fetch_jobs, replace r = self.session.get(...) with async with httpx.AsyncClient(...) as client: r = await client.get(...)
    # Actually, we can just instantiate the client once inside fetch_jobs
    code = code.replace('async def fetch_jobs(self', 'async def fetch_jobs(self')
    code = re.sub(r'(async def fetch_jobs\(.*?\):)', r'\1\n        async with httpx.AsyncClient(headers=getattr(self, "headers", {})) as client:', code)
    
    # We need to indent everything inside fetch_jobs!
    # A simpler way is to just do `r = await httpx.AsyncClient().get(...)`
    # Let's just write custom replacements for each file or do it carefully.
