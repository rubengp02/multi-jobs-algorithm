import re

import fitz

doc = fitz.open("revista_foro.pdf")
email_regex = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
keywords = [
    "Inteligencia Artificial",
    "Machine Learning",
    "Python",
    "Visión",
    "Mantenimiento predictivo",
    "Automatización",
    "Computer Vision",
    "Deep Learning",
    "Data Science",
    "Data Engineer",
    "Ingeniero de Datos",
]

for i, page in enumerate(doc):
    text = page.get_text()
    if any(k.lower() in text.lower() for k in keywords):
        emails = list(set(email_regex.findall(text)))
        if emails:
            lines = [l for l in text.split("\n") if l.strip()]
            company = lines[0] if lines else "Unknown"
            # Filter out generic emails if possible, or just print them all
            print(f"Page {i + 1}: {company} | Emails: {emails}")
