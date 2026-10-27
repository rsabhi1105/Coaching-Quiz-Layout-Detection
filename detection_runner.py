"""
detection_runner.py: run this one file.

    python detection_runner.py

1. Sets itself up the first time (.venv + packages), then restarts inside .venv.
2. Asks for a PDF (file picker window; falls back to typing a path).
3. Detects blocks on every page (no AI) and writes:
       output/<pdf name>/blocks.json        all blocks with kind, text, position
       output/<pdf name>/viewer.html        open in a browser: hover/tap a block to see what was detected
       output/<pdf name>/pages/p<N>.png     page images used by the viewer
4. Opens the viewer in your browser, then asks if you want to run another PDF.
"""

import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ── 1. setup: make sure we run inside .venv with the packages ───────────────────────────────
def _deps_ok() -> bool:
    try:
        import dotenv  # noqa: F401
        import psycopg  # noqa: F401
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_env():
    if _deps_ok():
        return
    if Path(sys.executable).resolve() != VENV_PY.resolve():
        if not VENV_PY.exists():
            print("First run: creating .venv ...")
            subprocess.check_call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        print("Installing packages (one time) ...")
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
        sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:]))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])


# ── 2. ask for the PDF ───────────────────────────────────────────────────────────────────────
def ask_pdf() -> Path | None:
    if len(sys.argv) > 1:
        return Path(sys.argv[1].strip('"'))
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(title="Choose a book PDF", filetypes=[("PDF files", "*.pdf")],
                                            initialdir=str(ROOT / "samples"))
        root.destroy()
        if chosen:
            return Path(chosen)
    except Exception:
        pass
    typed = input("PDF path (Enter to quit): ").strip().strip('"')
    return Path(typed) if typed else None


# ── 3. viewer ────────────────────────────────────────────────────────────────────────────────
COLORS = {
    "section": "#dc2626", "subsection": "#ea580c", "heading": "#b91c1c", "activity": "#7e22ce",
    "info_box_head": "#7e22ce", "question_head": "#0284c7", "exercise_head": "#0284c7",
    "summary_head": "#db2777", "group_activity_head": "#db2777", "question": "#1d4ed8",
    "option": "#38bdf8", "paragraph": "#059669", "caption": "#6b7280", "figure": "#f59e0b",
}

VIEWER = """<!doctype html>
<html lang="hi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · detected blocks</title>
<style>
  :root { --bg:#f5f5f4; --card:#fff; --ink:#1c1917; --muted:#78716c; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }
  header { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid #e7e5e4;
           padding:10px 16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  header b { font-size:15px; }
  header .stats { color:var(--muted); font-size:12px; }
  label { font-size:13px; display:flex; gap:6px; align-items:center; cursor:pointer; }
  main { display:flex; gap:16px; padding:16px; align-items:flex-start; }
  .pages { flex:1; display:flex; flex-direction:column; align-items:center; gap:16px; min-width:0; }
  .page { position:relative; width:100%; max-width:860px; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.12); }
  .page img { display:block; width:100%; height:auto; }
  .page .no { position:absolute; left:-2px; top:-22px; font-size:12px; color:var(--muted); }
  .blk { position:absolute; border:1.5px solid transparent; border-radius:3px; cursor:pointer; }
  .blk:hover, .blk.sel { border-color:var(--c); background:color-mix(in srgb, var(--c) 12%, transparent); }
  body.all .blk { border-color:var(--c); }
  .blk .tag { display:none; position:absolute; top:-15px; left:-1px; font-size:10px; line-height:14px; padding:0 4px;
              color:#fff; background:var(--c); border-radius:3px 3px 0 0; white-space:nowrap; }
  .blk:hover .tag, .blk.sel .tag, body.all .blk .tag { display:block; }
  aside { position:sticky; top:64px; width:340px; max-height:calc(100vh - 80px); overflow:auto; background:var(--card);
          border:1px solid #e7e5e4; border-radius:10px; padding:14px; }
  aside h3 { margin:0 0 6px; font-size:13px; color:var(--muted); font-weight:600; }
  aside .kind { display:inline-block; color:#fff; border-radius:999px; padding:1px 10px; font-size:12px; }
  aside pre { white-space:pre-wrap; font:15px/1.6 system-ui,sans-serif; margin:10px 0 0; }
  aside .meta { color:var(--muted); font-size:12px; margin-top:8px; }
  .legend { display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; }
  .legend span { font-size:11px; color:#fff; border-radius:999px; padding:0 8px; }
  @media (max-width: 900px) { main { flex-direction:column; } aside { position:static; width:100%; } }
</style></head>
<body>
<header>
  <b>__TITLE__</b>
  <span class="stats">__STATS__</span>
  <label><input type="checkbox" id="all"> Show all boxes</label>
</header>
<main>
  <div class="pages" id="pages"></div>
  <aside id="panel">
    <h3>Hover or tap a block</h3>
    <div id="info" class="meta">The detected type and text appear here.</div>
    <div class="legend" id="legend"></div>
  </aside>
</main>
<script>
const DATA = __DATA__;
const COLORS = __COLORS__;
const pagesEl = document.getElementById("pages"), info = document.getElementById("info");
const byId = {};
for (const p of DATA.pages) {
  const page = document.createElement("div");
  page.className = "page";
  page.style.aspectRatio = p.width + " / " + p.height;
  page.innerHTML = '<span class="no">Page ' + p.page_no + '</span><img loading="lazy" src="pages/p' + p.page_no + '.png" alt="">';
  for (const b of p.blocks) {
    byId[b.id] = b;
    const [x0, y0, x1, y1] = b.bbox;
    const d = document.createElement("div");
    d.className = "blk"; d.dataset.id = b.id;
    d.style.cssText = "left:" + x0*100 + "%;top:" + y0*100 + "%;width:" + (x1-x0)*100 + "%;height:" + (y1-y0)*100 + "%;--c:" + (COLORS[b.kind] || "#000");
    d.innerHTML = '<span class="tag">' + b.kind + '</span>';
    page.appendChild(d);
  }
  pagesEl.appendChild(page);
}
let sel = null;
function show(el) {
  const b = byId[el.dataset.id];
  const extra = [b.source ? "source: " + b.source : "", b.number ? "no. " + b.number : "", b.label ? "option " + b.label : ""].filter(Boolean).join(" · ");
  info.innerHTML = '<span class="kind" style="background:' + (COLORS[b.kind] || "#000") + '">' + b.kind + '</span>'
    + '<pre></pre><div class="meta">' + b.id + (extra ? " · " + extra : "") + " · bbox " + b.bbox.join(", ") + '</div>';
  info.querySelector("pre").textContent = b.text || "(figure, no text)";
}
// one listener for the whole document, not one per box
pagesEl.addEventListener("mouseover", e => { const el = e.target.closest(".blk"); if (el && !sel) show(el); });
pagesEl.addEventListener("click", e => {
  const el = e.target.closest(".blk"); if (!el) return;
  if (sel) sel.classList.remove("sel");
  sel = (sel === el) ? null : el;
  if (sel) { sel.classList.add("sel"); show(sel); }
});
document.getElementById("all").addEventListener("change", e => document.body.classList.toggle("all", e.target.checked));
document.getElementById("legend").innerHTML = Object.entries(DATA.stats).map(([k, n]) =>
  '<span style="background:' + (COLORS[k] || "#000") + '">' + k + ' ' + n + '</span>').join("");
</script>
</body></html>
"""


