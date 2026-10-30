"""ElevenLabs text-to-speech: voices, key check, synthesis with a content-addressed mp3 cache.

Standard library only. ffmpeg/ffprobe are used (when present) to join long narrations and to measure length.
"""
import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .speech import speakable

API = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"
MAX_CHARS = 4500
RETRY_CODES = (408, 500, 502, 503, 504)
ENDS = (". ", "! ", "? ", ".\n", "!\n", "?\n", "\n\n")
sleep = time.sleep  # tests replace this


class VoiceError(RuntimeError):
    def __init__(self, message, kind="failed", status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


def _detail(raw):
    """The API's own message out of an error body, as short readable text."""
    text = raw.decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
    try:
        d = json.loads(text).get("detail", text)
        if isinstance(d, dict):
            d = d.get("message") or d.get("status") or json.dumps(d)
        elif isinstance(d, list):
            d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        return str(d)[:400]
    except (ValueError, AttributeError):
        return text[:400]


def _request(method, path, api_key, body=None, opener=None, tries=3, timeout=120):
    """Returns the raw response bytes. Retries 429/5xx with a short backoff; maps failures to VoiceError."""
    opener = opener or urllib.request.urlopen
    for i in range(tries):
        data, headers = None, {"xi-api-key": api_key, "Accept": "*/*"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with opener(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            detail = _detail(raw)
            low = (raw.decode(errors="replace") if raw else "").lower()
            if e.code in (401, 403):
                raise VoiceError("ElevenLabs rejected the API key", "auth", e.code)
            if "quota" in low or (e.code == 429 and "credit" in low):
                raise VoiceError(f"ElevenLabs quota used up: {detail}", "quota", e.code)
            if e.code in RETRY_CODES + (429,) and i < tries - 1:
                sleep(2 * (i + 1))
                continue
            if e.code == 429:
                raise VoiceError("ElevenLabs is rate limiting requests; try again shortly", "quota", e.code)
            if e.code in (400, 404, 422):
                raise VoiceError(f"ElevenLabs refused the request: {detail}", "invalid", e.code)
            raise VoiceError(f"ElevenLabs HTTP {e.code}: {detail}", "failed", e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if i < tries - 1:
                sleep(2 * (i + 1))
                continue
            raise VoiceError(f"could not reach ElevenLabs: {getattr(e, 'reason', e)}", "network")


def list_voices(api_key, opener=None):
    d = json.loads(_request("GET", "/v1/voices", api_key, opener=opener, timeout=30) or b"{}")
    return [{"id": v.get("voice_id", ""), "name": v.get("name", ""), "category": v.get("category", ""),
             "preview_url": v.get("preview_url", "")} for v in d.get("voices", [])]


def check_key(api_key, opener=None):
    try:
        d = json.loads(_request("GET", "/v1/user/subscription", api_key, opener=opener, timeout=30) or b"{}")
    except VoiceError as e:
        return {"ok": False, "message": str(e), "characters_left": None}
    try:
        left = max(0, int(d["character_limit"]) - int(d["character_count"]))
    except (KeyError, TypeError, ValueError):
        return {"ok": True, "message": "ElevenLabs key works", "characters_left": None}
    return {"ok": True, "message": f"ElevenLabs key works, {left:,} characters left", "characters_left": left}


PAUSES = {"normal": (0.2, 0.7), "slow": (0.35, 1.0)}   # seconds after a sentence, and after a deliberate "..."


MAX_BREAKS = 14   # ElevenLabs: "too many break tags in a single generation can cause instability" (speed-ups, noises); a scene is ~60 words
# Measured on the same sentence: no tag = a gap of 0.03 s (the voice runs the comma on); a 0.1 s tag = 0.35 s; 0.3 s = 0.39 s; 0.5 s = 0.56 s.
# So a short tag already gives the voice's natural comma stop, and a longer one lengthens it: the slow teaching pace asks for 0.4 s (about 0.45 s).
COMMA_S = {"normal": 0.1, "slow": 0.4}


def prepare(text, model=DEFAULT_MODEL, pace="normal"):
    """The narration as ElevenLabs should read it. Every symbol, number, abbreviation and acronym is first written out as the words to
    be said (speech.speakable): the model makes a noise on what it cannot read. Then the pauses, so the voice stops where the
    punctuation says: a comma gets a small breath, a sentence end the short pause (a longer one at the slow pace) and a deliberate
    "..." the long beat. The script keeps clean text (captions and timing use that); only what is sent to the voice has <break> tags,
    at most MAX_BREAKS per request (the deliberate beats first, then sentence ends, then commas). Models that do not understand
    break tags (eleven_v3) get the words only."""
    if "<break" in str(text):   # already prepared
        return " ".join(str(text).split())
    text = speakable(text)
    if str(model).startswith("eleven_v3"):
        return text
    sentence_s, beat_s = PAUSES.get(pace, PAUSES["normal"])
    comma_s = COMMA_S.get(pace, COMMA_S["normal"])
    budget = [MAX_BREAKS]

    def tag(sec, after=""):
        if budget[0] <= 0:
            return after + " "
        budget[0] -= 1
        return f'{after} <break time="{sec}s" /> '
    text = re.sub(r"\s*(?:\.\.\.|\u2026)\s*", lambda m: tag(beat_s), text)
    # a sentence end gets its pause whatever starts the next sentence: speakable() has already written "RAG" or "100" as lower-case words,
    # and requiring a capital letter lost the pause before every sentence that began with an acronym or a number (an abbreviation like
    # "e.g." or "vs." does not end a sentence)
    text = re.sub(r"(?<!e\.g)(?<!i\.e)(?<!\bvs)(?<!\betc)(?<!\bMr)(?<!\bMrs)(?<!\bDr)([.!?])\s+(?=[\w\"'(])", lambda m: tag(sentence_s, m.group(1)), text)
    # a comma that ends a clause ("In Python, a list works", "The closer needs round, but...") must stop the voice; the voice sometimes runs it
    # on (a gap of 0.0 s was measured). Items of a list ("curly, square, round") keep the voice's own short breath.
    def comma(m):
        clause = re.split(r"[.,;:!?>]", text[:m.start()])[-1].split()
        return tag(comma_s, m.group(1)) if len(clause) >= 2 else m.group(0)
    text = re.sub(r"([,;:])\s+(?=\w)", comma, text)
    return re.sub(r"\s+", " ", text).strip()


def pause_problems(words, pace="normal"):
    """Where a recorded voice stops against where the punctuation says it should: [(word, what)] from word times ([{text, start, end}], the
    punctuation kept on the word). A sentence end with no stop, a clause comma that was run on, and a stop in the middle of a phrase.
    The slow teaching pace is stricter: a human reading slowly stops longer at every clause and never stops inside a phrase."""
    slow = pace == "slow"
    sentence_min, comma_min, comma_words, phrase_max = (0.4, 0.2, 2, 0.15) if slow else (0.25, 0.12, 3, 0.45)   # slow: words in this voice are 0.02-0.07 s apart
    found, clause = [], 0
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        mark = re.search(r"[.?!,;:]$", a["text"])
        clause += 1
        if mark and mark.group(0) in ".?!":
            if gap < sentence_min:
                found.append((a["text"], f"no stop after the sentence end ({gap:.2f}s)"))
            clause = 0
        elif mark:
            if clause >= comma_words and gap < comma_min:
                found.append((a["text"], f"the comma was run on ({gap:.2f}s)"))
            clause = 0
        elif gap > phrase_max:
            found.append((a["text"], f"it stops in the middle of a phrase ({gap:.2f}s)"))
    return found


def words_from_alignment(alignment):
    """Words with their start and end seconds out of ElevenLabs' character timing. The <break .../> tags have no sound and are left out."""
    chars = alignment.get("characters") or []
    starts, ends = alignment.get("character_start_times_seconds") or [], alignment.get("character_end_times_seconds") or []
    s = "".join(chars)
    skip = set()
    for m in re.finditer(r"<break[^>]*/>", s):
        skip.update(range(m.start(), m.end()))
    words, cur = [], None
    for i, (c, a, b) in enumerate(zip(chars, starts, ends)):
        if i in skip or c.isspace():
            cur = None
            continue
        if cur is None:
            cur = {"text": "", "start": a, "end": b}
            words.append(cur)
        cur["text"] += c
        cur["end"] = b
    return words


# Natural but steady. Lower stability and any "style" make the voice drift and invent sounds on short words ("a", "the") or after a
# pause (a stray "ooo"), so both stay conservative; raise them per voice with video.voice.stability / style if you like the result.
HUMAN = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}


def synthesize(text, voice_id, api_key, out_path, model=DEFAULT_MODEL, speed=1.0, opener=None, settings=None, prepared=False, seed=None):
    if not (text or "").strip():
        raise VoiceError("nothing to say: the narration is empty", "invalid")
    if not voice_id:
        raise VoiceError("no voice chosen: pick an ElevenLabs voice first", "invalid")
    text = text if prepared else prepare(text, model)
    body = {"text": text, "model_id": model,
            "voice_settings": dict(HUMAN, **(settings or {}), speed=speed)}
    if seed is not None:   # the voice varies from take to take; a different seed is another take of the same words
        body["seed"] = int(seed)
    audio = _request("POST", f"/v1/text-to-speech/{urllib.parse.quote(voice_id, safe='')}?output_format=mp3_44100_128",
                     api_key, body, opener)
    if not audio:
        raise VoiceError("ElevenLabs returned no audio", "failed")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(text)}


def synthesize_timed(text, voice_id, api_key, out_path, model=DEFAULT_MODEL, speed=1.0, opener=None, settings=None, seed=None,
                     before="", after=""):
    """Like synthesize(), but also asks for the time of every character, so the pauses can be checked against the punctuation. `before` and
    `after` are the text that comes before and after this one in the video: the voice uses them to carry its intonation across the join
    (the scenes are recorded one at a time). Returns {path, seconds, characters, words}."""
    body = {"text": text, "model_id": model, "voice_settings": dict(HUMAN, **(settings or {}), speed=speed)}
    if seed is not None:
        body["seed"] = int(seed)
    if not str(model).startswith("eleven_v3"):   # v3 does not take them
        if before:
            body["previous_text"] = before[-300:]
        if after:
            body["next_text"] = after[:300]
    raw = _request("POST", f"/v1/text-to-speech/{urllib.parse.quote(voice_id, safe='')}/with-timestamps?output_format=mp3_44100_128",
                   api_key, body, opener)
    try:
        d = json.loads(raw)
        audio = base64.b64decode(d["audio_base64"])
    except (ValueError, KeyError, TypeError):
        raise VoiceError("ElevenLabs returned no audio", "failed")
    if not audio:
        raise VoiceError("ElevenLabs returned no audio", "failed")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(text),
            "words": words_from_alignment(d.get("alignment") or d.get("normalized_alignment") or {})}


TAKE_SEEDS = (None, 17, 29)   # a scene is recorded up to three times when a pause is in the wrong place; the best take is kept


def audio_seconds(path):
    path = str(path)
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                               capture_output=True, text=True, timeout=60)
            return float(r.stdout.strip().splitlines()[0])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    try:
        return Path(path).stat().st_size / 16000.0  # 128 kbps mp3 = 16000 bytes per second
    except OSError:
        return 0.0


