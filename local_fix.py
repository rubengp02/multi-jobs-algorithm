import re

FILE = "rpi_consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# The corrupted part looks like:
# if response.status_code in {403, 429} or any(marker in body_l for marker in CHALLENGE_MARKERS):
#                     if self.source == " grupo_noas\ and \captcha\ in body_l and response.status_code == 200:
#                         pass # False positive: Google reCAPTCHA is just in the footer
#                     else:

# I'll use regex to match this and replace it cleanly.
pattern = r"if response\.status_code in \{403, 429\} or any\(marker in body_l for marker in CHALLENGE_MARKERS\):.*?else:"
replacement = 'if response.status_code in {403, 429} or (any(marker in body_l for marker in CHALLENGE_MARKERS) and not (self.source == "grupo_noas" and response.status_code == 200)):'

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
with open(FILE, "w", encoding="utf-8") as f:
    f.write(new_content)
