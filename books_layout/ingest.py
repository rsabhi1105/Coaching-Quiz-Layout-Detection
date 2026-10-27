"""
Folder of chapter PDFs -> rows in the platform's books tables.

The parser in `books_layout.extract` describes a block with one word (`kind`). The
platform splits that across three columns — `type` (what it is), `role` (what part of
the chapter it belongs to) and `level` (how deep the heading sits) — because the reader
queries them separately: the chapter contents panel asks for headings and then keeps
only the ones whose role is a section. KIND_MAP below is where the one word is taken
apart; getting it wrong shows up as an empty contents panel, not as an error.

The original PDF is copied byte for byte. PyMuPDF can re-save a document and this code
deliberately never does: the student downloads the publisher's file, and the block
boxes are fractions of the pages in *that* file.
"""

import hashlib
import json
import re
import shutil
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .extract import extract_document
from .platform import media_root, models

#: What this tool's JSON means, so a later reader cannot mistake it for the backend's
#: `document.v1` — same tables, different parser, fewer fields filled.
SCHEMA_VERSION = "books_layout.v1"
ENGINE_VERSION = "books_layout/0.2.0"

#: Below this, the page had so little usable text that the chapter is worth OCR.
#: Scores cluster near 1.0, so the useful threshold is high, not 0.5.
OCR_THRESHOLD = 0.90

#: kind -> (type, role, level). Type and role are the platform's own enums; level is
#: 1..3 on headings and 0 elsewhere.
KIND_MAP = {
    "heading":             ("heading",    "",               1),
    "section":             ("heading",    "section",        2),
    "subsection":          ("subheading", "subsection",     3),
    "activity":            ("heading",    "activity",       2),
    "question_head":       ("heading",    "questions",      2),
    "exercise_head":       ("heading",    "exercise",       2),
    "summary_head":        ("heading",    "summary",        2),
    "group_activity_head": ("heading",    "group_activity", 2),
    "info_box_head":       ("heading",    "info_box",       2),
    "paragraph":           ("para",       "",               0),
    "question":            ("question",   "",               0),
    "option":              ("option",     "",               0),
    "figure":              ("figure",     "",               0),
    "caption":             ("caption",    "",               0),
}

#: "4.2 भौतिक गुणधर्म" -> "4.2". Only headings carry one; a paragraph knowing its
#: section is a different job and nothing reads it yet.
SECTION_PATH_RE = re.compile(r"^(\d+(?:\.\d+)+)\s")

#: "Ch01 - Chemical Reactions and Equations.pdf" -> 1, "Chemical Reactions and Equations"
CHAPTER_FILE_RE = re.compile(r"^(?:ch(?:apter)?)\s*[-_ ]?(\d{1,3})\s*[-–_. ]*\s*(.*)$", re.I)


# ── reading the folder ────────────────────────────────────────────────────────

def detect_language(doc: dict) -> str:
    """`hi` when the page text is mostly Devanagari, else `en`.

    The parser does not report a language, and the platform stores one. Counting
    letters beats trusting the filename, which is usually English either way.
    """
    deva = latin = 0
    for page in doc["pages"][:5]:
        for block in page["blocks"]:
            for ch in block.get("text", ""):
                if not ch.isalpha():
                    continue
                name = unicodedata.name(ch, "")
                if name.startswith("DEVANAGARI"):
                    deva += 1
                elif name.startswith("LATIN"):
                    latin += 1
    return "hi" if deva > latin else "en"


def read_folder(folder) -> list[dict]:
    """Every PDF in the folder, with the chapter number and title its name implies.

    Page count is read here because the review screen shows it; the full parse waits
    until the operator has actually pressed upload.
    """
    import pymupdf

    rows = []
    for path in sorted(Path(folder).glob("*.pdf")):
        stem = path.stem
        match = CHAPTER_FILE_RE.match(stem)
        number = int(match.group(1)) if match else None
        title = (match.group(2).strip() if match else stem).strip(" -–_")
        try:
            with pymupdf.open(path) as doc:
                pages = doc.page_count
        except Exception as exc:                            # a file we cannot even open
            rows.append({"file": path.name, "path": str(path), "number": number,
                         "title": title, "pages": 0, "include": False, "error": str(exc)})
            continue
        rows.append({
            "file": path.name,
            "path": str(path),
            "number": number,
            "title": title or f"Chapter {number}" if number else title,
            "pages": pages,
            # Front matter (chapter 0) and the answer key are rarely wanted as chapters,
            # so they start unticked rather than being hidden — the operator decides.
            "include": number is not None and number > 0 and not _looks_like_back_matter(title),
            "error": "",
        })
    return rows


def _looks_like_back_matter(title: str) -> bool:
    return bool(re.search(r"^(answers?|appendix|index|glossary|front\s*matter|preface|contents)\b",
                          title.strip(), re.I))


# ── writing ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _book(form: dict, language: str, M: dict):
    """Create the book, or update the one that already has this slug.

    An existing book is updated, not left alone. The reason this tool exists is that
    `ingest_book` used get_or_create with defaults and so could never fix a book that
    had been filed wrongly — which is how every book so far ended up public and
    institute-less. The form always carries the full set of fields, so what the
    operator confirmed on screen is what the row ends up saying.
    """
    Book, Visibility = M["Book"], M["Visibility"]
    fields = {
        "title": form["title"],
        "subtitle": form.get("subtitle", ""),
        "author": form.get("author", ""),
        "publisher": form.get("publisher", ""),
        "language": language,
        "description": form.get("description", ""),
        "cover_color": form.get("cover_color", ""),
        "visibility": form["visibility"],
        "board_id": form.get("board") or None,
        "level_id": form.get("level") or None,
        "subject_id": form.get("subject") or None,
        # A public book belongs to no tenant; keeping an institute on it would let a
        # later visibility flip quietly expose that institute.
        "institute_id": (form.get("institute") or None
                         if form["visibility"] == Visibility.INSTITUTE else None),
    }
    if form.get("edition_year"):
        fields["edition_year"] = int(form["edition_year"])

    book, created = Book.objects.update_or_create(slug=form["slug"], defaults=fields)
    return book, created


