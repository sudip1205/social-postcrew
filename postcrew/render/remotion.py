"""Remotion renderer: the scenes become a props file, and the Remotion project (postcrew/remotion) draws them.

Python decides WHEN everything happens (scene lengths from the recorded voice, word times, the moment each box, arrow and step is
spoken); the React project only draws a frame for a given time. Remotion renders the picture and captions without sound; the voice
is laid under it afterwards with the same ffmpeg step the other renderers use.
"""
import json
import shutil
import subprocess
from pathlib import Path

from . import timeline, video
from .scenes import FORMATS, parse_edge, parse_pointer, split_node
from .video import FPS, VideoError

PROJECT = Path(__file__).resolve().parent.parent / "remotion"
CAPTION_WORDS = 4
TAIL_S = video.TAIL_S


def project_dir(cfg=None):
    """The Remotion project: the folder set in video.remotion.path, else the one shipped with Postcrew."""
    custom = str(((cfg or {}).get("remotion") or {}).get("path") or "").strip()
    return Path(custom).expanduser() if custom else PROJECT


def problems(cfg=None):
    """What stops Remotion from running here ([] when it can)."""
    out = []
    if not shutil.which("node") or not shutil.which("npx"):
        out.append("Node.js is not installed (https://nodejs.org, version 18 or newer)")
    if not (project_dir(cfg) / "package.json").exists():
        out.append(f"no Remotion project at {project_dir(cfg)}")
    return out


def install(root, log=None):
    """npm install once; the browser Remotion renders with is fetched on the first render."""
    root = Path(root)
    if (root / "node_modules" / "remotion").exists():
        return
    if log:
        log("installing Remotion (first run only, a minute or two)")
    r = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=root, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise VideoError("npm install failed: " + " | ".join((r.stderr or "").strip().splitlines()[-3:])[:500])


def _times(scene, length, audio):
    words, _measured = timeline.voice_words(scene.get("narration", ""), length, audio)
    return words


def _when(label, words, after=0.0):
    t = timeline.cue_time(label, words, after)
    return round(t if t is not None else after, 3)


def _captions(words):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= CAPTION_WORDS or w[0][-1:] in ".!?":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"text": " ".join(w[0] for w in c), "start": round(c[0][1], 3), "end": round(c[-1][2], 3)} for c in out]


def _diagram(scene, words, carry):
    """Boxes and arrows with the time each is said; what earlier consecutive diagram scenes drew is kept (from time 0)."""
    nodes = [split_node(n) for n in scene.get("nodes") or [] if split_node(n)[0]]
    for label, icon in carry["nodes"]:
        if label.lower() not in [n[0].lower() for n in nodes]:
            nodes.append((label, icon))
    names = [n[0] for n in nodes]
    boxes = [{"label": n[0][:18], "icon": n[1], "t": 0.0 if (n[0], n[1]) in carry["nodes"] else None} for n in nodes]
    edges, said = [], 0.0
    for e in scene.get("edges") or []:
        p = parse_edge(e, names)
        if not p:
            continue
        a, b, label = p
        t = max(_when(label, words, said) if label else said, _when(names[b], words, said))
        said = t
        edges.append({"from": a, "to": b, "label": label, "t": t})
        for i in (a, b):
            if boxes[i]["t"] is None:
                boxes[i]["t"] = min(_when(names[i], words), t)
    for i, bx in enumerate(boxes):
        if bx["t"] is None:
            bx["t"] = _when(names[i], words)
    carry["nodes"] = [(b["label"], b["icon"]) for b in boxes]
    return {"nodes": boxes, "edges": edges}


def _trace(scene, words):
    steps, said = [], 0.0
    for st in scene.get("steps") or []:
        t = _when(st.get("say"), words, said)
        said = t
        ptrs = [p for p in (parse_pointer(x) for x in st.get("pointers") or []) if p]
        steps.append({"t": t, "pointers": [{"name": n, "at": i} for n, i in ptrs], "active": st.get("active") or [],
                      "out": st.get("out") or [], "found": st.get("found") or [], "note": str(st.get("note") or ""),
                      "memo": [str(m) for m in st.get("memo") or []]})
    return {"cells": [str(c) for c in scene.get("cells") or []], "steps": steps}


def build_props(scenes, fmt, audio):
    """The JSON the Remotion project is rendered from, and the length of each scene in seconds."""
    if fmt not in FORMATS:
        raise VideoError(f"unknown format '{fmt}'")
    lengths = video._scene_lengths(scenes, audio)
    out, carry = [], {"nodes": []}
    for i, (sc, ln) in enumerate(zip(scenes, lengths)):
        a = audio[i] if isinstance(audio, (list, tuple)) else None
        words = _times(sc, ln, a)
        layout = sc.get("layout") or "statement"
        item = {"layout": layout, "title": str(sc.get("on_screen") or ""), "items": [str(x) for x in sc.get("items") or []],
                "code": str(sc.get("code") or ""), "language": str(sc.get("language") or ""),
                "seconds": round(ln, 3), "captions": _captions(words)}
        if layout in ("diagram", "flow"):
            item.update(_diagram(sc, words, carry if layout == "diagram" else {"nodes": []}))
        else:
            carry = {"nodes": []}
        if layout == "trace":
            item.update(_trace(sc, words))
        if layout in ("points", "code"):
            item["cues"] = [_when(x, words) for x in (item["items"] if layout == "points" else [])]
        out.append(item)
    w, h = FORMATS[fmt]
    return {"format": fmt, "width": w, "height": h, "fps": FPS, "scenes": out}, lengths


def _run(cmd, root, what, timeout=3600):
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise VideoError(f"{what}: {e}")
    if r.returncode != 0:
        tail = " | ".join([l for l in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if l.strip()][-5:])
        raise VideoError(f"{what} failed: {tail[:700]}")


def _fit(src, dst, fmt):
    """Re-encode a clip to the one format every clip is joined in (same size, 30 fps, H.264), so the join is seamless."""
    w, h = FORMATS[fmt]
    video._run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"scale={w}:{h},setsar=1,fps={FPS},format=yuv420p", "-an"]
               + video.ENC + [str(dst)], "Fitting a clip")


def thumbnail(script, out_path, cfg=None):
    """A 1280x720 thumbnail drawn by the Remotion project's Thumbnail composition."""
    bad = problems(cfg)
    if bad:
        raise VideoError("; ".join(bad))
    root = project_dir(cfg)
    install(root)
    props = Path(out_path).with_suffix(".props.json")
    props.write_text(json.dumps({"text": script.get("thumbnail_text") or script["title"], "title": script["title"]}))
    _run(["npx", "remotion", "still", "src/index.ts", "Thumbnail", str(out_path), f"--props={props}", "--log=error"],
         root, "Remotion thumbnail", timeout=600)
    props.unlink(missing_ok=True)
    return out_path
