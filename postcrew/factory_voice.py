"""Your own voice for a Factory video: upload a recording of the whole script (or of one scene), and the video is made again with it.

Recordings live in the episode, episodes/<slug>/voice/scene<i>.wav (+ scene<i>.words.json, when each word was said), where the
factory's voice step (pipeline/tts.mjs) uses them in place of Kokoro. A whole-script take is split into scenes with faster-whisper's
word timings: each scene's share of the script's words, with the cut moved to the longest pause nearby.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .agents.shorts import factory_dir

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".webm", ".flac", ".mp4", ".mov", ".3gp", ".caf", ".aiff")
LIMIT = 300 * 2**20
CHUNK = 1 << 20
CTA_LINE = ("If this was useful, please like, comment and subscribe. And if you liked it, share it with someone who would find it "
            "helpful.")   # the factory's fallback outro (pipeline/tts.mjs CTA_LINE), read when a cta scene has no text
_render = {"slug": None, "started": None, "error": None, "done": None}
_lock = threading.Lock()


def _cfg(ws):
    from . import platforms
    return platforms.view(ws.config(), "youtube")


def _ep(ws, slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", str(slug or "")):
        raise ValueError("unknown episode")
    root = factory_dir(_cfg(ws))
    ep = root / "episodes" / slug
    if not (ep / "script.json").exists():
        raise ValueError("this episode has no script.json")
    return root, ep, json.loads((ep / "script.json").read_text())


def _secs(f):
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                    capture_output=True, text=True, timeout=60).stdout.strip())
    except (ValueError, OSError):
        return 0.0


def scene_text(sc):
    return (sc.get("text") or "").strip() or (CTA_LINE if sc.get("type") == "cta" else "")


def _tok(w):
    return re.sub(r"[^a-z0-9]", "", str(w).lower())


def own_count(ep, n):
    return sum((ep / "voice" / f"scene{i}.wav").exists() for i in range(n))


def view(ws, slug):
    root, ep, script = _ep(ws, slug)
    scenes = []
    for i, sc in enumerate(script.get("scenes") or []):
        f = ep / "voice" / f"scene{i}.wav"
        scenes.append({"i": i, "type": sc.get("type") or "", "text": scene_text(sc), "own": f.exists(),
                       "seconds": round(_secs(f), 1) if f.exists() else 0,
                       "audio": f"{slug}/voice/scene{i}.wav" if f.exists() else None})
    return {"slug": slug, "title": script.get("title") or slug, "scenes": scenes, "own": sum(s["own"] for s in scenes),
            "render": dict(_render, busy=bool(_render["slug"] and not _render["done"])), "whisper": _has_whisper()}


def _python():
    for p in ("python3", sys.executable):
        try:
            if subprocess.run([p, "-c", "import faster_whisper"], capture_output=True, timeout=60).returncode == 0:
                return p
        except OSError:
            continue
    return None


_whisper_py = {"p": "unset"}


def _has_whisper():
    if _whisper_py["p"] == "unset":
        _whisper_py["p"] = _python()
    return bool(_whisper_py["p"])


def _words(wav):
    if not _has_whisper():
        return None
    r = subprocess.run([_whisper_py["p"], str(Path(__file__).with_name("whisper_words.py")), str(wav)], capture_output=True, text=True,
                       timeout=1800)
    if r.returncode:
        raise ValueError("could not find the words in the recording: " + (r.stderr.strip().splitlines() or ["whisper failed"])[-1][:300])
    return json.loads(r.stdout or "[]")


def _ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise ValueError("ffmpeg could not read that recording: " + r.stderr.strip()[-300:])


TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse")


def _save_scene(voice, i, src, start=None, end=None, words=None):
    """One scene's take: cut (start..end), quiet ends trimmed, 48 kHz mono, with its words relative to the new start."""
    out = voice / f"scene{i}.wav"
    cut = (["-ss", f"{start:.3f}", "-to", f"{end:.3f}"] if start is not None else [])
    trim = "" if start is not None else "," + TRIM   # a cut from a whole take is already tight around its words
    _ffmpeg(*cut, "-i", str(src), "-ac", "1", "-ar", "48000", "-af", "highpass=f=70" + trim, "-c:a", "pcm_s16le", str(out))
    ws_ = _words(out) if words is None else words
    (voice / f"scene{i}.words.json").unlink(missing_ok=True)
    if ws_:
        (voice / f"scene{i}.words.json").write_text(json.dumps(ws_))
    return out


