import glob
import os
import re

provider_files = glob.glob("/home/rubengaona/bots/bot_multi_jobs/providers/*.py")
for fpath in provider_files:
    with open(fpath, "r", encoding="utf-8") as f:
        text = f.read()

    # Replace EXCLUDE_ROLE_STEMS = [...] or (...) with EXCLUDE_ROLE_STEMS = []
    # This regex looks for EXCLUDE_ROLE_STEMS = [ ... ] or ( ... ) across multiple lines
    new_text = re.sub(
        r"EXCLUDE_ROLE_STEMS\s*=\s*\[.*?\]",
        "EXCLUDE_ROLE_STEMS = []",
        text,
        flags=re.DOTALL,
    )
    new_text = re.sub(
        r"EXCLUDE_ROLE_STEMS\s*=\s*\(.*?\)",
        "EXCLUDE_ROLE_STEMS = []",
        new_text,
        flags=re.DOTALL,
    )

    if new_text != text:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"Cleaned {os.path.basename(fpath)}")

# Also ensure EXCLUDE_WORDS is empty in .env
with open("/home/rubengaona/bots/bot_multi_jobs/.env", "r") as f:
    env_text = f.read()
env_text = re.sub(r"(?m)^EXCLUDE_WORDS=.*$", "EXCLUDE_WORDS=", env_text)
with open("/home/rubengaona/bots/bot_multi_jobs/.env", "w") as f:
    f.write(env_text)
print("Cleaned .env EXCLUDE_WORDS")
