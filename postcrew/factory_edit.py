"""The Factory's video editor (owner, 2026-11-23).

    "I want to keep it as video editor with AI. So keep the workflow as create plan, create script, approve script, generate voice,
     approve voice as of now. then create video. But I want to have option to edit video by hand or with AI command and I should be
     able to edit each frame or each section where I feel improvement required. And at the end if I approve then only it will be
     ready for upload."

After Make video a plan is "editing" (factory_plans.py) and its video waits in the Queue as "editing", which is never uploaded.
The editor plays the episode's own animation page live (an Isometric / Signal video is a pure function of t: styles/iso-pastel/shell.js
seek(t)), so every frame can be looked at, and changed:
  by hand   episodes/<slug>/edits.json {texts: {old: new}, hide: [text], moves: {label text: [dx, dy]}}; edits.js applies them in the
            editor, the storyboard check and the render alike
  with AI   a command for the frames and sections the owner picked: Claude Code changes explainer.js for them (the words, voice and
            timing stay), the check runs, the editor shows the result; every change keeps the drawing before it, so Undo puts it back
Then Render the video again (the approved voice is kept) and Approve the video: only then is it "approved" in the Queue, ready for upload.
"""
import base64
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()
_jobs = {}   # slug -> {"what": "ai" | "render" | "prepare", "started", "done", "error", "note"}
MAX_FRAMES = 6
TEXT_MAX = 120


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _root(ws):
    from . import voice_desk
    return voice_desk._root(ws)


def _ep(ws, slug):
    slug = str(slug or "")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,120}", slug):
        raise ValueError("no such video")
    ep = _root(ws) / "episodes" / slug
    if not (ep / "explainer.js").exists():
        raise ValueError("this video has no animation to edit (only Isometric and Signal videos can be edited here)")
    return ep


