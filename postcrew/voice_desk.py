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
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from . import factory_voice, voice_clean
from .factory_voice import AUDIO_EXT, CTA_LINE, LIMIT, CHUNK, _ffmpeg, _secs, _tok, _words, _has_whisper

STATE = "voice-desk"
MODES = ("own", "own_us", "dip_puck", "am_puck")   # own: your recording matched to dip_puck; own_us: dip_puck reads your words; the others: that voice reads the script
HUGE_GAP = 1.2   # s: a pause inside a sentence longer than this is a hesitation, cut to KEEP_GAP
KEEP_GAP = 0.45
MAX_GAP = 0.9    # s: the longest pause kept between two sentences
CHUNK_S = 12.0   # s: the longest piece Seed-VC converts at once
UNHEARD_S = 0.35   # s: this much sound between two words that no word covers is a repeat Whisper did not write
CUT_GAP = 0.18   # s: the pause left where words were cut out (a restart, a stutter)
PAD_IN, PAD_OUT = 0.06, 0.16   # s of audio kept before a sentence's first word and after its last
_jobs = {}       # slug -> {"what", "started", "error", "done"}: background work (voice processing, a run)
_lock = threading.Lock()


# ---------- settings and places ----------
def settings(cfg):
    d = ((cfg.get("video") or {}).get("voice_desk") or {})
    return {"enabled": d.get("enabled", True),
            "seedvc_dir": d.get("seedvc_dir", "~/voicelab/seed-vc"), "target": d.get("target", "~/voicelab/refs/am_puck.wav"),   # the timbre dip_puck was trained on (measured: as close to dip_puck as a dip_puck clip)
            "steps": int(d.get("diffusion_steps", 40)), "cfg_rate": float(d.get("cfg_rate", 0.7)),
            "whisper_python": d.get("whisper_python", "~/voicelab/f5env/bin/python"), "tts_url": d.get("tts_url", "http://127.0.0.1:8882"),
            "am_url": d.get("am_url", "http://127.0.0.1:8880")}   # Kokoro, for am_puck


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


