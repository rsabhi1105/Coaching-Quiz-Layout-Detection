"""
Text repair for born-digital PDFs.

1. Fake bold: some PDFs draw each glyph twice, slightly shifted, to look bold. Same character at
   (almost) the same x origin -> keep one.
2. Broken conjuncts: the font's Unicode map loses a "र" or maps "श" to a Latin look-alike. These are
   per-font and stable, so a small replace table fixes them. Add rows when a new font shows new breaks.
"""

LIGATURE_FIXES = [
    ("ćृं", "शृं"), ("Ýांृ", "शृं"), ("Ýृं", "शृं"),
    ("ट्ॉ", "ट्रॉ"), ("श्े", "श्रे"), ("ड्ो", "ड्रो"), ("क्ि", "क्रि"),
]

EXTRA_OK = set("–—‘’“”।॥")


def dedupe_chars(chars: list[dict]) -> str:
    """chars: PyMuPDF rawdict span chars [{c, origin, bbox}] -> text without fake-bold double strikes."""
    out: list[dict] = []
    for ch in chars:
        if out:
            prev = out[-1]
            width = max(ch["bbox"][2] - ch["bbox"][0], 0.5)
            if ch["c"] == prev["c"] and abs(ch["origin"][0] - prev["origin"][0]) < 0.35 * width + 0.3:
                continue
        out.append(ch)
    return "".join(c["c"] for c in out)


def fix_text(text: str) -> str:
    for bad, good in LIGATURE_FIXES:
        text = text.replace(bad, good)
    return " ".join(text.split())


def text_quality(text: str) -> float:
    """0..1: share of characters that are normal Devanagari / ASCII / common punctuation.
    Low score -> broken font map or scanned page -> needs OCR."""
    if not text.strip():
        return 0.0
    good = sum(1 for c in text if c.isspace() or "ऀ" <= c <= "ॿ" or c.isascii() or c in EXTRA_OK)
    return round(good / len(text), 3)