def _split(words, texts):
    """Where each scene starts in the heard words: the script's words matched to what was said (difflib), so a slip or an extra
    word does not shift the cuts; scenes with no match fall back to their share of the words. Each cut moves to the longest pause
    within two words."""
    import difflib
    said, heard = [], [_tok(w["w"]) for w in words]
    starts = []
    for t in texts:
        starts.append(len(said))
        said += [x for x in (_tok(w) for w in t.split()) if x]
    m = difflib.SequenceMatcher(None, said, heard, autojunk=False)
    pair = {}
    for a, b, n in m.get_matching_blocks():
        for k in range(n):
            pair[a + k] = b + k
    h, total, cuts = len(words), max(1, len(said)), []
    for st in starts[1:]:
        j = next((pair[k] - (k - st) for k in range(st, min(len(said), st + 6)) if k in pair), None)
        if j is None:
            j = round(st / total * h)
        j = max(1, min(h - 1, j))
        gap = lambda x: words[x]["s"] - words[x - 1]["e"]
        best = max(range(max(1, j - 2), min(h - 1, j + 2) + 1), key=lambda x: (gap(x), -abs(x - j)))
        if gap(best) > gap(j) + 0.15:   # only for a clearly longer pause: the matched word wins otherwise
            j = best
        cuts.append(max(j, (cuts[-1] + 1) if cuts else 1))
    return cuts


def upload(ws, slug, scene, name, rfile, length):
    """Store a recording. scene None/'': the whole script, split into scenes; a number: that scene only."""
    root, ep, script = _ep(ws, slug)
    scenes = script.get("scenes") or []
    ext = Path(str(name or "")).suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError("pick an audio recording (" + ", ".join(AUDIO_EXT) + ")")
    if length <= 0:
        raise ValueError("the recording is empty")
    if length > LIMIT:
        raise ValueError(f"the recording is {length / 2**20:.0f} MB; the limit is {LIMIT // 2**20} MB")
    voice = ep / "voice"
    voice.mkdir(exist_ok=True)
    tmp, left = voice / f".upload{ext}", length
    with open(tmp, "wb") as f:
        while left:
            chunk = rfile.read(min(CHUNK, left))
            if not chunk:
                tmp.unlink(missing_ok=True)
                raise ValueError("the upload ended early")
            f.write(chunk)
            left -= len(chunk)
    try:
        if scene not in (None, ""):
            i = int(scene)
            if not 0 <= i < len(scenes):
                raise ValueError("that scene is not in the script")
            _save_scene(voice, i, tmp)
            done = [i]
        else:
            full = voice / ".whole.wav"
            _ffmpeg("-i", str(tmp), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(full))
            heard = _words(full)
            if heard is None:
                raise ValueError("a whole-script recording needs faster-whisper on this computer to split it into scenes "
                                 "(pip install faster-whisper); or upload each scene on its own")
            if len(heard) < len(scenes):
                raise ValueError(f"only {len(heard)} words were heard in the recording: is it the whole script?")
            cuts = _split(heard, [scene_text(sc) for sc in scenes])
            bounds = [0] + cuts + [len(heard)]
            done = []
            for i in range(len(scenes)):
                part = heard[bounds[i]:bounds[i + 1]]
                start = max(0.0, part[0]["s"] - 0.08)
                end = part[-1]["e"] + 0.2
                rel = [{"w": w["w"], "s": round(w["s"] - start, 3), "e": round(w["e"] - start, 3)} for w in part]
                _save_scene(voice, i, full, start, end, words=rel)
                done.append(i)
            full.unlink(missing_ok=True)
            if script.get("voice") != "own":   # variety: your own voice counts as its own narrator
                script["voice_kokoro"] = script.get("voice")
                script["voice"] = "own"
                (ep / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n")
    finally:
        tmp.unlink(missing_ok=True)
    return dict(view(ws, slug), saved=done)


def clear(ws, slug, scene=None):
    """Remove your recording of one scene (or all), so Kokoro reads it again."""
    root, ep, script = _ep(ws, slug)
    voice = ep / "voice"
    idx = [int(scene)] if scene not in (None, "") else range(len(script.get("scenes") or []))
    for i in idx:
        for f in (voice / f"scene{i}.wav", voice / f"scene{i}.words.json"):
            f.unlink(missing_ok=True)
    if script.get("voice") == "own" and not own_count(ep, len(script.get("scenes") or [])):
        script["voice"] = script.pop("voice_kokoro", None) or "am_echo"
        (ep / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n")
    return view(ws, slug)


def render(ws, slug, runner=subprocess.run):
    """Make the video again with the recordings (in the background; the new video appears in the Factory's list)."""
    root, ep, script = _ep(ws, slug)
    with _lock:
        if _render["slug"] and not _render["done"]:
            raise ValueError(f"already making {_render['slug']} again: wait for it to finish")
        _render.update(slug=slug, started=time.time(), error=None, done=None)

    def go():
        try:
            r = runner(["npm", "run", "make", "--", f"episodes/{slug}", "--allow-repeat"], cwd=str(root), capture_output=True, text=True,
                       timeout=3600)
            (ep / "build").mkdir(exist_ok=True)
            (ep / "build" / "render.log").write_text((r.stdout or "") + (r.stderr or ""))
            if r.returncode:
                _render["error"] = ((r.stderr or r.stdout or "").strip().splitlines() or ["render failed"])[-1][:400]
        except Exception as e:   # never leave it stuck as busy
            _render["error"] = f"{type(e).__name__}: {e}"[:400]
        finally:
            _render["done"] = time.time()

    threading.Thread(target=go, daemon=True, name="factory-voice").start()
    return view(ws, slug)
