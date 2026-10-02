with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

start = -1
for i, l in enumerate(lines):
    if l.startswith("def process_jobs("):
        start = i
        break

for i in range(start, start + 100):
    print(lines[i], end="")
