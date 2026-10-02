import re

from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get(
    "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python",
    impersonate="chrome",
)
soup = BeautifulSoup(r.text, "html.parser")

text = ""
for s in soup.find_all("script"):
    if s.string and "__INITIAL_PROPS__" in s.string:
        text = s.string
        break

pattern = re.compile(
    r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\(\s*("(?:\\.|[^"\\])*")\s*\)\s*;?',
    re.DOTALL,
)
m = pattern.search(text)
if m:
    print("Match found! Length of captured group:", len(m.group(1)))
else:
    print("Match failed!")
