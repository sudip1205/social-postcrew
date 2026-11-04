"""Files attached to a plan you wrote yourself (Manual run): images and PDFs of a problem, read once into a problem statement every agent
uses. Algorithm problems often come as a PDF of text and figures (a grid, a tree, a sample input drawn out), so a PDF is read two ways:
its text (pdftotext, exact words and numbers) and its pages as pictures (pdftoppm), which a vision model looks at with the text beside it.

Files: workspace/plans/<platform>/<plan id>/<file>; page pictures in .../pages/. The Reader (llm.agents.reader) writes the statement into the
plan: item["source"] = {"state": "reading" | "done" | "failed", "statement": {...}, "files": [...]}.
"""
import re
import shutil
import subprocess
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import monthly
from .llm import LLMError, make_backend

AGENT = "reader"
EXT = {".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image"}
MAX_MB, MAX_FILES, MAX_PAGES = 25, 6, 12
DPI, STRIP_PX, OVERLAP_PX, MAX_STRIPS = 220, 1500, 120, 24
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "the problem's name, as the material gives it (or a short name)"},
        "statement": {"type": "string", "description": "the full problem statement, in the material's own words, complete"},
        "input_output": {"type": "string", "description": "the input and output format, exactly"},
        "examples": {"type": "array", "items": {"type": "object", "properties": {
            "input": {"type": "string"}, "output": {"type": "string"}, "explanation": {"type": "string"}},
            "required": ["input", "output", "explanation"]}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "figures": {"type": "array", "items": {"type": "string"},
                    "description": "each figure, described so it can be redrawn: what it shows, its labels and numbers, where things are"},
        "solution_notes": {"type": "string", "description": "a solution, hints or an approach the material gives, as written (empty if none)"},
        "unclear": {"type": "array", "items": {"type": "string"}, "description": "what you could not read or is ambiguous"},
    },
    "required": ["title", "statement", "input_output", "examples", "constraints", "figures", "solution_notes", "unclear"],
}
SYSTEM = """You read the material a creator attached to a video plan: pages of a PDF (pictures of each page, plus the text pulled out of it)
and images. It is usually an algorithm or coding problem. Write down the problem exactly as the material states it, complete, so a script
writer and an animator who never see the files can teach it faithfully.

- The pictures are the pages in order, a tall page cut into overlapping strips from top to bottom (the strips overlap a little: do not
  read a line twice). Read the small print: sample inputs (copy every row of a grid exactly, character by character), constraints.
- A sample drawn as a coloured picture (a grid of coloured squares with a key) is data too: read it cell by cell with its key.
- Copy words, numbers, names, input and output formats, examples and constraints exactly. Never solve, improve or invent: if a value is not
  in the material, it is not in your answer. The pulled-out text is exact where it exists; use the pictures for what text cannot carry
  (figures, tables, formulas, handwriting, a scanned page) and to check the text's order.
- Describe every figure so it can be redrawn: what kind it is (grid, tree, graph, array, chart), every label and value, positions and arrows.
- Put a solution, hints or an approach only if the material gives one.
- List anything unreadable or ambiguous under unclear instead of guessing."""

_running = set()
_lock = threading.Lock()


def plan_dir(ws, platform, item_id):
    if not re.fullmatch(r"[a-z0-9]{6,32}", item_id or ""):
        raise ValueError("bad plan id")
    return Path(ws.root) / "plans" / platform / item_id


def _item(ws, platform, item_id):
    pool = monthly.load(ws, platform)
    item = monthly._item(pool, item_id)
    if not item.get("manual"):
        raise ValueError("files can be attached to your own plans only")
    return pool, item


def _update(ws, platform, item_id, fn):
    with monthly._lock:
        pool = monthly.load(ws, platform)
        item = monthly._item(pool, item_id)
        fn(item)
        ws.save_state(monthly._name(platform), pool)
        return item


