import fitz

doc = fitz.open("revista_foro.pdf")
for p in [21, 70]:
    print(f"--- PAGE {p} ---")
    print(doc[p - 1].get_text()[:600])