def write_viewer(pdf: Path, result: dict, out: Path):
    import pymupdf
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf))
    for i, page in enumerate(doc, start=1):
        page.get_pixmap(dpi=110).save(str(pages_dir / f"p{i}.png"))
    stats = f'{result["page_count"]} pages · ' + " · ".join(f"{k} {v}" for k, v in sorted(result["stats"].items()))
    html = (VIEWER.replace("__TITLE__", pdf.stem.replace("<", ""))
            .replace("__STATS__", stats)
            .replace("__COLORS__", json.dumps(COLORS))
            .replace("__DATA__", json.dumps(result, ensure_ascii=False).replace("</", "<\\/")))
    path = out / "viewer.html"
    path.write_text(html, encoding="utf-8")
    return path


# ── 4. run ───────────────────────────────────────────────────────────────────────────────────
def run_one(pdf: Path):
    from books_layout.extract import extract_document

    if not pdf.exists() or pdf.suffix.lower() != ".pdf":
        print(f"Not a PDF file: {pdf}")
        return
    out = ROOT / "output" / pdf.stem.replace(" ", "_")
    out.mkdir(parents=True, exist_ok=True)

    print(f"\nDetecting blocks in: {pdf.name}")
    t = time.perf_counter()
    result = extract_document(str(pdf))
    secs = time.perf_counter() - t
    (out / "blocks.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"  pages   : {result['page_count']}   time: {secs:.1f}s   body font size: {result['body_font_size']}")
    for kind, n in sorted(result["stats"].items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<20}{n}")
    if result["flags"]:
        print("  needs attention:")
        for f in result["flags"]:
            print(f"    page {f['page']}: {f['issue']}")

    print("Rendering page images for the viewer ...")
    viewer = write_viewer(pdf, result, out)
    print(f"\nJSON   : {out / 'blocks.json'}")
    print(f"Viewer : {viewer}")
    webbrowser.open(viewer.as_uri())


def db_note():
    try:
        from books_layout.db import check
        info = check()
        print(f"Database: connected ({info['dsn']})")
    except Exception as e:
        print(f"Database: not reachable ({type(e).__name__}). Detection still works; start docker to use the DB.")


def main():
    ensure_env()
    sys.path.insert(0, str(ROOT))
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("Book layout detection (no AI, runs locally)")
    db_note()
    while True:
        pdf = ask_pdf()
        if pdf is None:
            print("No file chosen. Bye.")
            return
        run_one(pdf)
        if len(sys.argv) > 1:
            return
        again = input("\nRun another PDF? (y/n): ").strip().lower()
        if again not in ("y", "yes", "haan", "h"):
            return


if __name__ == "__main__":
    main()
