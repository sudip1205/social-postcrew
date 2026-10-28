"""Files the owner supplies for one video: their own script, voice and video.

They are kept per app and date (workspace/assets/<app>/<YYYY-MM-DD>/) and used by the next crew run for that date:
  script  a .txt/.md file parsed into scenes; the Editor still reviews it like any script
  voice   an audio file that replaces the ElevenLabs voice; its length sets the length of the video
  video   a finished video, used as is (its format and length are checked); the crew only writes the metadata

Script format (all optional except the narration): lines before the first blank line like `title: ...`, `description: ...`,
`tags: a, b, c`, `thumbnail: ...`; then scenes separated by blank lines. In a scene: `on-screen: ...` sets the big text,
lines starting with `- ` become on-screen points, `flow: Client > Load Balancer > Server` draws a diagram, a ``` fenced block
is code (``` python), everything else is the narration.
"""
import re
import shutil
from pathlib import Path

from .platforms import SHORT_MAX_S, WORDS_PER_SECOND

KINDS = {"script": ((".txt", ".md"), 200_000), "voice": ((".mp3", ".wav", ".m4a"), 100 * 2**20),
         "video": ((".mp4", ".mov"), 2**30)}
CHUNK = 1 << 20


class AssetError(ValueError):
    pass


def folder(ws, platform, day):
    day = day if isinstance(day, str) else day.isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(r"[a-z0-9-]+", platform):
        raise AssetError("bad app or date")
    return Path(ws.root) / "assets" / platform / day


def find(ws, platform, day):
    """{kind: path} of the files supplied for that day."""
    d = folder(ws, platform, day)
    out = {}
    for kind, (exts, _) in KINDS.items():
        hit = next((p for p in sorted(d.glob(f"{kind}.*")) if p.suffix.lower() in exts), None) if d.is_dir() else None
        if hit:
            out[kind] = hit
    return out


def _check_name(kind, name):
    if kind not in KINDS:
        raise AssetError(f"unknown kind {kind!r}: use script, voice or video")
    ext = Path(name or "").suffix.lower()
    if ext not in KINDS[kind][0]:
        raise AssetError(f"a {kind} must be one of {', '.join(KINDS[kind][0])}, not {ext or 'a file without an extension'}")
    return ext


def remove(ws, platform, day, kind):
    for p in folder(ws, platform, day).glob(f"{kind}.*"):
        p.unlink()


def save_stream(ws, platform, day, kind, name, rfile, length):
    """Store an uploaded file, replacing an earlier one of that kind. rfile.read(n) is read for exactly `length` bytes."""
    ext = _check_name(kind, name)
    limit = KINDS[kind][1]
    if length <= 0:
        raise AssetError("the file is empty")
    if length > limit:
        raise AssetError(f"the {kind} file is {length / 2**20:.0f} MB; the limit is {limit / 2**20:.0f} MB")
    d = folder(ws, platform, day)
    d.mkdir(parents=True, exist_ok=True)
    tmp, left = d / f".{kind}.part", length
    with open(tmp, "wb") as f:
        while left:
            chunk = rfile.read(min(CHUNK, left))
            if not chunk:
                tmp.unlink()
                raise AssetError("the upload ended early")
            f.write(chunk)
            left -= len(chunk)
    remove(ws, platform, day, kind)
    dest = d / f"{kind}{ext}"
    tmp.replace(dest)
    (d / f"{kind}.name").write_text(Path(name).name[:120])   # what the owner called it, for display
    return dest


def original_name(path):
    n = Path(path).with_suffix(".name")
    return n.read_text() if n.exists() else Path(path).name


# ---------- the script ----------
_META = re.compile(r"^(title|description|tags|thumbnail)\s*:\s*(.+)$", re.I)
_FLOW = re.compile(r"^\[?flow\s*:\s*(.+?)\]?$", re.I)
_ONSCREEN = re.compile(r"^\[?on[- ]screen\s*:\s*(.+?)\]?$", re.I)


def _shorten(sentence, n=12):
    words = sentence.split()
    return " ".join(words[:n]) + ("…" if len(words) > n else "")


