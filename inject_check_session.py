import re
from pathlib import Path

base_dir = Path(r"c:\Users\Ruben\Desktop\Python\bot_linkedin\bot_multi_jobs\providers")

patches = {
    "accessiway.py": ("https://boards.eu.greenhouse.io/accessiway", "accessiway"),
    "experis.py": ("https://www.experis.es/ofertas-de-empleo", "experis"),
    "indeed.py": ('self.config.indeed_url or "https://es.indeed.com/"', "indeed"),
    "remoteok.py": ("https://remoteok.com/api", "remoteok"),
    "remotive.py": (
        "https://remotive.com/api/remote-jobs?category=software-dev&limit=1",
        "remotive",
    ),
    "synergie.py": ("https://www.synergie.es/busco-trabajo/", "synergie"),
    "upv_sie.py": ("self.OFFICIAL_APP_URL", "upv_sie"),
    "wwr.py": ("self.RSS_FEEDS[0]", "wwr"),
    "greenhouse_spain.py": ('"https://boards.eu.greenhouse.io/"', "greenhouse"),
}

for filename, (url_expr, name) in patches.items():
    filepath = base_dir / filename
    if not filepath.exists():
        continue

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "def check_session(" in content:
        continue

    # Check if URL is a string literal or a variable
    if url_expr.startswith("http"):
        url_expr = f'"{url_expr}"'

    injection = f"""
    def check_session(self) -> tuple[bool, str]:
        try:
            import requests
            r = requests.get({url_expr}, headers={{"User-Agent": "Mozilla/5.0"}}, timeout=10)
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{{r.status_code}}"
        except Exception as e:
            return False, f"error_{{str(e)[:20]}}"
"""

    # Inject it right before def fetch_jobs
    match = re.search(r"( +)def fetch_jobs\(", content)
    if match:
        indent = match.group(1)
        # Fix indentation of injection
        injection_indented = "\n".join(
            (indent + line[4:] if line.startswith("    ") else line)
            for line in injection.split("\n")
        )

        new_content = (
            content[: match.start()] + injection_indented + content[match.start() :]
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Patched {filename}")
    else:
        print(f"Could not find fetch_jobs in {filename}")

# Special patch for consultancies.py
cons_file = base_dir / "consultancies.py"
with open(cons_file, "r", encoding="utf-8") as f:
    cons_content = f.read()

if "def check_session(" not in cons_content:
    injection = """
    def check_session(self) -> tuple[bool, str]:
        try:
            import requests
            from utils_stealth import get_stealth_headers
            r = requests.get(self.definition.index_url, headers=get_stealth_headers(), timeout=15)
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"
"""
    match = re.search(r"( +)def fetch_jobs\(", cons_content)
    if match:
        indent = match.group(1)
        injection_indented = "\n".join(
            (indent + line[4:] if line.startswith("    ") else line)
            for line in injection.split("\n")
        )
        new_content = (
            cons_content[: match.start()]
            + injection_indented
            + cons_content[match.start() :]
        )
        with open(cons_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("Patched consultancies.py")
