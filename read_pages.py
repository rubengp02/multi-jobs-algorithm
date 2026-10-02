import fitz

doc = fitz.open("revista_foro.pdf")
for p in [47, 79, 114]:
    print(f"--- PAGE {p} ---")
    print(doc[p - 1].get_text()[:1000])