def save_upload(ws, platform, item_id, name, rfile, length):
    """Store one uploaded file with the plan. Returns the plan's file list."""
    _pool, item = _item(ws, platform, item_id)
    name = Path(str(name or "file")).name
    ext = Path(name).suffix.lower()
    if ext not in EXT:
        raise ValueError(f"{name}: attach a PDF or an image ({', '.join(sorted(EXT))})")
    if length <= 0:
        raise ValueError("the file is empty")
    if length > MAX_MB * 1024 * 1024:
        raise ValueError(f"{name} is larger than {MAX_MB} MB")
    files = (item.get("source") or {}).get("files") or []
    if len(files) >= MAX_FILES:
        raise ValueError(f"a plan holds {MAX_FILES} files at most: remove one first")
    d = plan_dir(ws, platform, item_id)
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem)[:60] or "file"
    dest = d / f"{safe}-{uuid.uuid4().hex[:6]}{ext}"
    left = length
    with dest.open("wb") as f:
        while left > 0:
            chunk = rfile.read(min(1 << 20, left))
            if not chunk:
                f.close()
                dest.unlink(missing_ok=True)
                raise ValueError("the upload stopped before the end of the file")
            f.write(chunk)
            left -= len(chunk)
    if ext == ".pdf" and not dest.read_bytes()[:5].startswith(b"%PDF"):
        dest.unlink()
        raise ValueError(f"{name} is not a PDF")
    entry = {"name": name, "file": dest.name, "kind": EXT[ext], "bytes": length}

    def add(it):
        src = it.setdefault("source", {})
        src["files"] = (src.get("files") or []) + [entry]
        src["state"] = "new"
    return _update(ws, platform, item_id, add)["source"]


def remove_file(ws, platform, item_id, file):
    _item(ws, platform, item_id)
    d = plan_dir(ws, platform, item_id)

    def drop(it):
        src = it.get("source") or {}
        src["files"] = [f for f in src.get("files") or [] if f["file"] != file]
        src["state"] = "new" if src["files"] else "none"
        if not src["files"]:
            src.pop("statement", None)
    (d / Path(file).name).unlink(missing_ok=True)
    return _update(ws, platform, item_id, drop).get("source")


