import re

FILE = "rpi_consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

bad_chunk = r"""if response.status_code in {403, 429} or (any(marker in body_l for marker in CHALLENGE_MARKERS) and not (self.source == "grupo_noas" and response.status_code == 200)):
                    if self.source == " grupo_noas\ and \captcha\ in body_l and response.status_code == 200:
 pass # False positive: Google reCAPTCHA is just in the footer
 else:"""

replacement = 'if response.status_code in {403, 429} or (any(marker in body_l for marker in CHALLENGE_MARKERS) and not (self.source == "grupo_noas" and response.status_code == 200)):'

if bad_chunk in content:
    content = content.replace(bad_chunk, replacement)
else:
    # use regex
    content = re.sub(
        r"if response\.status_code in \{403, 429\}.*?else:",
        replacement,
        content,
        flags=re.DOTALL,
    )

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)
