with open("/home/rubengaona/bots/bot_multi_jobs/main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "/health" in line:
        start_idx = i
        break
for i in range(start_idx, len(lines)):
    if "continue" in lines[i]:
        end_idx = i
        break

with open("/tmp/health_block.txt", "r", encoding="utf-8") as f:
    block_lines = f.readlines()

lines[start_idx : end_idx + 1] = block_lines

with open("/home/rubengaona/bots/bot_multi_jobs/main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
