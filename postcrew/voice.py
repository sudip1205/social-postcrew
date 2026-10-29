"""ElevenLabs text-to-speech: voices, key check, synthesis with a content-addressed mp3 cache.

Standard library only. ffmpeg/ffprobe are used (when present) to join long narrations and to measure length.
"""
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
COMMA_S = 0.1     # any break tag makes ElevenLabs stop for about half a second (measured: 0.05 s and 0.12 s gave the same gap)


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
    budget = [MAX_BREAKS]

    def tag(sec, after=""):
        if budget[0] <= 0:
            return after + " "
        budget[0] -= 1
        return f'{after} <break time="{sec}s" /> '
    text = re.sub(r"\s*(?:\.\.\.|\u2026)\s*", lambda m: tag(beat_s), text)
    text = re.sub(r"([.!?])\s+(?=[A-Z0-9\"'(])", lambda m: tag(sentence_s, m.group(1)), text)
    # a comma that ends a clause ("In Python, a list works", "The closer needs round, but...") must stop the voice; the voice sometimes runs it
    # on (a gap of 0.0 s was measured). Items of a list ("curly, square, round") keep the voice's own short breath.
    def comma(m):
        clause = re.split(r"[.,;:!?>]", text[:m.start()])[-1].split()
        return tag(COMMA_S, m.group(1)) if len(clause) >= 2 else m.group(0)
    text = re.sub(r"([,;:])\s+(?=\w)", comma, text)
    return re.sub(r"\s+", " ", text).strip()


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


def cached_synthesize(root, text, voice_cfg, api_key, opener=None, seed=None):
    voice_id = voice_cfg.get("voice_id", "")
    model = voice_cfg.get("model") or DEFAULT_MODEL
    speed = float(voice_cfg.get("speed", 1.0) or 1.0)
    pace = voice_cfg.get("pace") or "normal"
    settings = {k: voice_cfg[k] for k in ("stability", "similarity_boost", "style") if isinstance(voice_cfg.get(k), (int, float))}
    key = hashlib.sha1(json.dumps([voice_id, model, speed, text, "speech-1", pace, settings] + ([seed] if seed is not None else []), ensure_ascii=False).encode()).hexdigest()
    out = Path(root) / "cache" / "voice" / f"{key}.mp3"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        spoken = prepare(text, model, pace)   # pauses first: the request size limit counts the break tags
        pieces = split_text(spoken)
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