def _chapter(book, row: dict, doc: dict, keys: dict, parse_ms: int, M: dict):
    BookChapter = M["BookChapter"]
    quality = min((p.get("text_quality", 1.0) for p in doc["pages"]), default=1.0)
    status = (BookChapter.ParseStatus.NEEDS_OCR if quality < OCR_THRESHOLD
              else BookChapter.ParseStatus.READY)
    blocks = sum(len(p["blocks"]) for p in doc["pages"])

    chapter, _ = BookChapter.objects.update_or_create(
        book=book, number=row["number"],
        defaults={
            "title": row["title"],
            "code": row["code"],
            "page_count": doc["page_count"],
            "file_key": keys["file_key"],
            "json_key": keys["json_key"],
            "mime": "application/pdf",
            "size_bytes": keys["size_bytes"],
            "sha256": keys["sha256"],
            "parse_status": status,
            "parse_error": "",
            "parse_ms": parse_ms,
            "engine_version": ENGINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "block_count": blocks,
            "text_quality": quality,
            "parsed_at": datetime.now(timezone.utc),
            "display_order": row["number"],
            "is_active": True,
        },
    )
    return chapter


def _blocks(chapter, doc: dict, M: dict) -> int:
    """Replace this chapter's blocks. Annotations are anchored by block id and quote,
    so they are not touched and survive a re-parse."""
    BookBlock = M["BookBlock"]
    BookBlock.objects.filter(chapter=chapter).delete()

    rows = []
    for page in doc["pages"]:
        for block in page["blocks"]:
            kind = block.get("kind", "paragraph")
            btype, role, level = KIND_MAP.get(kind, ("para", "", 0))
            text = block.get("text", "")
            x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
            path_match = SECTION_PATH_RE.match(text) if role in ("section", "subsection") else None
            rows.append(BookBlock(
                chapter=chapter,
                block_id=block.get("id", "")[:16],
                page_no=page["page_no"],
                order=block.get("order", 0),
                type=btype,
                role=role,
                level=level,
                text=text,
                section_path=path_match.group(1)[:20] if path_match else "",
                size=block.get("size", 0.0),
                q_number=str(block.get("number", ""))[:8],
                q_source=block.get("source", "") or "",
                option_label=str(block.get("label", ""))[:4],
                x0=x0, y0=y0, x1=x1, y1=y1,
            ))
    BookBlock.objects.bulk_create(rows, batch_size=1000)
    return len(rows)


def ingest_folder(form: dict, rows: list[dict], progress=None) -> dict:
    """Parse every ticked chapter and write the book. Returns a per-chapter report.

    One bad chapter does not stop the others: the summary names what failed so the
    operator can fix that file and run the folder again.
    """
    M = models()
    chapters = [r for r in rows if r.get("include") and r.get("number")]
    if not chapters:
        raise ValueError("no chapters were ticked")

    def say(msg):
        if progress:
            progress(msg)

    # Language is read from the first chapter; a book is not written in two languages.
    say(f"reading {Path(chapters[0]['path']).name}…")
    first = extract_document(chapters[0]["path"])
    language = form.get("language") or detect_language(first)

    book, created = _book(form, language, M)
    say(f"book {'created' if created else 'updated'}: {book.slug}")

    media = media_root()
    report = []
    for i, row in enumerate(chapters):
        row = dict(row, code=f"ch{row['number']:02d}")
        say(f"[{i + 1}/{len(chapters)}] chapter {row['number']} — {row['title']}")
        try:
            started = time.perf_counter()
            doc = first if i == 0 else extract_document(row["path"])
            parse_ms = int((time.perf_counter() - started) * 1000)

            src = Path(row["path"])
            rel = Path("books") / book.slug / f"{row['code']}.pdf"
            dest = media / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            # copyfile, never a PyMuPDF save: the bytes the student gets are the
            # publisher's bytes, and the block boxes describe those exact pages.
            shutil.copyfile(src, dest)

            json_rel = rel.with_suffix(".json")
            (media / json_rel).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

            keys = {"file_key": str(rel).replace("\\", "/"),
                    "json_key": str(json_rel).replace("\\", "/"),
                    "size_bytes": dest.stat().st_size,
                    "sha256": _sha256(dest)}

            chapter = _chapter(book, row, doc, keys, parse_ms, M)
            written = _blocks(chapter, doc, M)
            report.append({"number": row["number"], "title": row["title"], "ok": True,
                           "blocks": written, "pages": doc["page_count"],
                           "status": chapter.parse_status, "error": ""})
            say(f"    {written} blocks, {doc['page_count']} pages, {chapter.parse_status}")
        except Exception as exc:
            report.append({"number": row["number"], "title": row["title"], "ok": False,
                           "blocks": 0, "pages": 0, "status": "failed", "error": str(exc)})
            say(f"    FAILED: {exc}")

    live = book.chapters.filter(is_deleted=False, is_active=True)
    book.total_chapters = live.count()
    book.total_pages = sum(c.page_count for c in live)
    # A chapter needing OCR still reads; the book stays open and the summary says which.
    book.status = M["Book"].Status.READY if any(r["ok"] for r in report) else M["Book"].Status.FAILED
    book.save(update_fields=["total_chapters", "total_pages", "status", "updated_at"])

    return {"slug": book.slug, "title": book.title, "created": created,
            "language": language, "chapters": report}
