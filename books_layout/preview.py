"""Draw detected blocks on page images, to eyeball the extraction."""

from pathlib import Path

import pymupdf

COLORS = {
    "section": (0.85, 0.1, 0.1), "subsection": (0.9, 0.4, 0), "heading": (0.7, 0.2, 0.2),
    "activity": (0.5, 0, 0.7), "info_box_head": (0.5, 0, 0.7), "question_head": (0, 0.5, 0.9),
    "exercise_head": (0, 0.5, 0.9), "summary_head": (0.8, 0, 0.5), "group_activity_head": (0.8, 0, 0.5),
    "question": (0, 0.35, 1), "option": (0.2, 0.7, 1), "paragraph": (0.06, 0.6, 0.35),
    "caption": (0.45, 0.45, 0.45), "figure": (0.95, 0.55, 0),
}


def render(pdf_path: str, result: dict, pages: list[int], out_dir: Path, dpi: int = 110) -> list[Path]:
    doc = pymupdf.open(pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for pno in pages:
        page = doc[pno - 1]
        W, H = page.rect.width, page.rect.height
        for b in result["pages"][pno - 1]["blocks"]:
            x0, y0, x1, y1 = b["bbox"]
            r = pymupdf.Rect(x0 * W, y0 * H, x1 * W, y1 * H)
            color = COLORS.get(b["kind"], (0, 0, 0))
            page.draw_rect(r, color=color, width=1.1)
            page.insert_text((r.x0, max(6, r.y0 - 1.5)), b["kind"], fontsize=6, color=color)
        path = out_dir / f"{Path(pdf_path).stem}_p{pno}.png"
        page.get_pixmap(dpi=dpi).save(str(path))
        written.append(path)
    return written
