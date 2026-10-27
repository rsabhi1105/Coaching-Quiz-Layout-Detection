"""
PDF -> pages -> blocks, no AI.

Each block = one heading / paragraph / question / option / box title / caption / figure with a
bbox normalised to 0..1 of the page, so the frontend can place it at any zoom or screen size.

Kind rules, in order:
  * text patterns decide WHAT a heading is (4.2.1 -> subsection, क्रियाकलाप/Activity -> activity, ...)
  * font size relative to the book's body size decides WHETHER a line is a heading at all
    (body size = the size most characters use; calibrated per document, so no per-publisher constants)
  * a zone state (inside प्रश्न / अभ्यास) turns "1." lines into questions and "(a)" lines into options
Dropped: running headers/footers (repeat at the same height on many pages), page-sized background
images and coloured boxes behind text.
"""

import re
from collections import Counter

import pymupdf

from .text_fix import dedupe_chars, fix_text, text_quality

HEAD_PATTERNS = [
    ("subsection", re.compile(r"^\d+\.\d+\.\d+\s")),
    ("section", re.compile(r"^\d+\.\d+\s")),
    ("activity", re.compile(r"^(क्रियाकलाप|गतिविधि|Activity)\s*\d", re.I)),
    ("question_head", re.compile(r"^(प्रश्न|Questions?)$", re.I)),
    ("exercise_head", re.compile(r"^(अभ्यास|अभयास|Exercises?)$", re.I)),
    ("summary_head", re.compile(r"^(आपने क्या सीखा|आपने कया सीखा|What you have learnt)", re.I)),
    ("group_activity_head", re.compile(r"^(सामूहिक क्रियाकलाप|Group Activity)", re.I)),
    ("info_box_head", re.compile(r"^(क्या आप जानते|कया आप जानते|यह भी जानिए|Do you know|More to know)", re.I)),
]
QUESTION_RE = re.compile(r"^(\d{1,2})\.\s*")
OPTION_RE = re.compile(r"^\(([a-dA-D])\)\s*")
CAPTION_RE = re.compile(r"^(चित्र|सारणी|Figure|Fig\.|Table)\s*\d", re.I)
QUESTION_ZONES = {"question_head", "exercise_head"}
ZONE_ENDERS = {"section", "subsection", "summary_head", "group_activity_head", "activity", "info_box_head"}


def _norm(rect, w, h):
    x0, y0, x1, y1 = rect
    return [round(max(0, x0) / w, 4), round(max(0, y0) / h, 4), round(min(w, x1) / w, 4), round(min(h, y1) / h, 4)]


def _read_lines(page):
    """-> [{text, size, bold, bbox}] one entry per visual line, fake-bold removed."""
    raw = page.get_text("rawdict")
    lines = []
    for b in raw["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            text, sizes, bold = "", Counter(), False
            for s in ln["spans"]:
                t = dedupe_chars(s["chars"])
                text += t
                sizes[round(s["size"], 1)] += len(t.strip())
                bold |= "bold" in s["font"].lower() or bool(s["flags"] & 16)
            text = fix_text(text)
            if text:
                lines.append({"text": text, "size": sizes.most_common(1)[0][0] if sizes else 0,
                              "bold": bold, "bbox": list(ln["bbox"])})
    lines.sort(key=lambda l: (round(l["bbox"][1], 0), l["bbox"][0]))
    return lines


def _running_text_keys(pages_lines, heights):
    """Lines that repeat at the same height on >= 30% of pages (digits ignored) = header/footer."""
    seen = Counter()
    for lines, h in zip(pages_lines, heights):
        for ln in lines:
            y = ln["bbox"][1] / h
            if y < 0.08 or y > 0.90:
                seen[(re.sub(r"\d+", "#", ln["text"]), round(y, 2))] += 1
    limit = max(2, int(0.3 * len(pages_lines)))
    return {k for k, n in seen.items() if n >= limit}


#: Zero-width joiners survive PDF extraction and land inside words, sometimes with a
#: stray space beside them: NCERT Ch01 yields a heading the page prints as the Hindi
#: word for "exercises" but that carries a ZWJ and a space in the middle. The glyphs
#: are right, so the text is stored untouched; only the copy used for matching is
#: cleaned, or that heading is never recognised and the whole exercise section is lost.
_MATCH_NOISE = re.compile("[\u200b-\u200d\ufeff]")


def _for_match(text):
    return re.sub(r"\s+", " ", _MATCH_NOISE.sub("", text)).strip()


def _head_kind(text):
    probe = _for_match(text)
    for kind, rx in HEAD_PATTERNS:
        if rx.search(text) or rx.search(probe) or rx.search(probe.replace(" ", "")):
            return kind
    return "heading"


def _figures(page, text_rects):
    """Embedded images and clustered vector drawings that are not backgrounds and hold little text."""
    W, H = page.rect.width, page.rect.height
    page_area = W * H
    found = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()]
    try:
        found += list(page.cluster_drawings())
    except Exception:
        pass
    out = []
    for r in found:
        area = r.width * r.height
        if area < 1500 or area > 0.45 * page_area:
            continue
        covered = sum((r & t).get_area() for t in text_rects if r.intersects(t))
        if covered > 0.30 * area:
            continue  # coloured box behind text, not a figure
        if any(abs(r.x0 - o.x0) < 3 and abs(r.y0 - o.y0) < 3 for o in out):
            continue
        out.append(r)
    return out


