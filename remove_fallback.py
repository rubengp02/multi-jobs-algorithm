def remove_fallback():
    with open("providers/linkedin.py", "r", encoding="utf-8") as f:
        text = f.read()

    import re

    # Match the block exactly
    text = re.sub(
        r"# --- Fallback to 1h.*?# ----------------------------------------------",
        "",
        text,
        flags=re.DOTALL,
    )

    with open("providers/linkedin.py", "w", encoding="utf-8") as f:
        f.write(text)


remove_fallback()
