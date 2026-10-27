# books-layout-detection

Part of the **CoachingQuiz** product. Same product, same database, separate folder because it runs
**offline on a developer laptop**, not on the server.

```
coaching-quiz/
  CoachingQuiz-Ai-Plateform-v2/   backend: Django (schema owner) + aiohttp APIs + taskiq worker, Postgres, Redis
  CoachingQuiz-Ai-Frontend/       Next.js app (student / teacher dashboard, book reader)
  books-layout-detection/         THIS: book PDF -> structured data (sections, blocks with page positions, questions)
```

## What it does

Turns textbook PDFs (NCERT and others, Hindi + English) into data the platform uses for:
1. **Block-wise reader**: every heading / paragraph / question / figure has a box on its page, so the
   student can tap/hover a block and ask a doubt about exactly that block.
2. **Exam prep + notes**: chapter -> sections -> text, and the book's own questions (in-text + exercise,
   MCQ options split out) feed quizzes, mock tests and notes without re-reading the PDF.

No AI is used for extraction. PyMuPDF reads the text layer with positions and font sizes; rules decide
what each block is. Pages with no usable text (scans) are flagged for OCR (not built yet).

## Database: same as the platform

- Config is **not duplicated**. `books_layout/config.py` loads, first value wins:
  1. process env, 2. `./.env` (local overrides), 3. `../CoachingQuiz-Ai-Plateform-v2/shared/environment/.env.dev`
     (`.env.prod` when `HOST=production`).
- Inside docker the DB is `postgres:5432`; from the laptop it is `localhost:5433`, which is why `./.env`
  overrides only `POSTGRES_HOST` / `POSTGRES_PORT`. DB name, user and password come from the backend file.
- **Django owns the schema.** Tables are defined in `CoachingQuiz-Ai-Plateform-v2/django-service/apps/...`
  with migrations. This tool must never create or alter tables; it only reads/writes rows.
- **No models are described twice.** `books_layout/platform.py` starts the backend's own Django and
  imports `apps.books.models`, so there is no copy here to drift. A field renamed over there breaks
  this tool loudly instead of silently writing nothing. Check it with `cli check-platform`.

## Upload a book

```bash
.venv/Scripts/python -m books_layout.cli upload      # opens the form on localhost
```

One folder of chapter PDFs becomes one book. Three screens: pick the folder; fill the book's
details once (title, slug, author, language, board, class, subject, and **who can see it** —
Public or a single Institute); check the chapter list it read from the filenames
(`Ch01 - Title.pdf` -> number 1, title "Title"), fixing titles and unticking front matter or
answer keys. Nothing is written until that last screen is submitted.

What it writes, per chapter: the **original PDF copied byte for byte** to
`<backend>/media/books/<slug>/chNN.pdf` (never a PyMuPDF re-save — the student downloads the
publisher's file and the block boxes describe those exact pages), the parse JSON beside it,
one `book_chapters` row and its `book_blocks`.

Re-running the same folder **updates** the book, including its visibility and institute —
that is the point, since a book filed wrongly could not be corrected before. Re-uploaded
chapters have their blocks rebuilt; students' highlights and notes survive, because
annotations are anchored by block id and quote.

A chapter whose text layer is too thin is stored with `parse_status = needs_ocr` and still
opens; the summary screen names it.

## Run (parse only, no DB)

Easiest: `python detection_runner.py`. It sets up `.venv` on first run, opens a file picker for the PDF,
writes `output/<pdf name>/blocks.json` + `viewer.html` (hover/tap a block to see its kind and text) and
opens the viewer in the browser. `python detection_runner.py <pdf>` skips the picker. `run.ps1` does the
same steps with the older `output/preview/` images.

Step by step:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; use .venv/bin/python on Linux/macOS
.venv/Scripts/python -m books_layout.cli check-db            # proves the shared DB config works
.venv/Scripts/python -m books_layout.cli extract samples/ch04_hi.pdf
.venv/Scripts/python -m books_layout.cli preview samples/ch04_hi.pdf --pages 5,23   # boxes drawn on pages
```
Set `PYTHONIOENCODING=utf-8` on Windows consoles to print Hindi.

## Code map

| File | Job |
|---|---|
| `books_layout/config.py` | shared DB settings (see above) |
| `books_layout/db.py` | psycopg connection, `check()` |
| `books_layout/extract/text_fix.py` | removes fake-bold double letters, fixes broken conjuncts (per-font table), text quality score |
| `books_layout/extract/layout.py` | lines -> blocks: heading kinds by pattern + font size (body size calibrated per book), question/option zones, header/footer removal, figure detection |
| `books_layout/preview.py` | draws blocks on page images for checking |
| `books_layout/platform.py` | starts CoachingQuiz's Django; re-exports its models. **Defines none.** |
| `books_layout/ingest.py` | folder + form -> books / book_chapters / book_blocks; `KIND_MAP` splits one `kind` into the platform's `type` + `role` + `level` |
| `books_layout/web.py` | the local upload form (stdlib HTTP server) |
| `books_layout/cli.py` | `check-db`, `check-platform`, `upload`, `extract`, `preview` |
| `detection_runner.py` | one-file entry: setup, PDF picker, extract, HTML viewer |

## Output (`output/<name>.blocks.json`)

`pages[].blocks[]`: `id` (`p5-b3`), `order`, `kind`, `text`, `bbox` = `[x0, y0, x1, y1]` as **0..1 fractions of
the page** (so the frontend places boxes at any zoom/screen size), plus `number`/`source` on questions
(`in_text` | `exercise`) and `label` on MCQ options. Top level: `body_font_size`, `stats`, `flags`
(pages with no text layer or low text quality).

Block kinds: `section`, `subsection`, `heading`, `activity`, `info_box_head`, `question_head`,
`exercise_head`, `summary_head`, `group_activity_head`, `question`, `option`, `paragraph`, `caption`, `figure`.

## Rules for anyone changing this

- **PyMuPDF is AGPL-3.0.** Keep it in this offline tool. Do not import it in the served backend.
- No LLM calls in extraction. Cost must stay zero per page.
- Coordinates are always normalised 0..1, top-left origin.
- New font breaks a conjunct? Add a row to `LIGATURE_FIXES`, do not special-case in layout code.
- Test on `samples/ch04_hi.pdf` (NCERT Class 10 Science, Hindi, Ch. 4) after any change: expect
  5 sections, 11 subsections, 13 in-text + 15 exercise questions, 16 MCQ options.

## Known gaps

- Summary bullets ("आपने क्या सीखा") merge into one block; should split per bullet.
- Some pages use a second font with leftover breaks (e.g. "प्रक्रियाया", "द्ारा").
- No OCR path yet for scanned pages (planned: PaddleOCR Devanagari + PP-DocLayout, only for flagged pages).
- Page images (WebP) and figure crops are not produced yet.
- The parser does not report a language; `ingest.detect_language` counts Devanagari vs Latin letters.