def pdf_parts(path, out_dir, runner=subprocess.run, max_pages=MAX_PAGES):
    """(text, [page pictures]) of a PDF. Missing poppler tools give what the other one could."""
    text, pages = "", []
    if shutil.which("pdftotext") or runner is not subprocess.run:
        try:
            r = runner(["pdftotext", "-layout", "-l", str(max_pages), str(path), "-"], capture_output=True, text=True, timeout=120)
            text = (r.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("pdftoppm") or runner is not subprocess.run:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(path).stem
        # A page is drawn sharp (DPI) and, when tall (a full-page screenshot of a web page), cut into overlapping strips: one shrunken picture
        # of a tall page leaves its small print (the sample input, a constraint) unreadable to the model.
        for n, (w_pt, h_pt) in enumerate(page_sizes(path, runner)[:max_pages], 1):
            w_px, h_px = int(w_pt / 72 * DPI), int(h_pt / 72 * DPI)
            y, k = 0, 0
            while y < h_px and len(pages) < MAX_STRIPS:
                k += 1
                out = out_dir / f"{stem}-p{n:02d}-{k:02d}"
                try:
                    runner(["pdftoppm", "-png", "-r", str(DPI), "-f", str(n), "-l", str(n), "-x", "0", "-y", str(y), "-W", str(w_px),
                            "-H", str(min(STRIP_PX, h_px - y)), "-singlefile", str(path), str(out)], capture_output=True, timeout=120)
                except (OSError, subprocess.SubprocessError):
                    break
                if Path(f"{out}.png").exists():
                    pages.append(Path(f"{out}.png"))
                if y + STRIP_PX >= h_px:
                    break
                y += STRIP_PX - OVERLAP_PX
    return text, pages


def page_sizes(path, runner=subprocess.run):
    """[(width, height) in points] of every page (pdfinfo); a letter page when it cannot tell."""
    try:
        r = runner(["pdfinfo", "-f", "1", "-l", str(MAX_PAGES), str(path)], capture_output=True, text=True, timeout=60)
        sizes = [(float(a), float(b)) for a, b in re.findall(r"Page\s+\d+\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", r.stdout or "")]
        if not sizes:
            m = re.search(r"Pages:\s+(\d+)", r.stdout or "")
            one = re.search(r"Page size:\s+([\d.]+)\s+x\s+([\d.]+)", r.stdout or "")
            if m and one:
                sizes = [(float(one.group(1)), float(one.group(2)))] * int(m.group(1))
        return sizes or [(612.0, 792.0)]
    except (OSError, subprocess.SubprocessError):
        return [(612.0, 792.0)]


def read(ws, platform, item_id, llm=None, runner=subprocess.run, log=print):
    """Read the plan's files into its problem statement (the Reader). Returns the plan's source."""
    _pool, item = _item(ws, platform, item_id)
    src = item.get("source") or {}
    files = src.get("files") or []
    if not files:
        return src
    d = plan_dir(ws, platform, item_id)
    images, texts = [], []
    for f in files:
        p = d / f["file"]
        if not p.exists():
            continue
        if f["kind"] == "pdf":
            t, pages = pdf_parts(p, d / "pages", runner)
            if t:
                texts.append(f"--- TEXT OF {f['name']} ---\n{t[:30000]}")
            images += pages
            if not t and not pages:
                texts.append(f"--- {f['name']}: could not be opened (is it password-protected?) ---")
        else:
            images.append(p)
    images = images[:MAX_STRIPS + MAX_FILES]
    cfg = ws.config()
    if llm is None:
        if cfg["llm"]["backend"] == "demo":
            from .demo import Demo
            llm = Demo(cfg, ws.secrets())
        else:
            llm = make_backend(cfg, ws.secrets())
    prompt = (f"The plan: {item.get('title', '')}\n" + (f"The creator's own details: {item['context']}\n" if item.get("context") else "")
              + f"\nAttached: {', '.join(f['name'] for f in files)}. Page and image pictures: {len(images)}.\n\n" + "\n\n".join(texts))
    res = llm.call(AGENT, SYSTEM, prompt, SCHEMA, cwd=str(d), images=[str(p) for p in images])
    st = res.data or {}

    def done(it):
        s = it.setdefault("source", {})
        s.update(state="done", statement=st, read_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=None,
                 pages=len(images))
    return _update(ws, platform, item_id, done)["source"]


def read_in_background(ws, platform, item_id, **kw):
    """Start the Reader for a plan (one at a time per plan). Returns False when it is already reading."""
    key = (platform, item_id)
    with _lock:
        if key in _running:
            return False
        _running.add(key)
    _update(ws, platform, item_id, lambda it: it.setdefault("source", {}).update(state="reading", error=None))

    def go():
        try:
            read(ws, platform, item_id, **kw)
        except (LLMError, ValueError, OSError) as e:
            _update(ws, platform, item_id, lambda it: it.setdefault("source", {}).update(state="failed", error=str(e)[:300]))
        except Exception as e:
            traceback.print_exc()
            _update(ws, platform, item_id, lambda it: it.setdefault("source", {}).update(state="failed", error=str(e)[:300]))
        finally:
            with _lock:
                _running.discard(key)
    threading.Thread(target=go, daemon=True, name="postcrew-reader").start()
    return True


def statement_text(st):
    """The problem statement as the agents read it."""
    if not st:
        return ""
    out = []
    if st.get("title"):
        out.append(f"Problem: {st['title']}")
    if st.get("statement"):
        out.append(st["statement"])
    if st.get("input_output"):
        out.append(f"Input / output: {st['input_output']}")
    for i, e in enumerate(st.get("examples") or [], 1):
        out.append(f"Example {i}: input {e.get('input', '')} -> output {e.get('output', '')}"
                   + (f" ({e['explanation']})" if e.get("explanation") else ""))
    if st.get("constraints"):
        out.append("Constraints: " + "; ".join(st["constraints"]))
    for i, f in enumerate(st.get("figures") or [], 1):
        out.append(f"Figure {i} (redraw it faithfully): {f}")
    if st.get("solution_notes"):
        out.append(f"The material's own solution notes: {st['solution_notes']}")
    if st.get("unclear"):
        out.append("Not readable in the material (do not guess these): " + "; ".join(st["unclear"]))
    return "\n".join(out)