def split_text(text, limit=MAX_CHARS):
    """Pieces of at most `limit` characters, cut at sentence ends (or spaces, or hard if there is no choice)."""
    text = text.strip()
    pieces = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind(m) + len(m) for m in ENDS if m in window) if any(m in window for m in ENDS) else 0
        if cut < limit // 4:
            cut = window.rfind(" ") + 1 or limit
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


def _concat(parts, out_path):
    if not shutil.which("ffmpeg"):
        raise VoiceError("ffmpeg is needed to join a long narration but was not found", "failed")
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "parts.txt"
        lst.write_text("".join("file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n" for p in parts))
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", str(out_path)],
                           capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise VoiceError(f"ffmpeg could not join the audio parts: {r.stderr.strip()[-300:]}", "failed")


def cached_synthesize(root, text, voice_cfg, api_key, opener=None, seed=None, align=False, before="", after=""):
    """One scene's recording, cached by text, voice and settings. With align=True (the video's voice step) the recording is checked against
    the punctuation using the voice's own word times, retaken up to three times when a pause is wrong, and `before`/`after` carry the
    intonation across the scene joins. The result then has "problems" (what is still wrong in the best take), "takes", "spent" (characters
    used by all takes) and "words". Another provider (voice_cfg provider "openai-compatible") is used as set in Settings."""
    if voice_cfg.get("provider") == "openai-compatible":
        return cached_local(root, text, voice_cfg, api_key, opener)
    voice_id = voice_cfg.get("voice_id", "")
    model = voice_cfg.get("model") or DEFAULT_MODEL
    speed = float(voice_cfg.get("speed", 1.0) or 1.0)
    pace = voice_cfg.get("pace") or "normal"
    settings = {k: voice_cfg[k] for k in ("stability", "similarity_boost", "style") if isinstance(voice_cfg.get(k), (int, float))}
    spoken = prepare(text, model, pace)   # pauses first: the request size limit counts the break tags
    pieces = split_text(spoken)
    if align and len(pieces) == 1:
        return _aligned(root, text, spoken, voice_id, model, speed, pace, settings, api_key, opener, seed, before, after)
    key = hashlib.sha1(json.dumps([voice_id, model, speed, text, "speech-1", pace, settings] + ([seed] if seed is not None else []), ensure_ascii=False).encode()).hexdigest()
    out = Path(root) / "cache" / "voice" / f"{key}.mp3"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if len(pieces) <= 1:
            synthesize(spoken, voice_id, api_key, out, model, speed, opener, settings, prepared=True, seed=seed)
        else:
            parts = []
            try:
                for n, piece in enumerate(pieces):
                    p = out.with_name(f"{key}.part{n}.mp3")
                    synthesize(piece, voice_id, api_key, p, model, speed, opener, settings, prepared=True, seed=seed)
                    parts.append(p)
                tmp = out.with_name(f"{key}.joined.mp3")
                _concat(parts, tmp)
                tmp.replace(out)
            finally:
                for p in parts:
                    p.unlink(missing_ok=True)
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(prepare(text, model, pace))}


