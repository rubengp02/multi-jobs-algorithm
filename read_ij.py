import re

with open("rpi_consultancies.py", encoding="utf-8") as f:
    text = f.read()
match = re.search(
    r'if getattr\(self\.definition, "strategy", ""\) == "infojobs":.*?return jobs',
    text,
    re.DOTALL,
)
if match:
    print(match.group(0))
