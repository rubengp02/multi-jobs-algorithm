import re

with open("main_rpi_commands.py", "r", encoding="utf-8") as f:
    text = f.read()

match = re.search(
    r'        if cmd in \{"/health".*?ctx\.notifier\.send_message\("\\n"\.join\(health_lines\)\)\n            continue',
    text,
    re.DOTALL,
)
if match:
    print(match.group(0))
else:
    print("Not found")