def extract_document(path: str) -> dict:
    doc = pymupdf.open(path)
    pages_lines = [_read_lines(p) for p in doc]
    heights = [p.rect.height for p in doc]

    body = Counter()
    for lines in pages_lines:
        for ln in lines:
            body[ln["size"]] += len(ln["text"])
    body_size = body.most_common(1)[0][0] if body else 11
    running = _running_text_keys(pages_lines, heights)

    pages, zone, flags = [], None, []
    for pno, (page, lines) in enumerate(zip(doc, pages_lines), start=1):
        W, H = page.rect.width, page.rect.height
        page_text = " ".join(l["text"] for l in lines)
        quality = text_quality(page_text)
        if len(page_text) < 40:
            flags.append({"page": pno, "issue": "no_text_layer", "hint": "scanned page -> OCR"})
        elif quality < 0.97:
            flags.append({"page": pno, "issue": "low_text_quality", "score": quality})

        blocks = []
        cur = None
        prev_rect = None

        def close(c):
            if c:
                c["text"] = " ".join(c.pop("parts"))
                c["bbox"] = _norm(c.pop("rect"), W, H)
                blocks.append(c)

        for ln in lines:
            if (re.sub(r"\d+", "#", ln["text"]), round(ln["bbox"][1] / H, 2)) in running:
                continue
            t = ln["text"]
            # A bold line is a heading if it is clearly bigger than body text, or if it is at least
            # body size AND matches a known heading pattern (4.2.1, क्रियाकलाप, अभ्यास ...).
            named = _head_kind(t) if ln["bold"] and len(t) < 120 else "heading"
            is_head = ln["bold"] and len(t) < 120 and (
                ln["size"] >= body_size * 1.15 or (named != "heading" and ln["size"] >= body_size * 0.95))
            if is_head:
                kind = named
                if kind in QUESTION_ZONES:
                    zone = kind
                elif kind in ZONE_ENDERS:
                    zone = None
            elif CAPTION_RE.match(t):
                kind = "caption"
            elif zone and QUESTION_RE.match(t):
                kind = "question"
            elif zone and OPTION_RE.match(t):
                kind = "option"
            else:
                kind = "paragraph"

            rect = pymupdf.Rect(ln["bbox"])
            gap = rect.y0 - prev_rect.y1 if prev_rect is not None else 99
            continues = (
                cur is not None and not is_head and kind == "paragraph"
                and cur["kind"] in ("paragraph", "question", "option", "caption")
                and gap < 0.8 * ln["size"] and rect.x0 >= cur["rect"].x0 - 30
            )
            same_head = cur is not None and is_head and cur["kind"] == kind and gap < 0.6 * ln["size"]
            if continues or same_head:
                cur["parts"].append(t)
                cur["rect"] |= rect
            else:
                close(cur)
                cur = {"kind": kind, "parts": [t], "rect": rect, "size": ln["size"]}
                if kind == "question":
                    cur["number"] = int(QUESTION_RE.match(t).group(1))
                    cur["source"] = "exercise" if zone == "exercise_head" else "in_text"
                if kind == "option":
                    cur["label"] = OPTION_RE.match(t).group(1).lower()
            prev_rect = rect
        close(cur)

        text_rects = [pymupdf.Rect(b["bbox"][0] * W, b["bbox"][1] * H, b["bbox"][2] * W, b["bbox"][3] * H)
                      for b in blocks]
        for r in _figures(page, text_rects):
            blocks.append({"kind": "figure", "text": "", "bbox": _norm(r, W, H), "size": 0})

        blocks.sort(key=lambda b: (round(b["bbox"][1], 2), b["bbox"][0]))
        for i, b in enumerate(blocks):
            b["id"] = f"p{pno}-b{i}"
            b["order"] = i
        pages.append({"page_no": pno, "width": round(W, 1), "height": round(H, 1),
                      "text_quality": quality, "blocks": blocks})

    return {"source": str(path), "page_count": len(doc), "body_font_size": body_size,
            "pages": pages, "flags": flags,
            "stats": dict(Counter(b["kind"] for p in pages for b in p["blocks"]))}