def parse_script(text):
    """The owner's script file -> {"title","description","tags","thumbnail_text","scenes","text"} (missing metadata is
    left empty; the crew fills it in). Raises AssetError when there is no narration."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks, cur, fenced = [], [], False
    for ln in text.split("\n"):
        if ln.strip().startswith("```"):
            fenced = not fenced
        if not ln.strip() and not fenced:   # a blank line ends a scene, except inside a code fence
            if cur:
                blocks.append("\n".join(cur))
            cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    meta, scenes = {}, []
    for i, block in enumerate(blocks):
        lines = block.split("\n")
        if i == 0 and all(_META.match(ln) for ln in lines if ln.strip()) and lines:
            for ln in lines:
                m = _META.match(ln)
                if m:
                    meta[m.group(1).lower()] = m.group(2).strip()
            continue
        narration, items, code, lang, on_screen, in_code, nodes = [], [], [], "", "", False, []
        for ln in lines:
            if ln.strip().startswith("```"):
                in_code = not in_code
                if in_code:
                    lang = ln.strip()[3:].strip().lower()
                continue
            if in_code:
                code.append(ln)
            elif (m := _ONSCREEN.match(ln.strip())):
                on_screen = m.group(1).strip()
            elif (m := _FLOW.match(ln.strip())):
                nodes = [n.strip()[:18] for n in re.split(r"\s*(?:->|→|>)\s*", m.group(1)) if n.strip()][:6]
            elif ln.strip().startswith(("- ", "* ")):
                items.append(ln.strip()[2:].strip())
            elif ln.strip():
                narration.append(ln.strip())
        spoken = " ".join(narration).strip()
        if not spoken:
            raise AssetError(f"scene {len(scenes) + 1} has no narration: write what the voice says")
        layout = ("code" if code else "diagram" if len(nodes) >= 2 else "points" if items
                  else "title" if not scenes else "statement")
        first = re.split(r"(?<=[.!?])\s+", spoken)[0]
        scenes.append({"layout": layout, "narration": spoken, "on_screen": on_screen or (_shorten(first) if layout != "code" else ""),
                       "items": items[:5], "code": "\n".join(code), "nodes": nodes,
                       "edges": [f"{a} > {b}" for a, b in zip(nodes, nodes[1:])], "language": lang or ("python" if code else ""),
                       "seconds": round(len(spoken.split()) / WORDS_PER_SECOND, 1)})
    if not scenes:
        raise AssetError("the script has no scenes: separate scenes with a blank line")
    tags = [t.strip().lstrip("#") for t in re.split(r"[,\n]", meta.get("tags", "")) if t.strip()]
    return {"title": meta.get("title", ""), "description": meta.get("description", ""), "tags": tags,
            "thumbnail_text": meta.get("thumbnail", ""), "scenes": scenes,
            "text": "\n\n".join(s["narration"] for s in scenes)}


def read_script(path):
    return parse_script(Path(path).read_text(errors="replace"))


# ---------- what the Studio shows ----------
def describe(ws, platform, day, cfg):
    """{kind: {"name", "bytes", "checks": [...], ...}} for the Studio's upload dialog. cfg: the app's view of the config."""
    from . import platforms
    found, out = find(ws, platform, day), {}
    spec = platforms.video_spec(cfg)
    for kind, path in found.items():
        info = {"name": original_name(path), "bytes": path.stat().st_size, "checks": []}
        try:
            if kind == "script":
                s = read_script(path)
                words = len(s["text"].split())
                secs = round(words / WORDS_PER_SECOND)
                info.update(scenes=[{"narration": sc["narration"], "seconds": sc["seconds"]} for sc in s["scenes"]],
                            words=words, seconds=secs)
                info["checks"] = [{"label": "Scenes", "ok": len(s["scenes"]) >= 3, "detail": f"{len(s['scenes'])} scenes"},
                                  {"label": "Length", "ok": spec["format"] == "long" or secs <= SHORT_MAX_S + 3,
                                   "detail": f"about {secs} s ({words} words)"
                                             + ("" if spec["format"] == "long" or secs <= SHORT_MAX_S + 3 else ": too long for a Short")}]
            elif kind == "voice":
                from . import voice
                secs = voice.audio_seconds(path)
                info.update(seconds=round(secs, 1))
                info["checks"] = [{"label": "Duration", "ok": secs >= 5, "detail": f"{secs:.0f} s"},
                                  {"label": "Fits a Short", "ok": spec["format"] == "long" or secs <= SHORT_MAX_S + 1,
                                   "detail": "under 3 minutes" if secs <= SHORT_MAX_S + 1 else "longer than 3 minutes: use a long video"}]
            else:
                from .render import video as vid
                p = vid.probe(path)
                info.update(seconds=round(p["seconds"], 1), width=p["width"], height=p["height"])
                info["checks"] = vid.check_video(path, spec["format"])
                thumb = Path(ws.root) / "media" / f"asset-{platform}-{day}.png"
                thumb.parent.mkdir(exist_ok=True)
                if not thumb.exists() or thumb.stat().st_mtime < path.stat().st_mtime:
                    shutil.which("ffmpeg") and __import__("subprocess").run(
                        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(path), "-frames:v", "1", str(thumb)],
                        timeout=60)
                if thumb.exists():
                    info["thumbnail"] = f"/media/{thumb.name}"
        except Exception as e:   # a broken file is reported, not raised: the owner can replace it
            info["checks"].append({"label": "Readable", "ok": False, "detail": str(e)[:160]})
        out[kind] = info
    return out
