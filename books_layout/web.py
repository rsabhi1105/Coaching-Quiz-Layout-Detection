"""
The local upload form.

Three screens: pick a folder, describe the book, check the chapters it found. Nothing
is written until the third screen is submitted, so the operator corrects a wrong title
or unticks the answer key before any row exists.

Served by Python's own HTTP server. One person uses this on one laptop; a web framework
would be a fourth dependency for a page that never leaves localhost.

    python -m books_layout.cli upload
"""

import html
import json
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .config import PROJECT_DIR
from .ingest import ingest_folder, read_folder
from .platform import models

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f1f4f2;color:#0f1512;
     font:15px/1.55 Inter,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:40px 24px 80px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#6b7572;font-size:13.5px;margin:0 0 24px}
.card{background:#fff;border:1px solid #e2e7e4;border-radius:16px;padding:22px;margin-bottom:18px}
label{display:block;font-size:12.5px;font-weight:600;color:#4b544f;margin:0 0 5px}
input[type=text],input[type=number],select,textarea{
  width:100%;padding:9px 11px;border:1px solid #e2e7e4;border-radius:9px;
  font:inherit;font-size:14px;background:#fff;color:#0f1512}
input:focus,select:focus,textarea:focus{outline:none;border-color:#059669;box-shadow:0 0 0 3px #05966922}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.field{margin-bottom:14px}
button{background:#059669;color:#fff;border:0;border-radius:999px;
       padding:10px 22px;font:inherit;font-weight:600;font-size:14px;cursor:pointer}
button:hover{background:#047857}
button.ghost{background:#fff;color:#4b544f;border:1px solid #e2e7e4}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;color:#6b7572;font-weight:600;
   padding:0 8px 8px;border-bottom:1px solid #e2e7e4}
td{padding:7px 8px;border-bottom:1px solid #f0f3f1;vertical-align:middle}
td input[type=text]{padding:6px 9px}
td.n input{width:64px}
.muted{color:#6b7572;font-size:13px}
.warn{background:#fffbeb;border:1px solid #fde68a;border-radius:11px;padding:12px 14px;
      font-size:13.5px;margin-bottom:16px}
.err{background:#fef2f2;border:1px solid #fecaca;border-radius:11px;padding:12px 14px;
     font-size:13.5px;margin-bottom:16px}
.ok{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:11px;padding:12px 14px;
    font-size:13.5px;margin-bottom:16px}
pre.log{background:#0f1512;color:#d7e3dc;border-radius:12px;padding:16px;
        font:12.5px/1.65 ui-monospace,Consolas,monospace;white-space:pre-wrap;margin:0}
a{color:#047857}
"""


def page(title, body):
    return (f"<!doctype html><html lang=en><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style>"
            f"<div class=wrap>{body}</div></html>").encode("utf-8")


def esc(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def options(rows, selected=None, blank="—"):
    out = [f"<option value=''>{blank}</option>"]
    for value, label in rows:
        sel = " selected" if selected is not None and str(selected) == str(value) else ""
        out.append(f"<option value='{esc(value)}'{sel}>{esc(label)}</option>")
    return "".join(out)


def slugify(text):
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:120]


# ── screens ───────────────────────────────────────────────────────────────────

def screen_folder(error=""):
    note = f"<div class=err>{esc(error)}</div>" if error else ""
    sample = PROJECT_DIR / "class_X_science"
    return page("Upload a book", f"""
      <h1>Upload a book</h1>
      <p class=sub>One folder of chapter PDFs becomes one book on the shelf.</p>
      {note}
      <form method=post action=/scan>
        <div class=card>
          <div class=field>
            <label for=folder>Folder of chapter PDFs</label>
            <input type=text id=folder name=folder required
                   value="{esc(sample if sample.is_dir() else '')}"
                   placeholder="D:\\books\\class_X_science">
            <p class=muted style="margin:7px 0 0">
              Files named like <code>Ch01 - Chemical Reactions.pdf</code> give the chapter
              number and title automatically. You can fix both on the next screen.</p>
          </div>
          <button type=submit>Scan folder</button>
        </div>
      </form>""")


def screen_details(folder, rows, M):
    Visibility = M["Visibility"]
    boards = [(b.id, b.name) for b in M["Board"].objects.all()]
    levels = [(l.id, l.name) for l in M["EducationalLevel"].objects.all()]
    subjects = [(s.id, getattr(s, "name", str(s))) for s in M["LevelSubject"].objects.all()]
    institutes = [(i.id, i.name) for i in M["Institute"].objects.all()]

    found = len(rows)
    ticked = sum(1 for r in rows if r["include"])
    broken = [r for r in rows if r.get("error")]
    warn = (f"<div class=err>{len(broken)} file(s) could not be opened and are excluded: "
            f"{esc(', '.join(r['file'] for r in broken))}</div>" if broken else "")

    body = []
    for i, r in enumerate(rows):
        checked = " checked" if r["include"] else ""
        disabled = " disabled" if r.get("error") else ""
        body.append(f"""
          <tr>
            <td><input type=checkbox name=inc_{i} value=1{checked}{disabled}></td>
            <td class=n><input type=text name=num_{i} value="{esc(r['number'] if r['number'] is not None else '')}"></td>
            <td><input type=text name=title_{i} value="{esc(r['title'])}"></td>
            <td class=muted>{r['pages'] or '—'}</td>
            <td class=muted>{esc(r['file'])}</td>
            <input type=hidden name=path_{i} value="{esc(r['path'])}">
          </tr>""")

    return page("Book details", f"""
      <h1>Book details</h1>
      <p class=sub>{found} PDF(s) found in {esc(folder)} — {ticked} ticked to upload.</p>
      {warn}
      <form method=post action=/upload>
        <input type=hidden name=count value="{found}">
        <div class=card>
          <div class=field>
            <label for=title>Title</label>
            <input type=text id=title name=title required placeholder="NCERT Science — Class 10"
                   oninput="document.getElementById('slug').value =
                     this.value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,120)">
          </div>
          <div class=grid>
            <div class=field>
              <label for=slug>Slug <span class=muted>(in the student's URL)</span></label>
              <input type=text id=slug name=slug required>
            </div>
            <div class=field>
              <label for=language>Language</label>
              <select id=language name=language>
                <option value="">Detect from the pages</option>
                <option value="hi">Hindi</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>
          <div class=grid>
            <div class=field><label for=author>Author</label>
              <input type=text id=author name=author placeholder="NCERT"></div>
            <div class=field><label for=publisher>Publisher</label>
              <input type=text id=publisher name=publisher placeholder="NCERT"></div>
          </div>
          <div class=grid3>
            <div class=field><label for=board>Board</label>
              <select id=board name=board>{options(boards)}</select></div>
            <div class=field><label for=level>Class</label>
              <select id=level name=level>{options(levels)}</select></div>
            <div class=field><label for=subject>Subject</label>
              <select id=subject name=subject>{options(subjects)}</select></div>
          </div>
          <div class=grid>
            <div class=field>
              <label for=visibility>Who can see it</label>
              <select id=visibility name=visibility
                      onchange="document.getElementById('inst').style.display =
                                this.value === '{Visibility.INSTITUTE}' ? '' : 'none'">
                <option value="{Visibility.PUBLIC}">Public — everyone on the platform</option>
                <option value="{Visibility.INSTITUTE}">Institute — only this institute</option>
              </select>
            </div>
            <div class=field id=inst style="display:none">
              <label for=institute>Institute</label>
              <select id=institute name=institute>{options(institutes)}</select>
            </div>
          </div>
          <div class=grid>
            <div class=field><label for=edition_year>Edition year</label>
              <input type=number id=edition_year name=edition_year min=1900 max=2100></div>
            <div class=field><label for=cover_color>Cover gradient <span class=muted>(optional)</span></label>
              <input type=text id=cover_color name=cover_color placeholder="from-emerald-200 to-emerald-50"></div>
          </div>
          <div class=field><label for=description>Description</label>
            <textarea id=description name=description rows=2></textarea></div>
        </div>

        <div class=card>
          <h1 style="font-size:16px;margin:0 0 3px">Chapters</h1>
          <p class=sub style="margin-bottom:14px">
            Untick anything that is not a chapter. Front matter and answer keys start unticked.</p>
          <table>
            <tr><th style="width:34px"></th><th style="width:78px">No.</th>
                <th>Title</th><th style="width:62px">Pages</th><th style="width:34%">File</th></tr>
            {''.join(body)}
          </table>
        </div>

        <button type=submit>Upload to the library</button>
        <a href="/" style="margin-left:14px" class=muted>Start over</a>
      </form>""")


# ── server ────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "books_layout"

    def log_message(self, *a):            # the console belongs to the progress output
        pass

    def _send(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _form(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(screen_folder())
        else:
            self._send(page("Not found", "<h1>Not found</h1><p><a href='/'>Start again</a></p>"), 404)

    def do_POST(self):
        if self.path == "/scan":
            self._scan()
        elif self.path == "/upload":
            self._upload()
        else:
            self._send(page("Not found", "<h1>Not found</h1>"), 404)

    def _scan(self):
        folder = self._form().get("folder", "").strip().strip('"')
        if not folder or not Path(folder).is_dir():
            return self._send(screen_folder(f"Not a folder: {folder}"))
        rows = read_folder(folder)
        if not rows:
            return self._send(screen_folder(f"No PDFs in {folder}"))
        self._send(screen_details(folder, rows, models()))

    def _upload(self):
        form = self._form()
        count = int(form.get("count") or 0)
        rows = []
        for i in range(count):
            number = form.get(f"num_{i}", "").strip()
            rows.append({
                "path": form.get(f"path_{i}", ""),
                "title": form.get(f"title_{i}", "").strip(),
                "number": int(number) if number.isdigit() else None,
                "include": form.get(f"inc_{i}") == "1",
            })

        M = models()
        slug = form.get("slug") or slugify(form.get("title", ""))
        existing = M["Book"].objects.filter(slug=slug).first()

        # The response streams: each chapter takes seconds and a blank tab for a minute
        # looks like a hang.
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        def out(chunk):
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        note = ""
        if existing:
            note = (f"<div class=warn><b>{esc(slug)}</b> already exists — its details are being "
                    f"replaced with what you entered, and re-uploaded chapters have their blocks "
                    f"rebuilt. Students' highlights and notes are kept.</div>")
        out(f"<!doctype html><html lang=en><meta charset=utf-8>"
            f"<title>Uploading</title><style>{CSS}</style><div class=wrap>"
            f"<h1>Uploading</h1><p class=sub>Parsing each chapter and writing it to the library.</p>"
            f"{note}<div class=card><pre class=log>")

        form["slug"] = slug
        try:
            result = ingest_folder(form, rows, progress=lambda m: out(html.escape(m) + "\n"))
        except Exception as exc:
            out(f"\n{html.escape(str(exc))}</pre></div>"
                f"<div class=err>Nothing was written.</div>"
                f"<a href='/'>Try again</a></div></html>")
            return

        ok = [c for c in result["chapters"] if c["ok"]]
        bad = [c for c in result["chapters"] if not c["ok"]]
        ocr = [c for c in ok if c["status"] == "needs_ocr"]

        out("</pre></div>")
        out(f"<div class=ok><b>{esc(result['title'])}</b> is on the shelf — "
            f"{len(ok)} chapter(s), {sum(c['blocks'] for c in ok)} blocks, "
            f"language {esc(result['language'])}.</div>")
        if ocr:
            out(f"<div class=warn>{len(ocr)} chapter(s) have little usable text and are marked "
                f"<code>needs_ocr</code>: {esc(', '.join(str(c['number']) for c in ocr))}. "
                f"They still open, but their text will be thin.</div>")
        if bad:
            items = "".join(f"<li>Chapter {c['number']} — {esc(c['error'])}</li>" for c in bad)
            out(f"<div class=err>{len(bad)} chapter(s) failed:<ul>{items}</ul>"
                f"Fix those files and run the folder again; the rest are already in.</div>")
        out(f"<p><a href='http://localhost:3000/dashboard/books/{esc(result['slug'])}'>"
            f"Open it in the reader</a> &nbsp;·&nbsp; <a href='/'>Upload another book</a></p>"
            f"</div></html>")


def _free_port(preferred=8765):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def serve(port=None, open_browser=True):
    models()                      # fail now, with a clear error, not on the first click
    port = port or _free_port()
    url = f"http://localhost:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Upload form: {url}\nCtrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()