def _aligned(root, text, spoken, voice_id, model, speed, pace, settings, api_key, opener, seed, before, after):
    """One scene recorded with word times, checked against its punctuation, and retaken (up to three takes) while a pause is wrong."""
    key = hashlib.sha1(json.dumps([voice_id, model, speed, text, "speech-2-aligned", pace, settings, before[-300:], after[:300]]
                                  + ([seed] if seed is not None else []), ensure_ascii=False).encode()).hexdigest()
    out = Path(root) / "cache" / "voice" / f"{key}.mp3"
    side = out.with_suffix(".json")
    if out.exists() and side.exists():   # cached: nothing is spent
        d = json.loads(side.read_text())
        return {"path": str(out), "seconds": audio_seconds(out), "characters": len(spoken), "problems": d["problems"], "takes": d["takes"],
                "spent": 0, "words": d["words"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    best, spent = None, 0
    for n, take_seed in enumerate((seed,) + TAKE_SEEDS[1:]):
        tmp = out.with_name(f"{key}.take{n}.mp3")
        r = synthesize_timed(spoken, voice_id, api_key, tmp, model, speed, opener, settings, take_seed, before, after)
        spent += r["characters"]
        problems = pause_problems(r["words"], pace)
        if best is None or len(problems) < len(best[1]):
            if best:
                Path(best[0]["path"]).unlink(missing_ok=True)
            best = (r, problems, n + 1)
        else:
            tmp.unlink(missing_ok=True)
        if not problems:
            break
    r, problems, takes = best
    Path(r["path"]).replace(out)
    side.write_text(json.dumps({"words": r["words"], "problems": problems, "takes": takes}))
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(spoken), "problems": problems, "takes": takes, "spent": spent,
            "words": r["words"]}


# ---------- another voice tool: any server with an OpenAI-style speech endpoint (Kokoro-FastAPI, Chatterbox-TTS-Server, Orpheus-FastAPI, ...) ----------
def synthesize_local(text, cfg, out_path, api_key="", opener=None):
    """Read text with a voice server of your own (video.voice.provider "openai-compatible", base_url, model, voice_id). The server decides how
    punctuation sounds, so the text is only made speakable (numbers and symbols written as words)."""
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise VoiceError("set the address of your voice server in Settings (for example http://localhost:8880/v1)", "invalid")
    url = base + ("/audio/speech" if base.endswith("/v1") else "/v1/audio/speech")
    body = {"model": cfg.get("model") or "tts-1", "voice": cfg.get("voice_id") or "alloy", "input": speakable(text),
            "response_format": "mp3", "speed": float(cfg.get("speed") or 1.0)}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=600) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        raise VoiceError(f"the voice server refused the request (HTTP {e.code}): {_detail(e.read() if hasattr(e, 'read') else b'')}", "failed", e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VoiceError(f"could not reach the voice server at {base}: {getattr(e, 'reason', e)}", "network")
    if not audio:
        raise VoiceError("the voice server returned no audio", "failed")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(text)}


def cached_local(root, text, cfg, api_key="", opener=None):
    key = hashlib.sha1(json.dumps(["local", cfg.get("base_url"), cfg.get("model"), cfg.get("voice_id"), cfg.get("speed"), text],
                                  ensure_ascii=False).encode()).hexdigest()
    out = Path(root) / "cache" / "voice" / f"{key}.mp3"
    if not out.exists():
        synthesize_local(text, cfg, out, api_key, opener)
    return {"path": str(out), "seconds": audio_seconds(out), "characters": len(text), "problems": [], "takes": 1, "spent": len(text), "words": []}