def _read(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _write(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(p)


def _state(ep):
    return _read(ep / "edit" / "state.json", {})


def _set_state(ep, **kw):
    st = _state(ep)
    st.update(kw)
    _write(ep / "edit" / "state.json", st)
    return st


def _history(ep):
    return _read(ep / "edit" / "history.json", [])


def busy():
    return any(j.get("done") is None for j in _jobs.values())


def _job(slug, what, fn):
    with _lock:
        j = _jobs.get(slug)
        if j and j.get("done") is None:
            raise ValueError("the editor is still working on this video: wait for it to finish")
        _jobs[slug] = {"what": what, "started": time.time(), "done": None, "error": None}

    def go():
        try:
            note = fn()
            if note:
                _jobs[slug]["note"] = str(note)[:400]
        except Exception as e:   # never leave it stuck as busy
            _jobs[slug]["error"] = str(e)[:500]
        finally:
            _jobs[slug]["done"] = time.time()

    threading.Thread(target=go, daemon=True, name=f"video-editor-{what}").start()


# ---------- what the editor shows ----------
def timing(ep):
    """The real timing of the last check or render (build-iso/page.html): sections with their lines, the outro, the length."""
    try:
        html = (ep / "build-iso" / "page.html").read_text()
    except OSError:
        return None
    m = re.search(r"window\.TIMING = (\{.*?\}); const TIMING", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _post(ws, slug, item=None):
    pid = (item or {}).get("post_id")
    q = ws.queue()
    return next((p for p in q if pid and p.get("id") == pid), None) or next(
        (p for p in q if (p.get("youtube") or {}).get("episode") == slug and p.get("status") not in ("published", "publishing")), None)


def _plan(ws, slug):
    from . import factory_plans
    return factory_plans._by_slug(ws, slug)


def view(ws, slug):
    ep = _ep(ws, slug)
    T = timing(ep)
    item = _plan(ws, slug) or {}
    post = _post(ws, slug, item)
    st, hist = _state(ep), _history(ep)
    video = next((f for f in (_root(ws) / "out" / f"{slug}-hyperframes.mp4",) if f.exists()), None)
    sections = []
    for i, b in enumerate((T or {}).get("beats") or []):
        sections.append({"i": i, "t0": b["t0"], "t1": b["t1"], "say": b.get("say", "")})
    job = _jobs.get(slug)
    return {
        "slug": slug, "title": item.get("title") or (post or {}).get("topic") or slug, "plan_id": item.get("id"), "plan_state": item.get("state"),
        "ready": bool(T), "width": (T or {}).get("W"), "height": (T or {}).get("H"), "duration": (T or {}).get("duration"),
        "end": (T or {}).get("end"), "sections": sections,
        "page": f"/factory-edit/{slug}/page.html?v={int((ep / 'explainer.js').stat().st_mtime)}",
        "video": f"/factory-out/{slug}-hyperframes.mp4?v={int(video.stat().st_mtime)}" if video else None,
        "edits": _read(ep / "edits.json", {}),
        "history": [dict({k: h.get(k) for k in ("n", "at", "command", "frames", "sections", "result", "undone", "cost_usd")},
                         problems=[_plain(x) for x in h.get("problems") or []]) for h in hist][::-1][:30],
        "changed": bool(st.get("changed")), "rendered_at": st.get("rendered_at"), "approved_at": st.get("approved_at"),
        "post": {"id": post["id"], "status": post["status"]} if post else None,
        "job": job,
    }


def _plain(problem):
    """A check problem for the owner: what is wrong, without the drawing advice written for the AI."""
    return re.split(r"\. (?:Name things|Name |draw |frame it|no ctx|use |fewer )", str(problem))[0][:240]


def page(ws, slug):
    """The episode's animation page for the editor: the check's / render's page.html with its files served by the Studio."""
    ep = _ep(ws, slug)
    try:
        html = (ep / "build-iso" / "page.html").read_text()
    except OSError:
        raise ValueError("the editor page is being prepared: press Prepare")
    root = str(_root(ws).resolve())
    v = int((ep / "explainer.js").stat().st_mtime)
    html = html.replace(f"file://{root}/", "/factory-files/")
    html = re.sub(r'(/factory-files/[^"\s)]+\.js)"', lambda m: f'{m.group(1)}?v={v}"', html)
    html = html.replace("canvas{display:block}", "canvas{display:block;width:100%;height:auto}")
    return html


def file_path(ws, rel):
    """A kit or episode file the editor page loads (fonts, kit scripts, the episode's explainer.js): nothing else."""
    root = _root(ws).resolve()
    rel = str(rel or "").split("?")[0]
    f = (root / rel).resolve()
    ok = (root / "styles") in f.parents or (f.parent.parent == (root / "episodes") and f.name == "explainer.js")
    if not ok or not f.is_file():
        raise KeyError(rel)
    return f, root


# ---------- by hand ----------
def save_edits(ws, slug, edits):
    """The owner's hand edits: new wording, hidden texts and moved labels. Applied live in the editor and in the next render."""
    ep = _ep(ws, slug)
    e = edits if isinstance(edits, dict) else {}
    clean = lambda s: " ".join(str(s or "").split())[:TEXT_MAX]
    texts = {clean(k): clean(v) for k, v in (e.get("texts") or {}).items() if clean(k) and clean(k) != clean(v)}
    hide = sorted({clean(s) for s in (e.get("hide") or []) if clean(s)})
    moves = {}
    for k, v in (e.get("moves") or {}).items():
        try:
            dx, dy = (max(-1200.0, min(1200.0, float(x))) for x in v)
        except (TypeError, ValueError):
            continue
        if clean(k) and (abs(dx) >= 1 or abs(dy) >= 1):
            moves[clean(k)] = [round(dx), round(dy)]
    out = {k: v for k, v in (("texts", texts), ("hide", hide), ("moves", moves)) if v}
    if out != _read(ep / "edits.json", {}):
        _write(ep / "edits.json", out)
        _set_state(ep, changed=True)
    return view(ws, slug)


# ---------- with AI ----------
def _claude(ws, prompt, cwd):
    from .llm import agent_settings
    from .factory_plans import _cfg
    cfg = _cfg(ws)
    s = agent_settings(cfg, "writer")
    binary = cfg["llm"].get("claude_path") or "claude"
    tools = ["Read", "Edit", "Glob", "Grep", "Bash"]   # the shell only for the storyboard check (allowed below)
    allowed = ["Read", "Edit", "Glob", "Grep", "Bash(node pipeline/make-iso.mjs:*)"]
    cmd = [binary, "-p", "--output-format", "json", "--no-session-persistence", "--model", str(s.get("model", "sonnet")),
           "--max-budget-usd", str(max(float(s.get("max_budget_usd", 1.0)), 2.0)),
           "--permission-mode", "acceptEdits", "--allowedTools", ",".join(allowed), "--tools", ",".join(tools)]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(cwd), timeout=1500)
    except FileNotFoundError:
        raise ValueError(f"Claude Code CLI '{binary}' not found")
    except subprocess.TimeoutExpired:
        raise ValueError("the AI did not finish the change within 25 minutes")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise ValueError(f"claude exited {r.returncode}: {(r.stderr or r.stdout or '').strip()[-300:]}")
    if out.get("is_error") or out.get("subtype") != "success":
        raise ValueError(f"the AI stopped: {str(out.get('result') or out.get('subtype'))[:300]}")
    return str(out.get("result") or "").strip(), float(out.get("total_cost_usd") or 0)


def _check(ws, ep):
    """The storyboard check (it also writes the editor's page.html): its problems, [] when clean."""
    root = _root(ws)
    try:
        r = subprocess.run(["node", str(root / "pipeline" / "make-iso.mjs"), str(ep), "--check"], cwd=str(root), capture_output=True,
                           text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return ["the check did not finish within 15 minutes"]
    if r.returncode == 0:
        return []
    found = [ln[2:].strip() for ln in (r.stderr or "").splitlines() if ln.startswith("- ")]
    return found or [re.sub(r"\x1b\[[0-9;]*m", "", (r.stderr or r.stdout or "the check failed"))[-300:]]


def prepare(ws, slug):
    """An episode made before the editor has no page.html yet: the check writes it (a minute or two)."""
    ep = _ep(ws, slug)
    _job(slug, "prepare", lambda: _check(ws, ep) and None)
    return view(ws, slug)


def _where(T, t):
    for i, b in enumerate((T or {}).get("beats") or []):
        if b["t0"] <= t < b["t1"]:
            return i
    return None


def ask(ws, slug, command, frames=None, sections=None):
    """An AI change for the frames / sections the owner picked. frames: [{"t": seconds, "image": "data:image/jpeg;base64,..."}]."""
    ep = _ep(ws, slug)
    command = " ".join(str(command or "").split())[:1500]
    if len(command) < 3:
        raise ValueError("say what to change")
    T = timing(ep)
    if not T:
        raise ValueError("the editor page is being prepared: press Prepare first")
    beats = T.get("beats") or []
    secs = sorted({int(i) for i in (sections or []) if str(i).lstrip("-").isdigit() and 0 <= int(i) < len(beats)})
    shots = []
    fdir = ep / "edit" / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    for f in (frames or [])[:MAX_FRAMES]:
        try:
            t = round(max(0.0, min(float(f.get("t")), float(T.get("duration") or 0))), 2)
        except (TypeError, ValueError, AttributeError):
            continue
        img = str(f.get("image") or "")
        m = re.match(r"data:image/(png|jpeg);base64,(.+)$", img, re.S)
        name = None
        if m:
            name = f"f-{t:07.2f}.{'png' if m.group(1) == 'png' else 'jpg'}"
            (fdir / name).write_bytes(base64.b64decode(m.group(2)))
        shots.append({"t": t, "file": name, "section": _where(T, t)})
    hist = _history(ep)
    n = (max((h.get("n", 0) for h in hist), default=0) + 1)
    entry = {"n": n, "at": _now(), "command": command, "frames": [s["t"] for s in shots], "sections": [i + 1 for i in secs],
             "before": f"edit/history/{n:03d}.js"}
    (ep / "edit" / "history").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ep / "explainer.js", ep / entry["before"])
    prompt = _prompt(ep, T, command, shots, secs)

    def go():
        keep = {f: (ep / f).read_bytes() for f in ("script.json", "edits.json") if (ep / f).exists()}
        result, cost = _claude(ws, prompt, _root(ws))
        for f, b in keep.items():   # the words, the voice timing and the owner's hand edits are not the AI's to change
            if (ep / f).read_bytes() != b:
                (ep / f).write_bytes(b)
        problems = _check(ws, ep)
        entry.update(result=result[:600], cost_usd=round(cost, 4), problems=problems[:6])
        _write(ep / "edit" / "history.json", _history(ep) + [entry])
        _set_state(ep, changed=True)
        return result
    _job(slug, "ai", go)
    return view(ws, slug)


def _prompt(ep, T, command, shots, secs):
    slug = ep.name
    beats = T.get("beats") or []
    line = lambda i: f'section {i + 1} ({beats[i]["t0"]:.1f} to {beats[i]["t1"]:.1f} s, B({i}) in the code), its voice line "{beats[i].get("say", "")}"'
    frames = "\n".join(f"- t = {s['t']:.2f} s" + (f", in {line(s['section'])}" if s["section"] is not None else ", in the outro")
                       + (f". Its picture is episodes/{slug}/edit/frames/{s['file']} (Read it)" if s["file"] else "") for s in shots)
    where = ("\n".join(f"- {line(i)}" for i in secs)) if secs else ""
    scope = ("Change only the frames and sections listed above. Everything else must look exactly as it does now."
             if shots or secs else "The owner chose no frame or section: the command is for the whole video.")
    return f"""You are the video editor of the owner's YouTube Short episodes/{slug}. The owner watched the video in the Factory's
editor and asks for this change

    {command}

Frames the owner picked
{frames or "- none"}
Sections the owner picked
{where or "- none"}

{scope}

How the video is made
- The animation is episodes/{slug}/explainer.js, function explainer(ctx, W, H_, t), a pure function of t. TIMING.beats[i] (B(i)) gives
  each section's t0 and t1 from the approved voice. The captions and the outro are drawn by the shell, not by explainer.js.
- The look and its rules are in styles/iso-pastel/STYLE.md (read rule 6). Names are printed on the objects with nameOn, states and
  values float with label(), texts never cover each other, nothing goes in the caption band.
- episodes/{slug}/edits.json holds the owner's hand edits (texts renamed, hidden or moved); they are applied on top. Leave that file.

Rules
- Edit only episodes/{slug}/explainer.js. Never change script.json, the voice files or the timing: the words and voice are approved.
- Do exactly what the owner asked, as well as you can; do not redesign other parts.
- Smaller still means readable: no text the story needs under 40 px (headlines 66, key numbers 96), names printed on objects 26 px.
- When done run  node pipeline/make-iso.mjs episodes/{slug} --check  and look at episodes/{slug}/build-iso/storyboard.png. Fix every
  problem your change caused. A problem in a section you did not touch you may leave; say so.
- Answer with one or two plain sentences for the owner saying what you changed (no code)."""


def undo(ws, slug):
    """Put back the drawing from before the last AI change that is still in place."""
    ep = _ep(ws, slug)
    if (_jobs.get(slug) or {}).get("done", 1) is None:
        raise ValueError("the editor is still working on this video: wait for it to finish")
    hist = _history(ep)
    last = next((h for h in reversed(hist) if not h.get("undone")), None)
    if not last or not (ep / last["before"]).exists():
        raise ValueError("there is no AI change to undo")
    shutil.copy2(ep / last["before"], ep / "explainer.js")
    last["undone"] = _now()
    _write(ep / "edit" / "history.json", hist)
    _set_state(ep, changed=True)
    _job(slug, "prepare", lambda: _check(ws, ep) and None)   # the editor's page follows the drawing put back
    return view(ws, slug)


# ---------- render again, approve ----------
def render(ws, slug):
    """Record the video again with every change; the approved voice is kept. The Queue's copy is replaced."""
    ep = _ep(ws, slug)
    root = _root(ws)

    def go():
        try:
            r = subprocess.run(["npm", "run", "make", "--", f"episodes/{slug}"], cwd=str(root), capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired:
            raise ValueError("the render did not finish within an hour")
        (ep / "edit").mkdir(exist_ok=True)
        (ep / "edit" / "render.log").write_text((r.stdout or "") + "\n" + (r.stderr or ""))
        if r.returncode:
            raise ValueError(f"the render failed: {re.sub(chr(27) + r'[[0-9;]*m', '', (r.stderr or r.stdout or ''))[-400:]}")
        video = root / "out" / f"{slug}-hyperframes.mp4"
        if not video.exists():
            raise ValueError("the render finished but there is no video")
        post = _post(ws, slug, _plan(ws, slug))
        if post:
            q = ws.queue()
            p = next(x for x in q if x["id"] == post["id"])
            shutil.copy2(video, ws.root / p["media"])
            thumb = video.with_suffix(".jpg")
            if thumb.exists() and p.get("poster_image"):
                shutil.copy2(thumb, ws.root / p["poster_image"])
            try:
                secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                            capture_output=True, text=True, timeout=60).stdout.strip())
                p.setdefault("youtube", {})["seconds"] = round(secs, 1)
            except (ValueError, OSError):
                pass
            p["edited_at"] = _now()
            ws.save_queue(q)
        _set_state(ep, changed=False, rendered_at=_now())
        return "rendered"
    _job(slug, "render", go)
    return view(ws, slug)


def approve(ws, slug):
    """The owner approves the edited video: only now is it ready for upload (Queue status "approved"), and the plan is made."""
    from . import factory_plans, rewards
    ep = _ep(ws, slug)
    if (_jobs.get(slug) or {}).get("done", 1) is None:
        raise ValueError("the editor is still working on this video: wait for it to finish")
    if _state(ep).get("changed"):
        raise ValueError("you changed the video since it was last rendered: press Render the video first, watch it, then approve")
    item = _plan(ws, slug)
    post = _post(ws, slug, item)
    if not post:
        raise ValueError("this video is not in the Queue any more")
    q = ws.queue()
    p = next(x for x in q if x["id"] == post["id"])
    if p["status"] in ("editing", "awaiting_approval", "queued", "failed", "dry_run"):
        p["status"] = "approved"
        p["approved_in"] = "video editor"
        ws.save_queue(q)
        rewards.record(ws, p, "approved")
    if item and item.get("state") == "editing":
        factory_plans._update(ws, item["id"], state="made", approved_at=_now())
    _set_state(ep, approved_at=_now())
    return view(ws, slug)


def reopen(ws, slug):
    """Take an approved video back into the editor (before it is uploaded)."""
    from . import factory_plans
    ep = _ep(ws, slug)
    item = _plan(ws, slug)
    post = _post(ws, slug, item)
    if post and post["status"] == "approved":
        q = ws.queue()
        next(x for x in q if x["id"] == post["id"])["status"] = "editing"
        ws.save_queue(q)
    if item and item.get("state") == "made":
        factory_plans._update(ws, item["id"], state="editing")
    _set_state(ep, approved_at=None)
    return view(ws, slug)
