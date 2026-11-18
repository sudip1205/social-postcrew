"""Voice desk: every YouTube script waits for the owner's two approvals, the script and the voice, before its video is made (owner, 2026-11-16).
Since 2026-11-17 the scripts come from your Factory plans (factory_plans.py); nothing is made automatically.

    "I'll create the voice and upload for each of them ... match with dip_puck and create the voice for the video. Remove wrong lines,
     huge gap etc. But for the sentences keep the pause as it is and the pronunciation of the words and abbreviations. ... I should have
     option to skip my voice and use am_puck directly. basically I'll approve script and voice before making the video."

- A script is written by a crew run that stops at the Render step, WAITING (AgentWait), until the script and the voice are approved here.
- Your recording of the whole script is cleaned and matched to the channel voice:
    1. faster-whisper finds every word and when it was said;
    2. each sentence of the script is matched to what was heard; a line said again (a retake) keeps its LAST take, and words that are
       not in the script (false starts, "sorry, again") are cut;
    3. a pause INSIDE a sentence is kept as it is unless it is huge (over HUGE_GAP s); a pause between sentences is kept up to MAX_GAP s;
    4. the cleaned take is converted with Seed-VC to the am_puck timbre dip_puck was trained on (the same conversion as the training
       data), so it sounds like the channel voice but keeps your timing, pauses and pronunciation (nothing is re-synthesised);
    5. it is cut into one clip per line (episodes/<slug>/voice/scene<i>.wav + words), which the factory uses in place of the AI voice.
- Or skip your voice: dip_puck (the trained voice) or Kokoro am_puck reads the script.
- The video is made only when you press Make the video (factory_plans.make, or make() here for a script from the chat or a manual run).

State: episodes/<slug>/desk.json in the Shorts factory; the index (day -> slug) of manual runs in workspace state "voice-desk".
"""
import difflib
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from . import factory_voice
from .factory_voice import AUDIO_EXT, CTA_LINE, LIMIT, CHUNK, _ffmpeg, _secs, _tok, _words, _has_whisper

STATE = "voice-desk"
MODES = ("own", "dip_puck", "am_puck")   # own: your recording (converted); the others: that voice reads the script
HUGE_GAP = 1.2   # s: a pause inside a sentence longer than this is a hesitation, cut to KEEP_GAP
KEEP_GAP = 0.45
MAX_GAP = 0.9    # s: the longest pause kept between two sentences
PAD_IN, PAD_OUT = 0.06, 0.16   # s of audio kept before a sentence's first word and after its last
_jobs = {}       # slug -> {"what", "started", "error", "done"}: background work (voice processing, a run)
_lock = threading.Lock()


# ---------- settings and places ----------
def settings(cfg):
    d = ((cfg.get("video") or {}).get("voice_desk") or {})
    return {"enabled": d.get("enabled", True),
            "seedvc_dir": d.get("seedvc_dir", "~/voicelab/seed-vc"), "target": d.get("target", "~/voicelab/refs/am_puck.wav"),
            "steps": int(d.get("diffusion_steps", 40)), "cfg_rate": float(d.get("cfg_rate", 0.7))}


def _cfg(ws):
    return factory_voice._cfg(ws)


def enabled(cfg):
    return bool(settings(cfg)["enabled"])


def _root(ws):
    from .agents.shorts import factory_dir
    return factory_dir(_cfg(ws))


