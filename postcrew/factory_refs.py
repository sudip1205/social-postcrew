"""Reference videos for the Factory: a video you like (uploaded, or a link), with your comment on what to learn from it.

Each one lives next to the Shorts factory, in ~/Youtube/references/<id>/ (video, frames/, ref.json), so the factory itself is not
changed. When it is added, ffmpeg takes frames from it (Claude cannot watch a video, but it can look at pictures). "Teach the skill"
sends the chat a message pointing at those frames and your comment; Claude writes what it learned into the skill, as CLAUDE.md asks.
"""
import json
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .agents.shorts import factory_dir

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
LIMIT = 600 * 2**20
CHUNK = 1 << 20
FRAMES = 12
ID = re.compile(r"[a-z0-9]{8}")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cfg(ws):
    from . import platforms
    return platforms.view(ws.config(), "youtube")


def folder(ws):
    return factory_dir(_cfg(ws)).parent / "references"


def _dir(ws, rid):
    if not ID.fullmatch(str(rid or "")):
        raise ValueError("unknown reference")
    d = folder(ws) / rid
    if not (d / "ref.json").exists():
        raise ValueError("that reference is gone")
    return d


def _read(d):
    return json.loads((d / "ref.json").read_text())


def _write(d, ref):
    (d / "ref.json").write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n")


def _video(d):
    return next((f for f in sorted(d.iterdir()) if f.stem == "video" and f.suffix in VIDEO_EXT), None)


def _row(d):
    ref = _read(d)
    frames = sorted((d / "frames").glob("*.jpg")) if (d / "frames").exists() else []
    v = _video(d)
    return dict(ref, frames=len(frames), video=f"{d.name}/{v.name}" if v else None,
                thumb=f"{d.name}/frames/{frames[len(frames) // 3].name}" if frames else None)


def listing(ws):
    root = folder(ws)
    if not root.exists():
        return []
    rows = []
    for d in root.iterdir():
        if d.is_dir() and ID.fullmatch(d.name) and (d / "ref.json").exists():
            try:
                rows.append(_row(d))
            except (OSError, ValueError):
                continue
    return sorted(rows, key=lambda r: r.get("added", ""), reverse=True)


def _new(ws, name, url, comment):
    rid = secrets.token_hex(4)
    d = folder(ws) / rid
    d.mkdir(parents=True)
    _write(d, {"id": rid, "name": str(name or "")[:120], "url": url or "", "comment": str(comment or "").strip()[:4000],
               "added": _now(), "learned": None, "seconds": 0})
    return d


def _finish(d):
    """Measure the video and take FRAMES pictures spread over it (frames/01.jpg ...), for Claude to look at."""
    v = _video(d)
    if not v:
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("no video came through")
    secs = 0.0
    try:
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)],
                                    capture_output=True, text=True, timeout=60).stdout.strip())
    except (ValueError, OSError):
        pass
    if secs <= 0:
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("that file is not a video ffmpeg can read")
    (d / "frames").mkdir(exist_ok=True)
    for i in range(FRAMES):
        t = secs * (i + 0.5) / FRAMES
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1", "-vf", "scale=-2:720",
                        str(d / "frames" / f"{i + 1:02d}.jpg")], capture_output=True, timeout=120)
    ref = _read(d)
    ref["seconds"] = round(secs, 1)
    _write(d, ref)
    return _row(d)


def add_upload(ws, name, comment, rfile, length):
    """Store an uploaded video (the request body, `length` bytes)."""
    ext = Path(str(name or "")).suffix.lower()
    if ext not in VIDEO_EXT:
        raise ValueError("pick a video file (" + ", ".join(VIDEO_EXT) + ")")
    if length <= 0:
        raise ValueError("the file is empty")
    if length > LIMIT:
        raise ValueError(f"the video is {length / 2**20:.0f} MB; the limit is {LIMIT // 2**20} MB")
    d = _new(ws, Path(name).name, "", comment)
    left = length
    with open(d / f"video{ext}", "wb") as f:
        while left:
            chunk = rfile.read(min(CHUNK, left))
            if not chunk:
                shutil.rmtree(d, ignore_errors=True)
                raise ValueError("the upload ended early")
            f.write(chunk)
            left -= len(chunk)
    return {"reference": _finish(d), "references": listing(ws)}


