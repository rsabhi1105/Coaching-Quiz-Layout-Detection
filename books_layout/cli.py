"""
python -m books_layout.cli check-db          does the shared DB config reach Postgres
python -m books_layout.cli check-platform    does CoachingQuiz's Django import and read
python -m books_layout.cli upload            the local upload form (folder -> library)
python -m books_layout.cli extract <pdf> [--out output/]
python -m books_layout.cli preview <pdf> --pages 5,23 [--out output/preview]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from .config import PROJECT_DIR


def main(argv=None):
    ap = argparse.ArgumentParser(prog="books_layout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-db", help="connect to the platform DB with the shared config")
    sub.add_parser("check-platform", help="import CoachingQuiz's Django models and read a row")
    up = sub.add_parser("upload", help="open the local form: a folder of chapter PDFs -> the library")
    up.add_argument("--port", type=int, default=None)
    up.add_argument("--no-browser", action="store_true")
    ex = sub.add_parser("extract", help="PDF -> blocks JSON (no DB writes)")
    ex.add_argument("pdf")
    ex.add_argument("--out", default=str(PROJECT_DIR / "output"))
    pv = sub.add_parser("preview", help="draw detected blocks on page images")
    pv.add_argument("pdf")
    pv.add_argument("--pages", default="1")
    pv.add_argument("--out", default=str(PROJECT_DIR / "output" / "preview"))
    a = ap.parse_args(argv)

    if a.cmd == "check-db":
        from .db import check
        print(json.dumps(check(), indent=2))
        return

    if a.cmd == "check-platform":
        from .platform import media_root, models
        M = models()
        print(json.dumps({
            "models": sorted(M),
            "media_root": str(media_root()),
            "boards": [b.name for b in M["Board"].objects.all()],
            "levels": [l.name for l in M["EducationalLevel"].objects.all()],
            "institutes": [i.name for i in M["Institute"].objects.all()],
            "books": M["Book"].objects.count(),
        }, ensure_ascii=False, indent=2))
        return

    if a.cmd == "upload":
        from .web import serve
        serve(port=a.port, open_browser=not a.no_browser)
        return

    from .extract import extract_document
    t = time.perf_counter()
    result = extract_document(a.pdf)
    secs = time.perf_counter() - t

    if a.cmd == "extract":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{Path(a.pdf).stem}.blocks.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"file": str(path), "pages": result["page_count"], "seconds": round(secs, 2),
                          "body_font_size": result["body_font_size"], "stats": result["stats"],
                          "flags": result["flags"]}, ensure_ascii=False, indent=2))
    else:
        from .preview import render
        if a.pages.strip().lower() == "all":
            pages = list(range(1, result["page_count"] + 1))
        else:
            pages = [int(x) for x in a.pages.split(",") if x.strip()]
        for p in render(a.pdf, result, pages, Path(a.out)):
            print(p)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