def speakable(text):
    """A colon the voice would run straight through becomes a full stop, so it pauses there (owner, 2026-11-21: "use ; or full stop,
    because : is not stopping on voice"). Times and ratios (10:30, 2:1) are kept."""
    out = re.sub(r"(?<!\d)\s*:\s*(?!\d)(\S?)", lambda m: ". " + m.group(1).upper(), str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\.\s*\.", ".", out)).strip()


tokens = lambda text: [t for t, _ in voice_clean.tokens(text)]   # kept for callers of the old helper



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
            "audio": {k: f"{slug}/voice-take/{f}" for k, f in (("converted", "take-converted.wav"), ("american", "take-american.wav"), ("cleaned", "take.wav"), ("ai", "take-ai.wav"))
                      if (take / f).exists()},
            "ai_lines": [f"{slug}/voice-take/scenes-ai/scene{i}.wav" if (take / "scenes-ai" / f"scene{i}.wav").exists() else None
                         for i in range(len(lines(script)))],
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
        d.pop("approved_beats", None)   # the lines a redraw in another look must keep are these new ones
        v = d.get("voice") or {}
        if v.get("mode") == "own":   # a recording of the old words no longer matches
            d["voice"] = {"state": "none", "note": "the script changed: record it again"}
            _clear_scene_files(ep)
        elif v.get("mode") in AI_VOICES and (ep / "voice-take" / "scenes-ai").exists():   # read the changed lines again, at once
            _save_desk(ep, d)
            changed = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
            return generate(ws, slug, v["mode"], redo=changed or None)
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


# ---------- cleaning (voice_clean.py) and the two voices made from it ----------
def _whisper(cfg, args):
    """Run whisper_words.py with the lab's GPU Python (large-v3), else the Python that has faster-whisper (CPU). None when neither works."""
    py = Path(settings(cfg)["whisper_python"]).expanduser()
    env = dict(os.environ)
    if py.exists():
        libs = sorted(str(p) for p in py.parent.parent.glob("lib/python3*/site-packages/nvidia/*/lib"))
        if libs:
            env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")])
        r = subprocess.run([str(py), str(Path(__file__).with_name("whisper_words.py"))] + args, capture_output=True, text=True, timeout=1800, env=env)
        if r.returncode == 0:
            return json.loads(r.stdout or "null")
    if not _has_whisper():
        return None
    r = subprocess.run([factory_voice._whisper_py["p"], str(Path(__file__).with_name("whisper_words.py"))] + args, capture_output=True,
                       text=True, timeout=3600)
    return json.loads(r.stdout or "null") if r.returncode == 0 else None


def _verbatim_words(cfg, wav):
    """Every word as it was SAID (repeats, restarts, fillers), with large-v3 on the GPU when the lab's GPU Python is there."""
    got = _whisper(cfg, [str(wav)])
    return got if got is not None else _words(wav)


def repeats(words):
    """Adjacent repeats in a clip's words: the earlier copy of each ("single must single must first" -> the first "single must").
    Returns [(start, end)] of the stretches to cut."""
    toks = [_tok(w["w"]) for w in words]
    cut, i = [], 0
    while i < len(toks):
        hit = 0
        for n in (5, 4, 3, 2, 1):   # the longest repeat first
            if i + 2 * n <= len(toks) and toks[i:i + n] == toks[i + n:i + 2 * n] and all(toks[i:i + n]):
                hit = n
                break
        if not hit:   # a restart that changes a word: "if this was helpful if this was useful" -> the first try goes
            for n in (4, 3, 2):
                for gap in (1, 2):
                    j = i + n + gap
                    if j + n <= len(toks) and toks[i:i + n] == toks[j:j + n] and all(toks[i:i + n]):
                        hit = j - i
                        break
                if hit:
                    break
        if hit:
            cut.append((words[i]["s"], words[i + hit]["s"]))
            i += hit
        else:
            i += 1
    return cut


def _second_pass(cfg, clips):
    """Listen to each cleaned sentence again (short audio: Whisper writes repeats it missed in the long take) and cut what is said
    twice. clips: [sentence dict with "file", "words", "secs"]."""
    got = _whisper(cfg, ["--many"] + [str(c["file"]) for c in clips]) or {}
    fixed = 0
    for c in clips:
        ws_ = got.get(str(c["file"])) or []
        cuts = repeats(ws_)
        if not cuts:
            continue
        keep, t = [], 0.0
        for a, b in cuts:
            if a - t > 0.05:
                keep.append((t, a))
            t = b
        keep.append((t, c["secs"] + 0.05))
        tmp = c["file"].with_name(c["file"].stem + "-2.wav")
        filt = "".join(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01[k{n}];" for n, (a, b) in enumerate(keep))
        filt += "".join(f"[k{n}]" for n in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[out]"
        _ffmpeg("-i", str(c["file"]), "-filter_complex", filt, "-map", "[out]", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(tmp))
        tmp.replace(c["file"])
        removed = sum(b - a for a, b in cuts)
        new_words, shift = [], 0.0
        for w in c["words"]:   # re-time the words: everything after a cut moves back
            shift = sum(b - a for a, b in cuts if b <= w["s"] + 0.02)
            if any(a - 0.02 <= w["s"] < b - 0.02 for a, b in cuts):
                continue
            new_words.append({"w": w["w"], "s": round(w["s"] - shift, 3), "e": round(w["e"] - shift, 3)})
        c["words"], c["secs"] = new_words, max(0.1, c["secs"] - removed)
        c["repeats_cut"] = [" ".join(x["w"] for x in ws_ if a - 0.01 <= x["s"] < b) for a, b in cuts]
        fixed += len(cuts)
    return fixed


def silences(wav, floor_db=-38, min_s=0.18):
    """Where the recording is silent: [(start, end)] (ffmpeg silencedetect)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", f"silencedetect=n={floor_db}dB:d={min_s}", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


def fit_to_sound(words, quiet):
    """Whisper folds a pause into the word next to it ("points" 7 s long, "step" 3.7 s): each word is trimmed to the sound it overlaps
    most, and never longer than it can be said. Without this a cut keeps a long silence or slices a word in half."""
    for w in words:
        s, e = w["s"], w["e"]
        pieces, t = [], s
        for a, b in quiet:   # the sounding parts of [s, e]
            if b <= t or a >= e:
                continue
            if a > t:
                pieces.append((t, a))
            t = max(t, b)
        if t < e:
            pieces.append((t, e))
        if pieces:   # Whisper glues a word to the pause BEFORE it: the word is the last sounding part (unless that is only a click)
            real = [p for p in pieces if p[1] - p[0] >= 0.12]
            s, e = (real or pieces)[-1] if real else max(pieces, key=lambda p: p[1] - p[0])
        most = 0.25 + 0.1 * len(re.sub(r"[^A-Za-z0-9]", "", w["w"]))
        if e - s > most:   # still too long: keep the end near the next sound, the start where the sound starts
            e = s + most
        w["s"], w["e"] = round(s, 3), round(max(e, s + 0.05), 3)
    for a, b in zip(words, words[1:]):   # no overlaps
        if b["s"] < a["e"]:
            b["s"] = a["e"]
            b["e"] = max(b["e"], b["s"] + 0.05)


def _sound_between(quiet, a, b):
    """Seconds of sound (not silence) between a and b."""
    if b <= a:
        return 0.0
    return (b - a) - sum(max(0.0, min(b, y) - max(a, x)) for x, y in quiet)


def _runs(words, keep, quiet=()):
    """The kept words as pieces of audio: [(start, end, pause after)]. A pause between kept neighbours stays as it was (a huge one is
    shortened); where words were cut between two kept words, the pause becomes short. Sound between two kept neighbours that no word
    covers is speech Whisper did not write down (it drops some repeats: "single must, single must"): it is cut too."""
    runs, shortened = [], 0
    for n, k in enumerate(keep):
        w = words[k]
        if not runs:
            runs.append([w["s"], w["e"], None])
            continue
        prev = keep[n - 1]
        gap = w["s"] - words[prev]["e"]
        hidden = _sound_between(quiet, words[prev]["e"] + 0.04, w["s"] - 0.04) if quiet else 0.0
        if k == prev + 1 and gap <= HUGE_GAP and hidden < UNHEARD_S:
            runs[-1][1] = w["e"]   # said straight on: one piece, its pause untouched
            continue
        if k == prev + 1 and hidden >= UNHEARD_S:   # unwritten speech in between: cut it, short pause
            runs[-1][2] = CUT_GAP
            shortened += 1
            runs.append([w["s"], w["e"], None])
            continue
        if k == prev + 1:
            runs[-1][2] = KEEP_GAP; shortened += 1
        else:   # words cut in between (a restart, a stutter, a filler)
            runs[-1][2] = max(0.08, min(CUT_GAP, words[prev + 1]["s"] - words[prev]["e"]))
        runs.append([w["s"], w["e"], None])
    return runs, shortened


def _render(src, runs, words_in, out_wav):
    """One sentence's clip from its pieces (10 ms fades at every cut, no clicks) and its words re-timed to the clip."""
    parts, filt, t, out_words = [], [], 0.0, []
    for k, (a, b, gap) in enumerate(runs):
        s0, s1 = max(0.0, a - PAD_IN), b + PAD_OUT
        d = s1 - s0
        filt.append(f"[0:a]atrim={s0:.3f}:{s1:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st={max(0.0, d - 0.012):.3f}:d=0.012[p{k}]")
        parts.append(f"[p{k}]")
        out_words += [{"w": w["w"], "s": round(t + w["s"] - s0, 3), "e": round(t + w["e"] - s0, 3)} for w in words_in if a - 1e-3 <= w["s"] and w["e"] <= b + 1e-3]
        t += d
        if gap:
            filt.append(f"anullsrc=r=48000:cl=mono,atrim=0:{gap:.3f}[g{k}]")
            parts.append(f"[g{k}]")
            t += gap
    filt.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1[out]")
    _ffmpeg("-i", str(src), "-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav))
    return out_words, t


def _silence(path, secs):
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{max(0.01, secs):.3f}", "-c:a", "pcm_s16le", str(path))


def _join(files_gaps, out_wav, tmpd):
    """Clips with a pause after each: [(file, pause)] -> one wav."""
    listing = []
    for n, (f, gap) in enumerate(files_gaps):
        listing.append(f"file '{Path(f).resolve()}'")
        if gap:
            g = tmpd / f"gap{n}.wav"
            _silence(g, gap)
            listing.append(f"file '{g.resolve()}'")
    lst = tmpd / f"{Path(out_wav).stem}.txt"
    lst.write_text("\n".join(listing) + "\n")
    _ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav))


def tts(cfg, text, out_wav, voice="dip_puck", url=None):
    """The channel voice reads one sentence (the lab's dip_puck server; url: another Kokoro-compatible server)."""
    import urllib.request
    s = dict(settings(cfg), tts_url=url or settings(cfg)["tts_url"])
    req = urllib.request.Request(s["tts_url"].rstrip("/") + "/v1/audio/speech",
                                 json.dumps({"model": "kokoro", "input": text, "voice": voice, "response_format": "wav"}).encode(),
                                 {"Content-Type": "application/json"})
    raw = Path(out_wav).with_suffix(".raw.wav")
    try:
        raw.write_bytes(urllib.request.urlopen(req, timeout=300).read())
    except OSError as e:
        raise ValueError(f"the dip_puck voice server did not answer ({s['tts_url']}): {e}")
    _ffmpeg("-i", str(raw), "-ac", "1", "-ar", "48000", "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-c:a", "pcm_s16le", str(out_wav))
    raw.unlink(missing_ok=True)


def _even_words(text, secs):
    ws = [w for w in str(text).split() if w]
    tot = sum(len(w) + 1 for w in ws) or 1
    out, t = [], 0.0
    for w in ws:
        d = secs * (len(w) + 1) / tot
        out.append({"w": w, "s": round(t, 3), "e": round(t + d * 0.9, 3)})
        t += d
    return out


# ---------- matching the channel voice: Seed-VC to the dip_puck timbre ----------
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
    _ffmpeg("-i", str(got[-1]), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav))
    shutil.rmtree(tmp, ignore_errors=True)


def process(ws, slug, converter=convert, words_of=None, speaker=None):
    """Clean the uploaded take, then make it two ways for you to choose (both wait for your approval):
    matched  = your own recording, cleaned, converted to the dip_puck timbre (your delivery, your accent);
    american = dip_puck reads the script's sentences with your pauses between them and your reading of abbreviations (the channel's
               American sound; measured 2026-11-17: converting your recording keeps your accent and blurs words, this does not).
    A sentence you mispronounced (and did not say again correctly) is read by dip_puck in both."""
    ep = _ep(ws, slug)
    take = ep / "voice-take"
    raw = next(iter(sorted(take.glob("upload.*"))), None)
    if not raw:
        raise ValueError("no recording uploaded")
    cfg = _cfg(ws)
    speak = speaker or (lambda text, out: tts(cfg, text, out))
    try:
        script = _read(ep / "script.json", {})
        texts = lines(script)
        full = take / "take-original.wav"
        _ffmpeg("-i", str(raw), "-ac", "1", "-ar", "48000", "-af", "highpass=f=70", "-c:a", "pcm_s16le", str(full))
        heard = (words_of or (lambda f: _verbatim_words(cfg, f)))(full) or []
        if len(heard) < 10:
            raise ValueError(f"only {len(heard)} words were heard in the recording: is it the whole script?")
        quiet = silences(full)
        fit_to_sound(heard, quiet)
        sents, removed = voice_clean.clean(heard, texts)
        tmpd = take / "work"
        shutil.rmtree(tmpd, ignore_errors=True)
        tmpd.mkdir()
        shortened, own, fixed = 0, [], []
        said_lines = {s["line"] for s in sents if not s["missing"]}
        for n, s in enumerate(sents):   # each sentence: your clip, or dip_puck when it was mispronounced or not said
            s["n"] = n
            if s["missing"] and s["line"] not in said_lines:
                s["kind"] = "none"   # a whole line not recorded (the outro, usually): the factory's dip_puck reads it
                continue
            if s["missing"] or s["bad"]:
                s["kind"] = "ai"
                if not s["missing"]:
                    fixed.append({"line": s["line"] + 1, "said": s.get("said", ""), "script": s["text"],
                                  "words": [f"{a or '(not said)'} → {b}" for a, b in s["bad"]][:4]})
                continue
            s["kind"] = "own"
            runs, sh = _runs(heard, s["keep"], quiet)
            shortened += sh
            s["file"] = tmpd / f"s{n}.wav"
            s["words"], s["secs"] = _render(full, runs, [heard[k] for k in s["keep"]], s["file"])
            own.append(s)
        second = 0
        if own and not words_of:   # (tests pass words_of: no Whisper there)
            for _ in range(2):   # a cut can bring two copies together: listen once more
                n_cut = _second_pass(cfg, own)
                second += n_cut
                if not n_cut:
                    break
        if not own and not any(s["kind"] == "ai" and not s["missing"] for s in sents):
            raise ValueError("none of the script's lines was found in the recording")
        # the pause after each sentence: as you left it (up to MAX_GAP); between lines the factory adds its own
        for a, b in zip(sents, sents[1:]):
            a["pause"] = 0.0
            if a["line"] == b["line"]:
                g = 0.45
                if a.get("keep") and b.get("keep"):
                    g = heard[b["keep"][0]]["s"] - heard[a["keep"][-1]]["e"]
                a["pause"] = min(MAX_GAP, max(0.25, g))
        if sents:
            sents[-1]["pause"] = 0.0
        # dip_puck for the sentences it must read (both versions use them)
        for s in sents:
            if s["kind"] == "ai":
                s["ai_file"] = tmpd / f"ai{s['n']}.wav"
                speak(s["text"], s["ai_file"])
                s["ai_secs"] = _secs(s["ai_file"]) or 1.0
        # 1. matched: your clips converted with Seed-VC in short pieces (CHUNK_S): on one long take it loses words after a minute
        #    (measured 2026-11-17: "Delete is a big win" came out as "Big Hit is a big weed"), then cut again
        sep, groups, cur = 0.6, [], []
        for s in own:
            if cur and sum(x["secs"] + sep for x in cur) + s["secs"] > CHUNK_S:
                groups.append(cur); cur = []
            cur.append(s)
        if cur:
            groups.append(cur)
        for g, group in enumerate(groups):
            joined, conv = tmpd / f"own{g}.wav", tmpd / f"own{g}-converted.wav"
            _join([(s["file"], sep) for s in group], joined, tmpd)
            converter(cfg, joined, conv)
            k = (_secs(conv) / _secs(joined)) if _secs(joined) and _secs(conv) else 1.0
            t = 0.0
            for s in group:
                s["conv"] = tmpd / f"c{s['n']}.wav"
                _ffmpeg("-ss", f"{t * k:.3f}", "-t", f"{s['secs'] * k:.3f}", "-i", str(conv), "-c:a", "pcm_s16le", str(s["conv"]))
                s["conv_words"] = [{"w": w["w"], "s": round(w["s"] * k, 3), "e": round(w["e"] * k, 3)} for w in s["words"]]
                t += s["secs"] + sep
        # 2. american: dip_puck reads what you said, sentence by sentence
        for s in sents:
            if s["kind"] == "own":
                s["us_file"] = tmpd / f"us{s['n']}.wav"
                speak(s["spoken"], s["us_file"])
                s["us_secs"] = _secs(s["us_file"]) or 1.0
        out = {}
        for mode, folder in (("own", "scenes"), ("own_us", "scenes-us")):
            staged = take / folder
            shutil.rmtree(staged, ignore_errors=True)
            staged.mkdir()
            allf = []
            for line in sorted(said_lines):
                parts, words, t = [], [], 0.0
                for s in [x for x in sents if x["line"] == line]:
                    if s["kind"] == "ai":
                        f, ws_ = s["ai_file"], _even_words(s["text"], s["ai_secs"])
                    elif mode == "own":
                        f, ws_ = s["conv"], s["conv_words"]
                    else:
                        f, ws_ = s["us_file"], _even_words(s["spoken"], s["us_secs"])
                    words += [{"w": w["w"], "s": round(w["s"] + t, 3), "e": round(w["e"] + t, 3)} for w in ws_]
                    parts.append((f, s["pause"]))
                    t += (_secs(f) or 0) + s["pause"]
                clip = staged / f"scene{line}.wav"
                _join(parts, clip, tmpd)
                _write(staged / f"scene{line}.words.json", words)
                allf.append((clip, 0.6))
            prev = take / ("take-converted.wav" if mode == "own" else "take-american.wav")
            _join(allf, prev, tmpd)
            out[mode] = round(sum(_secs(f) or 0 for f, _ in allf), 1)
        cleaned = take / "take.wav"   # your own voice, cleaned (to compare)
        if own:
            _join([(s["file"], s.get("pause") or 0.6) for s in own], cleaned, tmpd)
        shutil.rmtree(tmpd, ignore_errors=True)
        missing = [s for s in sents if s["missing"]]
        outro_line = len(texts) - 1 if script.get("beats") else None
        outro_missing = outro_line is not None and all(s["missing"] for s in sents if s["line"] == outro_line)
        rep = {"heard_words": len(heard), "kept_lines": len({s["line"] for s in sents if s["kind"] == "own"}), "lines": len(texts),
               "removed": ([r for r in removed if r.strip()] + [x for s in own for x in s.get("repeats_cut", [])])[:60], "fixed": fixed,
               "second_pass_cuts": second,
               "missing": [{"line": s["line"] + 1, "text": s["text"]} for s in missing if not (outro_missing and s["line"] == outro_line)],
               "outro_recorded": not outro_missing, "huge_gaps_shortened": shortened, "seconds": out.get("own"), "seconds_us": out.get("own_us"),
               "voiced_by_ai": sorted({s["line"] + 1 for s in sents if s["kind"] == "ai"}), "done": time.time()}
        _write(take / "report.json", rep)
        d = desk(ep)
        d["voice"] = dict(d.get("voice") or {}, state="ready", mode="own")
        d["voice"].pop("error", None)
        _save_desk(ep, d)
    except Exception as e:
        d = desk(ep)
        d["voice"] = dict(d.get("voice") or {}, state="failed", error=str(e)[:500])
        _save_desk(ep, d)
        raise


def choose(ws, slug, mode):
    """Approve the voice: own (your processed recording), or the dip_puck / am_puck take generated for you to listen to first."""
    if mode not in MODES:
        raise ValueError("voice must be one of: " + ", ".join(MODES))
    ep = _ep(ws, slug)
    d = _adopt(ep)
    script = _read(ep / "script.json", {})
    v = d.get("voice") or {}
    ai = mode in AI_VOICES
    staged = ep / "voice-take" / ("scenes-ai" if ai else "scenes" if mode == "own" else "scenes-us")
    if ai and (v.get("mode") != mode or v.get("state") not in ("ready", "approved") or not staged.exists()):
        raise ValueError(f"generate the {mode} voice first and listen to it")
    if not ai and (v.get("state") not in ("ready", "approved") or not staged.exists()):
        raise ValueError("upload your recording first, and wait for it to be processed")
    _clear_scene_files(ep)
    (ep / "voice").mkdir(exist_ok=True)
    for f in staged.iterdir():   # the video uses exactly the take you heard
        shutil.copy2(f, ep / "voice" / f.name)
    if ai:
        script["voice_kokoro"] = mode
    elif script.get("voice") != "own":
        script["voice_kokoro"] = script.get("voice") if script.get("voice") in ("dip_puck", "am_puck") else "dip_puck"
    script["voice"] = "own"   # lines not in the take are read by voice_kokoro
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


# ---------- dip_puck / am_puck: generated at once, listened to, regenerated from your feedback (owner, 2026-11-18) ----------
AI_VOICES = ("dip_puck", "am_puck")
LINE_GAP = 0.6   # between lines in the preview (and the gap the video leaves between beats)


def generate(ws, slug, voice, feedback="", redo=None):
    """Make the voice now so you can listen before approving: every line read by `voice`. With feedback, it is regenerated: the feedback
    is turned into concrete changes (pace, pauses, how a word is said, which lines to read again) and only those lines are read again."""
    if voice not in AI_VOICES:
        raise ValueError("voice must be dip_puck or am_puck")
    ep = _ep(ws, slug)
    d = _adopt(ep)
    if vd_busy(slug):
        raise ValueError("the voice is already being made: wait for it")
    feedback = str(feedback or "").strip()[:2000]
    old = d.get("voice") or {}
    prev = old.get("ai") if old.get("mode") == voice else None
    d["voice"] = {"state": "processing", "mode": voice, "ai": prev or {}, "note": ""}
    _clear_scene_files(ep)
    _save_desk(ep, d)
    _start(slug, "voice", lambda: _generate(ws, ep, voice, feedback, prev, redo))
    return episode(ws, slug)


def vd_busy(slug):
    j = _jobs.get(slug)
    return bool(j and j.get("done") is None)


def _generate(ws, ep, voice, feedback, prev, redo):
    cfg = _cfg(ws)
    try:
        script = _read(ep / "script.json", {})
        texts = lines(script)
        ai = dict(prev or {})
        ai.setdefault("speed", 1.0)
        ai.setdefault("pause", 0.35)
        ai.setdefault("say", {})
        ai.setdefault("feedback", [])
        redo_lines = set(range(len(texts)))
        if feedback or redo:
            change = _feedback_to_changes(ws, cfg, texts, feedback, ai) if feedback else {}
            ai["speed"] = min(1.25, max(0.75, float(change.get("speed") or ai["speed"])))
            ai["pause"] = min(1.2, max(0.1, float(change.get("pause") or ai["pause"])))
            for w, how in (change.get("say") or {}).items():
                if str(w).strip() and str(how).strip():
                    ai["say"][str(w).strip()] = str(how).strip()
            asked = {int(i) - 1 for i in (change.get("lines") or []) if str(i).isdigit()} | {int(i) for i in (redo or [])}
            asked = {i for i in asked if 0 <= i < len(texts)}
            same_feel = change.get("speed") in (None, prev and prev.get("speed")) and change.get("pause") in (None, prev and prev.get("pause"))
            if prev and asked and same_feel and not change.get("say"):
                redo_lines = asked   # only the lines you named
            ai["feedback"] = (ai["feedback"] + [{"text": feedback, "changes": change, "at": time.time()}])[-10:] if feedback else ai["feedback"]
        take = ep / "voice-take"
        staged = take / "scenes-ai"
        staged.mkdir(parents=True, exist_ok=True)
        tmpd = take / "tmp-ai"
        shutil.rmtree(tmpd, ignore_errors=True)
        tmpd.mkdir()
        allf = []
        for i, text in enumerate(texts):
            clip = staged / f"scene{i}.wav"
            if i in redo_lines or not clip.exists():
                parts, words, t = [], [], 0.0
                for n, sent in enumerate(_sentences(speakable(text))):
                    raw = tmpd / f"l{i}s{n}.wav"
                    _ai_tts(cfg, voice, _respell(sent, ai["say"]), raw)
                    if abs(ai["speed"] - 1.0) > 0.01:
                        fast = tmpd / f"l{i}s{n}f.wav"
                        _ffmpeg("-i", str(raw), "-af", f"atempo={ai['speed']:.3f}", "-c:a", "pcm_s16le", str(fast))
                        raw = fast
                    secs = _secs(raw) or 1.0
                    words += [{"w": w["w"], "s": round(w["s"] + t, 3), "e": round(w["e"] + t, 3)} for w in _even_words(sent, secs)]
                    parts.append((raw, ai["pause"]))
                    t += secs + ai["pause"]
                if parts:
                    parts[-1] = (parts[-1][0], 0)
                _join(parts, clip, tmpd)
                _write(staged / f"scene{i}.words.json", words)
            allf.append((clip, LINE_GAP))
        _join(allf, take / "take-ai.wav", tmpd)
        shutil.rmtree(tmpd, ignore_errors=True)
        ai.update(voice=voice, made=time.time(), redone=sorted(i + 1 for i in redo_lines) if len(redo_lines) < len(texts) else [],
                  seconds=round(sum(_secs(f) or 0 for f, _ in allf), 1))
        d = desk(ep)
        d["voice"] = {"state": "ready", "mode": voice, "ai": ai}
        _save_desk(ep, d)
    except Exception as e:
        d = desk(ep)
        d["voice"] = {"state": "failed", "mode": voice, "error": f"{e}"[:400], "ai": prev or {}}
        _save_desk(ep, d)
        raise


def _ai_tts(cfg, voice, text, out):
    if voice == "dip_puck":
        return tts(cfg, text, out, voice)
    tts(cfg, text, out, voice, url=settings(cfg)["am_url"])


def _respell(text, say):
    for w, how in (say or {}).items():
        text = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", how, text, flags=re.I)
    return text


FEEDBACK_SCHEMA = {"type": "object", "properties": {
    "speed": {"type": ["number", "null"], "description": "new tempo factor for the whole voice, 1.0 = as generated (0.75-1.25), null = keep"},
    "pause": {"type": ["number", "null"], "description": "seconds of pause between sentences (0.1-1.2), null = keep"},
    "say": {"type": "object", "additionalProperties": {"type": "string"},
            "description": "words or abbreviations said wrong -> how to write them so the voice says them right, e.g. {\"SQL\": \"sequel\", \"O(n)\": \"O of n\"}"},
    "lines": {"type": "array", "items": {"type": "integer"}, "description": "1-based line numbers to read again (empty = all of them)"},
    "summary": {"type": "string", "description": "one sentence: what will change"}},
    "required": ["lines", "summary"]}


def _feedback_to_changes(ws, cfg, texts, feedback, ai):
    """The owner's words about the voice -> concrete changes the voice can make."""
    from .llm import make_backend, LLMError
    system = ("You turn a YouTube creator's feedback on an AI narration voice into concrete changes. The voice is a text-to-speech model; "
              "it can only be changed by: tempo (speed factor), the pause between sentences, rewriting how a word is spelled so it is "
              "pronounced right (a respelling sent to the voice; the script itself does not change), and reading some lines again "
              "(each new reading sounds a little different). Change only what the feedback asks for.")
    prompt = (f"Current settings: speed {ai.get('speed', 1.0)}, pause {ai.get('pause', 0.35)} s, respellings {json.dumps(ai.get('say') or {})}.\n\n"
              "The lines:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts)) + f"\n\nThe owner's feedback:\n{feedback}")
    try:
        llm = make_backend(cfg, ws.secrets())
        return llm.call("writer", system, prompt, FEEDBACK_SCHEMA, tools=(), cwd=str(_root(ws))).data or {}
    except (LLMError, Exception) as e:
        low = feedback.lower()   # without the model: the common asks still work
        out = {"lines": [int(n) for n in re.findall(r"line\s*(\d+)", low)], "summary": f"model unavailable ({str(e)[:80]})"}
        if re.search(r"slow", low):
            out["speed"] = round(float(ai.get("speed", 1.0)) - 0.08, 2)
        elif re.search(r"fast|quick", low):
            out["speed"] = round(float(ai.get("speed", 1.0)) + 0.08, 2)
        return out


def reopen_voice(ws, slug):
    """Take the voice approval back (to upload again or pick another voice)."""
    ep = _ep(ws, slug)
    d = desk(ep)
    mode = (d.get("voice") or {}).get("mode")
    has_take = (ep / "voice-take" / ("scenes-ai" if mode in AI_VOICES else "scenes")).exists()
    d["voice"] = dict(d.get("voice") or {}, state="ready" if has_take and mode in ("own", "own_us") + AI_VOICES else "none")
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




def busy():
    """A voice being processed or generated, or a video being made from the desk (a restart would cut it off)."""
    return any(j.get("done") is None for j in _jobs.values())