def _ytdlp():
    found = shutil.which("yt-dlp") or next((str(p) for p in (Path.home() / ".local/bin/yt-dlp",) if p.exists()), None)
    if not found:
        raise ValueError("yt-dlp is not installed on this computer, so links cannot be fetched: upload the video file instead")
    return found


def add_link(ws, url, comment):
    """Fetch a video from a link (YouTube and others) with yt-dlp, at 720p or below."""
    url = str(url or "").strip()
    if not re.match(r"^https?://[^\s]+$", url):
        raise ValueError("paste a link that starts with https://")
    binary = _ytdlp()
    d = _new(ws, url, url, comment)
    r = subprocess.run([binary, "--no-playlist", "--no-progress", "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b",
                        "--merge-output-format", "mp4", "--max-filesize", str(LIMIT), "--print", "after_move:title",
                        "-o", str(d / "video.%(ext)s"), url], capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not _video(d):
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("could not fetch that video: " + (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1][:300])
    title = (r.stdout.strip().splitlines() or [""])[-1]
    if title:
        ref = _read(d)
        ref["name"] = title[:120]
        _write(d, ref)
    return {"reference": _finish(d), "references": listing(ws)}


def comment(ws, rid, text):
    d = _dir(ws, rid)
    ref = _read(d)
    ref["comment"] = str(text or "").strip()[:4000]
    _write(d, ref)
    return {"references": listing(ws)}


def delete(ws, rid):
    shutil.rmtree(_dir(ws, rid))
    return {"references": listing(ws)}


def _part(d, n=None):
    """One reference's lines for a lesson: its name, length, your comment, its frames and the video file."""
    ref = _read(d)
    frames = sorted((d / "frames").glob("*.jpg"))
    head = f"Video {n}: " if n else "Video: "
    lines = [head + (ref.get("name") or d.name) + (f" ({ref['url']})" if ref.get("url") and ref["url"] != ref.get("name") else "")
             + f", {ref.get('seconds', 0)} s long. File: {_video(d)}",
             "What I want learned from it: " + (ref.get("comment") or "(no comment: find what makes it work)"),
             f"Its {len(frames)} frames, evenly from start to end:"] + [f"- {f}" for f in frames]
    return lines


def lesson(ws, ids, note=""):
    """The chat message that asks Claude to learn from one or more references and write it into the skill. With several, it looks
    for the pattern they share (and what your comments ask for), not one video's quirks."""
    ids = [ids] if isinstance(ids, str) else list(dict.fromkeys(ids or []))
    if not ids:
        raise ValueError("pick at least one reference video")
    if len(ids) > 10:
        raise ValueError("pick 10 reference videos at most at once")
    dirs = [_dir(ws, i) for i in ids]
    if len(dirs) == 1 and not _read(dirs[0]).get("comment"):
        raise ValueError("write what to learn from this video first (your comment)")
    many = len(dirs) > 1
    lines = [(f"Study these {len(dirs)} reference videos I like together, find the pattern they share, and update the skill "
              "(explainer-short-style) so future Shorts follow it." if many else
              "Learn from a reference video I like and update the skill (explainer-short-style) so future Shorts do this too."),
             "You cannot watch videos, so look at the frames listed for each one (open each with Read). Use ffprobe, or take more "
             "frames with ffmpeg into a video's frames folder, if you need a closer look.", ""]
    if str(note or "").strip():
        lines += ["What I want you to look for across them: " + str(note).strip()[:4000], ""]
    for n, d in enumerate(dirs, 1):
        lines += _part(d, n if many else None) + [""]
    if many:
        lines += ["Compare them on: hook and first 2 seconds, pacing and cut rhythm, text and caption size, position and animation, "
                  "colour and background, layout of diagrams, motion, and how they end. Write into the skill only what most of them share "
                  "(or what my comments ask for), as concrete rules with numbers where you can. Then list the pattern you found, one line "
                  "per rule with which videos show it, and say which skill files changed. Do not make a video now."]
    else:
        lines += ["Then write the lesson into the skill as a concrete rule (what to do, with numbers where you can: sizes, positions, "
                  "timing, colours, pacing), say which skill files changed, and do not make a video now."]
    return {"text": "\n".join(lines), "ids": ids}


def mark_learned(ws, ids):
    for rid in [ids] if isinstance(ids, str) else ids:
        d = _dir(ws, rid)
        ref = _read(d)
        ref["learned"] = _now()
        _write(d, ref)