def _ep(ws, slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", str(slug or "")):
        raise ValueError("unknown episode")
    ep = _root(ws) / "episodes" / slug
    if not (ep / "script.json").exists():
        raise ValueError("this episode has no script yet")
    return ep


def _read(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _write(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def desk(ep):
    return _read(Path(ep) / "desk.json", {})


def _save_desk(ep, d):
    _write(Path(ep) / "desk.json", d)


def index(ws):
    return ws.state(STATE, {"days": {}})


def _index_set(ws, day, slug):
    with _lock:
        st = index(ws)
        st.setdefault("days", {})[day] = slug
        ws.save_state(STATE, st)


# ---------- the script's lines ----------
def lines(script):
    """What is said, one entry per clip the factory voices: the beats (canvas looks) or scenes, then the outro line."""
    if script.get("beats"):
        return [str(b.get("say") or "").strip() for b in script["beats"]] + [CTA_LINE]
    return [factory_voice.scene_text(sc) for sc in script.get("scenes") or []]


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num(n):
    """An integer in words, as tokens (Whisper writes "45" where the script says "forty-five")."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    for size, word in ((10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            return _num(n // size) + [word] + (_num(n % size) if n % size else [])
    return []


def tokens(text):
    """Words to compare: lower case, numbers in words, hyphens split ("forty-five" = "45" = forty five)."""
    out = []
    for w in re.split(r"[\s\-–—/]+", str(text)):
        raw = w.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", w.strip(".!?;:")) else w
        m = re.fullmatch(r"\W*(\d+)(?:\.(\d+))?(%|x|k)?\W*", raw, re.I)
        if m and len(m.group(1)) <= 12:
            out += _num(int(m.group(1)))
            if m.group(2):
                out += ["point"] + [_ONES[int(c)] for c in m.group(2)]
            out += {"%": ["percent"], "x": ["x"], "k": ["thousand"]}.get((m.group(3) or "").lower(), [])
            continue
        t = _tok(w)
        if t:
            out.append(t)
    return out


# ---------- the run's side: reuse a written script, and wait for the voice ----------
def reuse(ctx):
    """The Script Writer's output for this day when the desk already has its episode (written ahead, or by an earlier run that waited)."""
    if not enabled(ctx.cfg) or (ctx.options or {}).get("rewrite"):
        return None
    slug = (index(ctx.ws).get("days") or {}).get(ctx.day.isoformat())
    if not slug:
        return None
    ep = _root(ctx.ws) / "episodes" / slug
    d = desk(ep)
    if not d.get("writer") or not (ep / "script.json").exists() or d.get("category") not in (None, ctx.category):
        return None
    return dict(d["writer"], reused=True)


def record(ctx, out):
    """A script was just written: put it on the desk (a new script needs a new approval and a new voice)."""
    if not enabled(ctx.cfg) or not out or not out.get("slug"):
        return
    ep = Path(out.get("episode") or (_root(ctx.ws) / "episodes" / out["slug"]))
    old = desk(ep)
    d = {"day": ctx.day.isoformat(), "category": ctx.category, "label": ctx.cat.get("label", ""), "slug": out["slug"],
         "topic": (ctx.outputs.get("topic") or {}).get("topic") or out.get("title", ""), "title": out.get("title", ""),
         "writer": {k: v for k, v in out.items() if not str(k).startswith("_")}, "written": time.time(), "script": "draft",
         "voice": {"state": "none"}, "history": (old.get("history") or [])[-10:], "plan_id": (ctx.options or {}).get("plan_id")}
    if old.get("written"):
        d["history"].append({"written": old["written"], "script": old.get("script"), "voice": (old.get("voice") or {}).get("state")})
    shutil.rmtree(ep / "voice-take", ignore_errors=True)   # a take of the old script does not fit the new one
    _clear_scene_files(ep)
    _save_desk(ep, d)
    _index_set(ctx.ws, d["day"], out["slug"])


def gate(ctx, slug):
    """None when the video may be made; otherwise why it waits."""
    if not enabled(ctx.cfg):
        return None
    ep = _root(ctx.ws) / "episodes" / slug
    d = desk(ep)
    if not d:   # an episode the desk never saw (written before the desk existed): put it there and wait like the others
        return "the script is waiting for you in Factory > Plans: approve it and upload your voice (or skip to the AI voice)"
    if d.get("script") != "approved":
        return "waiting for you to approve the script in Factory > Plans"
    v = d.get("voice") or {}
    if v.get("state") != "approved":
        return "waiting for your voice in Factory > Plans: upload it and approve it (or skip to dip_puck or am_puck)"
    return None


def mark_run(ws, slug, run_id, state):
    ep = _root(ws) / "episodes" / slug
    d = desk(ep)
    if d:
        d["run"] = {"id": run_id, "state": state, "at": time.time()}
        _save_desk(ep, d)


# ---------- the Studio's side ----------
def view(ws):
    """Factory > Plans: your plans (factory_plans.py), and other scripts waiting for your voice (Factory chat, manual runs)."""
    from . import factory_plans
    cfg = _cfg(ws)
    return dict(factory_plans.view(ws), others=chat_episodes(ws, 14), whisper=_has_whisper(), converter=_converter_ok(cfg), modes=list(MODES),
                enabled=enabled(cfg))


def delete(ws, slug):
    """Delete a waiting script that is not one of your plans (Factory chat, a manual run): its episode moves to episodes/.deleted/ (so it
    can still be got back by hand) and it is never used again."""
    ep = _ep(ws, slug)
    d = desk(ep)
    if (_jobs.get(slug) or {}).get("done") is None and _jobs.get(slug):
        raise ValueError("this script is being worked on: delete it when that is finished")
    if (d.get("run") or {}).get("state") == "making":
        raise ValueError("its video is being made")
    with _lock:
        st = index(ws)
        st["days"] = {k: v for k, v in (st.get("days") or {}).items() if v != slug}
        ws.save_state(STATE, st)
    bin_ = ep.parent / ".deleted"
    bin_.mkdir(exist_ok=True)
    dest = bin_ / f"{slug}-{int(time.time())}"
    shutil.move(str(ep), str(dest))
    return {"ok": True}


def chat_episodes(ws, days=7):
    """Scripts written in the Factory chat in the last days and not made yet: they wait for your voice too."""
    root = _root(ws)
    out, cut = [], time.time() - days * 86400
    eps = root / "episodes"
    if not eps.exists():
        return out
    for ep in sorted(eps.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        f = ep / "script.json"
        if not f.exists() or f.stat().st_mtime < cut or desk(ep).get("plan_id"):
            continue
        if (root / "out" / f"{ep.name}-hyperframes.mp4").exists() and not desk(ep):
            continue   # made before the desk existed
        if (desk(ep).get("run") or {}).get("state") == "made":
            continue
        try:
            out.append(episode(ws, ep.name))
        except ValueError:
            continue
    return out[:12]



def episode(ws, slug):
    ep = _ep(ws, slug)
    script = _read(ep / "script.json", {})
    d = desk(ep)
    v = dict(d.get("voice") or {"state": "none"})
    rep = _read(ep / "voice-take" / "report.json", None)
    take = ep / "voice-take"
    return {"slug": slug, "title": d.get("title") or script.get("title") or script.get("topic") or slug, "topic": d.get("topic", ""),
            "style": script.get("style") or "", "lines": lines(script), "hook_options": [str(h) for h in script.get("hook_options") or [] if str(h).strip()][:5], "outro": bool(script.get("beats")), "script": d.get("script", "draft"),
            "voice": v, "report": rep, "job": _jobs.get(slug), "run": d.get("run"),
            "audio": {k: f"{slug}/voice-take/{f}" for k, f in (("converted", "take-converted.wav"), ("cleaned", "take.wav"))
                      if (take / f).exists()},
            "words": sum(len(x.split()) for x in lines(script)[:-1 if script.get("beats") else None])}


def save_lines(ws, slug, new_lines):
    """Your edits to the script's lines (the narration only; the pictures stay)."""
    ep = _ep(ws, slug)
    script = _read(ep / "script.json", {})
    old = lines(script)
    n = len(old) - (1 if script.get("beats") else 0)
    new = [re.sub(r"\s+", " ", str(x or "")).strip() for x in (new_lines or [])][:n]
    if len(new) != n or not all(new):
        raise ValueError(f"send all {n} lines, none empty")
    if script.get("beats"):
        for b, t in zip(script["beats"], new):
            b["say"] = t
    else:
        for sc, t in zip(script.get("scenes") or [], new):
            sc["text"] = t
    _write(ep / "script.json", script)
    d = _adopt(ep)
    if new != old[:n]:
        d["script"] = "draft"
        if (d.get("voice") or {}).get("mode") == "own":   # a recording of the old words no longer matches
            d["voice"] = {"state": "none", "note": "the script changed: record it again"}
            _clear_scene_files(ep)
    _save_desk(ep, d)
    return episode(ws, slug)


def _adopt(ep):
    """An episode written in the Factory chat (no day): it joins the desk when you first work on it; the video is made as soon as both
    are approved."""
    d = desk(ep)
    if not d:
        script = _read(ep / "script.json", {})
        d = {"slug": ep.name, "source": "chat", "title": script.get("title") or script.get("topic") or ep.name, "topic": script.get("topic", ""),
             "script": "draft", "voice": {"state": "none"}, "run": {"state": "waiting"}, "written": (ep / "script.json").stat().st_mtime}
        _save_desk(ep, d)
    return d


def approve_script(ws, slug, approved=True):
    ep = _ep(ws, slug)
    d = _adopt(ep)
    d["script"] = "approved" if approved else "draft"
    _save_desk(ep, d)
    return episode(ws, slug)


def _clear_scene_files(ep):
    voice = Path(ep) / "voice"
    for f in list(voice.glob("scene*.wav")) + list(voice.glob("scene*.words.json")) if voice.exists() else []:
        f.unlink(missing_ok=True)


def upload(ws, slug, name, rfile, length):
    """Your recording of the whole script: stored, then cleaned and converted in the background."""
    ep = _ep(ws, slug)
    ext = Path(str(name or "")).suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError("pick an audio recording (" + ", ".join(AUDIO_EXT) + ")")
    if length <= 0:
        raise ValueError("the recording is empty")
    if length > LIMIT:
        raise ValueError(f"the recording is {length / 2**20:.0f} MB; the limit is {LIMIT // 2**20} MB")
    if not _has_whisper():
        raise ValueError("faster-whisper is not installed on this computer (pip install faster-whisper): it finds the words in your recording")
    with _lock:
        if (_jobs.get(slug) or {}).get("done") is None and _jobs.get(slug):
            raise ValueError("this recording is still being processed")
    take = ep / "voice-take"
    take.mkdir(exist_ok=True)
    for f in take.glob("upload.*"):
        f.unlink()
    raw, left = take / f"upload{ext}", length
    with open(raw, "wb") as f:
        while left:
            chunk = rfile.read(min(CHUNK, left))
            if not chunk:
                raw.unlink(missing_ok=True)
                raise ValueError("the upload ended early")
            f.write(chunk)
            left -= len(chunk)
    d = _adopt(ep)
    d["voice"] = {"state": "processing", "mode": "own", "file": name, "uploaded": time.time()}
    _save_desk(ep, d)
    _start(slug, "voice", lambda: process(ws, slug))
    return episode(ws, slug)


def _start(slug, what, fn):
    with _lock:
        _jobs[slug] = {"what": what, "started": time.time(), "error": None, "done": None}

    def go():
        try:
            fn()
        except Exception as e:   # never leave it stuck as busy
            _jobs[slug]["error"] = f"{e}"[:500]
        finally:
            _jobs[slug]["done"] = time.time()

    threading.Thread(target=go, daemon=True, name=f"voice-desk-{what}").start()


# ---------- cleaning: the script's sentences found in what was heard ----------
def _match(sent_tokens, heard_tokens, start, stop):
    """The best span of heard_tokens[start:stop] for one sentence: (ratio, i, j)."""
    n = len(sent_tokens)
    best = (0.0, start, start)
    if not n:
        return best
    for i in range(start, max(start, stop - max(1, n // 2)) + 1):
        if heard_tokens[i:i + 1] and heard_tokens[i] not in sent_tokens[:3] and i != start:
            continue   # a span starts on one of the sentence's first words (fast, and a retake starts the same way)
        for L in range(max(1, n - 2), n + 4):
            j = min(len(heard_tokens), i + L)
            r = difflib.SequenceMatcher(None, sent_tokens, heard_tokens[i:j], autojunk=False).ratio()
            if r > best[0] + 1e-9:
                best = (r, i, j)
    return best


def align(words, texts):
    """Every sentence of every line found in the heard words, keeping the last take of a line said more than once.
    Returns (sentences, report): sentences = [{"line", "text", "i", "j", "score"} | {"line", "text", "missing": True}]."""
    # one token stream for what was heard, each token knowing its word (a "45" is two tokens, both of that word)
    heard, owner = [], []
    for k, w in enumerate(words):
        for t in tokens(w["w"]):
            heard.append(t)
            owner.append(k)
    owner.append(len(words))
    out, p = [], 0
    H = len(heard)
    for li, text in enumerate(texts):
        for s in _sentences(text):
            toks = tokens(s)
            n = len(toks)
            if not n:
                continue
            r, i, j = _match(toks, heard, p, min(H, p + 4 * n + 40))
            if r < 0.5:
                out.append({"line": li, "text": s, "missing": True})
                continue
            while True:   # a retake: the same sentence said again soon after, keep the last good one
                r2, i2, j2 = _match(toks, heard, j, min(H, j + 3 * n + 15))
                if r2 >= max(0.72, r - 0.1) and i2 >= j:
                    r, i, j = r2, i2, j2
                else:
                    break
            wi, wj = owner[i], owner[j - 1] + 1   # back to whole words
            out.append({"line": li, "text": s, "i": wi, "j": wj, "score": round(r, 2)})
            p = j
    return out


def plan_cuts(words, sents):
    """The pieces of the recording to keep, per line: [(line, [(start, end, gap_after)...])], and what was cut."""
    pieces, removed, used = {}, [], set()
    prev_j = 0
    kept = [s for s in sents if not s.get("missing")]
    for k, s in enumerate(kept):
        if s["i"] > prev_j:
            removed.append(" ".join(w["w"] for w in words[prev_j:s["i"]]))
        used.update(range(s["i"], s["j"]))
        prev_j = s["j"]
        ws_ = words[s["i"]:s["j"]]
        # inside the sentence: keep every pause, except a huge one (a hesitation), which becomes KEEP_GAP
        segs, a = [], ws_[0]["s"]
        for x in range(1, len(ws_)):
            gap = ws_[x]["s"] - ws_[x - 1]["e"]
            if gap > HUGE_GAP:
                segs.append([a, ws_[x - 1]["e"], KEEP_GAP])
                a = ws_[x]["s"]
        segs.append([a, ws_[-1]["e"], None])
        pieces.setdefault(s["line"], []).append({"segs": segs, "first": ws_[0]["s"], "last": ws_[-1]["e"], "i": s["i"], "j": s["j"]})
    if prev_j < len(words):
        removed.append(" ".join(w["w"] for w in words[prev_j:]))
    plan, shortened = [], 0
    for line, sl in sorted(pieces.items()):
        segs = []
        for k, piece in enumerate(sl):
            if k:   # between two sentences of one line: the pause as it was, up to MAX_GAP (contiguous takes only)
                before = sl[k - 1]
                gap = piece["first"] - before["last"]
                contiguous = piece["i"] == before["j"]
                g = gap if contiguous and gap <= MAX_GAP else min(MAX_GAP, max(0.35, gap if contiguous else 0.5))
                shortened += g < gap - 0.05
                segs[-1][2] = g
            segs += [list(x) for x in piece["segs"]]
        shortened += sum(1 for sg in segs if sg[2] == KEEP_GAP)
        plan.append((line, segs))
    return plan, [r for r in removed if r.strip()], shortened


def _render_line(src, segs, words, out_wav):
    """One line's clip: its kept pieces, with the planned pauses between them (silence), and its words re-timed to the clip."""
    parts, filt, t, new_words = [], [], 0.0, []
    for k, (a, b, gap) in enumerate(segs):
        s0, s1 = max(0.0, a - PAD_IN), b + PAD_OUT
        filt.append(f"[0:a]atrim={s0:.3f}:{s1:.3f},asetpts=PTS-STARTPTS[p{k}]")
        parts.append(f"[p{k}]")
        for w in words:
            if a - 1e-3 <= w["s"] and w["e"] <= b + 1e-3:
                new_words.append({"w": w["w"], "s": round(t + (w["s"] - s0), 3), "e": round(t + (w["e"] - s0), 3)})
        t += s1 - s0
        if gap:
            filt.append(f"anullsrc=r=48000:cl=mono,atrim=0:{max(0.01, gap - PAD_IN - PAD_OUT):.3f}[g{k}]")
            parts.append(f"[g{k}]")
            t += max(0.01, gap - PAD_IN - PAD_OUT)
    filt.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1[out]")
    _ffmpeg("-i", str(src), "-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav))
    return new_words, t


# ---------- matching the channel voice: Seed-VC to the am_puck timbre ----------
def _converter_ok(cfg):
    s = settings(cfg)
    d = Path(s["seedvc_dir"]).expanduser()
    return (d / "inference.py").exists() and (d / "venv" / "bin" / "python").exists() and Path(s["target"]).expanduser().exists()


def convert(cfg, src, out_wav, runner=subprocess.run):
    s = settings(cfg)
    d = Path(s["seedvc_dir"]).expanduser()
    if not _converter_ok(cfg):
        raise ValueError(f"Seed-VC is not set up at {d} (with venv/ and {s['target']}): it matches your recording to the channel voice")
    tmp = Path(out_wav).parent / ".vc"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    r = runner([str(d / "venv" / "bin" / "python"), "inference.py", "--source", str(src), "--target", str(Path(s["target"]).expanduser()),
                "--output", str(tmp), "--diffusion-steps", str(s["steps"]), "--length-adjust", "1.0", "--inference-cfg-rate", str(s["cfg_rate"])],
               cwd=str(d), capture_output=True, text=True, timeout=3600)
    got = sorted(tmp.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    if r.returncode or not got:
        raise ValueError("Seed-VC could not convert the recording: " + ((r.stderr or r.stdout or "").strip().splitlines() or ["no output"])[-1][:300])
    _ffmpeg("-i", str(got[-1]), "-ac", "1", "-ar", "48000", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "pcm_s16le", str(out_wav))
    shutil.rmtree(tmp, ignore_errors=True)


def process(ws, slug, converter=convert, words_of=None):
    """Clean the uploaded take and match it to the channel voice; the result waits for your approval."""
    ep = _ep(ws, slug)
    take = ep / "voice-take"
    raw = next(iter(sorted(take.glob("upload.*"))), None)
    if not raw:
        raise ValueError("no recording uploaded")
    d = desk(ep)
    try:
        script = _read(ep / "script.json", {})
        texts = lines(script)
        full = take / "take-original.wav"
        _ffmpeg("-i", str(raw), "-ac", "1", "-ar", "48000", "-af", "highpass=f=70", "-c:a", "pcm_s16le", str(full))
        heard = (words_of or _words)(full) or []
        if len(heard) < 10:
            raise ValueError(f"only {len(heard)} words were heard in the recording: is it the whole script?")
        sents = align(heard, texts)
        plan, removed, shortened = plan_cuts(heard, sents)
        missing = [s for s in sents if s.get("missing")]
        outro_missing = bool(script.get("beats")) and all(s.get("missing") for s in sents if s["line"] == len(texts) - 1)
        # the cleaned take: every line's clip, joined with a short gap, converted in ONE pass (the model loads once), then cut again
        clips, lens, line_words, join = [], [], {}, 0.6
        tmpd = take / "lines"
        shutil.rmtree(tmpd, ignore_errors=True)
        tmpd.mkdir()
        for line, segs in plan:
            f = tmpd / f"line{line}.wav"
            line_words[line], n = _render_line(full, segs, heard, f)
            clips.append((line, f))
            lens.append(_secs(f) or n)
        if not clips:
            raise ValueError("none of the script's lines was found in the recording")
        listing = tmpd / "list.txt"
        gapf = tmpd / "gap.wav"
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(join), "-c:a", "pcm_s16le", str(gapf))
        listing.write_text("".join(f"file '{f.name}'\nfile 'gap.wav'\n" for _, f in clips))
        cleaned = take / "take.wav"
        _ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "pcm_s16le", str(cleaned))
        converted = take / "take-converted.wav"
        converter(_cfg(ws), cleaned, converted)
        total_in, total_out = _secs(cleaned), _secs(converted)
        k = (total_out / total_in) if total_in and total_out else 1.0   # Seed-VC keeps the length; scale if it drifted a little
        staged = take / "scenes"
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir()
        t = 0.0
        for (line, _), n in zip(clips, lens):
            _ffmpeg("-ss", f"{t * k:.3f}", "-t", f"{n * k:.3f}", "-i", str(converted), "-c:a", "pcm_s16le", str(staged / f"scene{line}.wav"))
            _write(staged / f"scene{line}.words.json", [{"w": w["w"], "s": round(w["s"] * k, 3), "e": round(w["e"] * k, 3)} for w in line_words[line]])
            t += n + join
        shutil.rmtree(tmpd, ignore_errors=True)
        rep = {"heard_words": len(heard), "kept_lines": len(clips), "lines": len(texts), "removed": removed[:40],
               "missing": [{"line": s["line"] + 1, "text": s["text"]} for s in missing if not (outro_missing and s["line"] == len(texts) - 1)],
               "outro_recorded": not outro_missing, "huge_gaps_shortened": shortened, "seconds": round(sum(lens) * k, 1),
               "voiced_by_ai": sorted({s["line"] + 1 for s in missing}), "done": time.time()}
        _write(take / "report.json", rep)
        d = desk(ep)
        d["voice"] = dict(d.get("voice") or {}, state="ready", mode="own")
        _save_desk(ep, d)
    except Exception as e:
        d = desk(ep)
        d["voice"] = dict(d.get("voice") or {}, state="failed", error=str(e)[:500])
        _save_desk(ep, d)
        raise


def choose(ws, slug, mode):
    """Approve the voice: own (your processed recording) or skip to dip_puck / am_puck."""
    if mode not in MODES:
        raise ValueError("voice must be one of: " + ", ".join(MODES))
    ep = _ep(ws, slug)
    d = _adopt(ep)
    script = _read(ep / "script.json", {})
    _clear_scene_files(ep)
    if mode == "own":
        staged = ep / "voice-take" / "scenes"
        if (d.get("voice") or {}).get("state") not in ("ready", "approved") or not staged.exists():
            raise ValueError("upload your recording first, and wait for it to be processed")
        (ep / "voice").mkdir(exist_ok=True)
        for f in staged.iterdir():
            shutil.copy2(f, ep / "voice" / f.name)
        if script.get("voice") != "own":
            script["voice_kokoro"] = script.get("voice") if script.get("voice") in ("dip_puck", "am_puck") else "dip_puck"
        script["voice"] = "own"   # lines not found in the recording are read by voice_kokoro
    else:
        script["voice"] = mode
        script.pop("voice_kokoro", None)
    _write(ep / "script.json", script)
    d["voice"] = dict(d.get("voice") or {}, state="approved", mode=mode, approved=time.time())
    _save_desk(ep, d)
    return episode(ws, slug)



def _make_now(ws, slug, d, runner=None):
    if d.get("day"):
        _start(slug, "video", lambda: (runner or _run)(ws, d["day"], {"kept": {"writer": d["writer"]}, "kept_from": "your approved script"},
                                                       d.get("category")))
    else:   # from the Factory chat: render it; it appears in the Factory's video list, to queue from there
        _start(slug, "video", lambda: _render_chat(ws, slug))


def _render_chat(ws, slug):
    factory_voice.render(ws, slug)
    while not factory_voice._render.get("done"):
        time.sleep(2)
    if factory_voice._render.get("error"):
        raise ValueError(factory_voice._render["error"])
    ep = _root(ws) / "episodes" / slug
    d = desk(ep)
    d["run"] = {"state": "made", "at": time.time()}
    _save_desk(ep, d)


def reopen_voice(ws, slug):
    """Take the voice approval back (to upload again or pick another voice)."""
    ep = _ep(ws, slug)
    d = desk(ep)
    has_take = (ep / "voice-take" / "scenes").exists()
    d["voice"] = dict(d.get("voice") or {}, state="ready" if has_take and (d.get("voice") or {}).get("mode") == "own" else "none")
    _clear_scene_files(ep)
    _save_desk(ep, d)
    return episode(ws, slug)


# ---------- runs: write ahead, write again, make the video ----------
def _run(ws, day, options=None, category=None):
    from . import crew
    res = None
    for _ in range(720):   # one crew run at a time: wait up to an hour for the one in progress
        if not crew.is_running():
            res = crew.run_crew(ws, day, category, platform="youtube", options=options or {})
            if "in progress" not in str(res.get("reason") or ""):
                return res
        time.sleep(5)
    return res or {"ok": False, "reason": "another crew run kept going for an hour"}


def make(ws, slug, runner=None):
    """Make the video now (script and voice approved): the day's run, reusing the script."""
    ep = _ep(ws, slug)
    d = desk(ep)
    if d.get("script") != "approved" or (d.get("voice") or {}).get("state") != "approved":
        raise ValueError("approve the script and the voice first")
    from . import crew
    if crew.is_running():
        raise ValueError("a crew run is in progress: try again when it finishes")
    _make_now(ws, slug, d, runner)
    return episode(ws, slug)


