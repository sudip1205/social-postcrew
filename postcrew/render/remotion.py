"""Remotion renderer: the scenes become a props file, and the Remotion project (postcrew/remotion) draws them.

Python decides WHEN everything happens (scene lengths from the recorded voice, word times, the moment each box, arrow and step is
spoken); the React project only draws a frame for a given time. Remotion renders the picture and captions without sound; the voice
is laid under it afterwards with the same ffmpeg step the other renderers use.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import looks, timeline, video
from .scenes import FORMATS, parse_edge, parse_pointer, split_node
from .video import FPS, VideoError

PROJECT = Path(__file__).resolve().parent.parent / "remotion"
CAPTION_WORDS = 6   # calm: fewer, longer captions
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
    """Word times of a scene. A scene with a lead (the closing line) starts speaking only after that silence."""
    lead = float(scene.get("lead_s") or 0)
    words, _measured = timeline.voice_words(scene.get("narration", ""), length - lead, audio)
    return [(w, s + lead, e + lead) for w, s, e in words]


def mark_closing(scenes, spec):
    """The last scene is the closing line (like, comment, share) when the app has one: it comes in after a pause."""
    if spec.get("outro") and scenes:
        scenes[-1]["closing"], scenes[-1]["lead_s"] = True, video.LEAD_S
    if len(scenes) > 1:
        scenes[0]["lead_s"] = video.OPEN_S
    return scenes


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


def _marked(text):
    """On-screen text with the word to highlight chosen by hand: "Welcome to *Dive*" -> ("Welcome to Dive", 2). Without a marker the
    longest word is highlighted (key is None)."""
    m = re.search(r"\*([^*]+)\*", text)
    if not m:
        return text, None
    clean = (text[:m.start()] + m.group(1) + text[m.end():]).strip()
    return clean, len(text[:m.start()].split())


def build_props(scenes, fmt, audio, look=None):
    """The JSON the Remotion project is rendered from, and the length of each scene in seconds."""
    if fmt not in FORMATS:
        raise VideoError(f"unknown format '{fmt}'")
    lengths = video._scene_lengths(scenes, audio)
    out, carry = [], {"nodes": []}
    for i, (sc, ln) in enumerate(zip(scenes, lengths)):
        a = audio[i] if isinstance(audio, (list, tuple)) else None
        words = _times(sc, ln, a)
        layout = sc.get("layout") or "statement"
        title, key = _marked(str(sc.get("on_screen") or ""))
        item = {"layout": layout, "title": title, "items": [str(x) for x in sc.get("items") or []],
                "code": str(sc.get("code") or ""), "language": str(sc.get("language") or ""),
                "seconds": round(ln, 3), "captions": _captions(words)}
        if key is not None:
            item["key"] = key
        if sc.get("closing"):   # "Like · Comment · Share": each part appears when the voice says it
            parts = [p for p in re.split(r"\s*[·•|,/]\s*|\s+and\s+", item["title"]) if p] or [item["title"]]
            item.update(closing=True, items=parts, cues=[_when(p, words, float(sc.get("lead_s") or 0)) for p in parts])
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
    return {"format": fmt, "width": w, "height": h, "fps": FPS, "theme": looks.theme(look, fmt), "scenes": out}, lengths


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


def illustration(script):
    """The picture of a thumbnail, drawn from the video's own content (there is no image model involved): its first diagram or request
    flow, else its first trace (the array and where the answer is), else its first code. None when it has none of these: the thumbnail is
    then type only. In a diagram, the box whose name shares the most words with the title is the one in focus."""
    scenes = script.get("scenes") or []
    words = lambda s: set(re.findall(r"[a-z0-9]+", str(s).lower()))
    title = words(f"{script.get('title', '')} {script.get('thumbnail_text', '')}")
    for sc in scenes:
        labels = [split_node(n)[0][:18] for n in sc.get("nodes") or [] if split_node(n)[0]]
        if sc.get("layout") in ("diagram", "flow") and len(labels) >= 2:
            labels = labels[:4]
            mid = (len(labels) - 1) / 2
            focus = max(range(len(labels)), key=lambda i: (len(title & words(labels[i])), -abs(i - mid)))
            return {"kind": "diagram", "nodes": labels, "focus": focus}
    for sc in scenes:
        cells = [str(c)[:5] for c in sc.get("cells") or []]
        if sc.get("layout") == "trace" and len(cells) >= 2:
            found = sorted({i for st in sc.get("steps") or [] for i in st.get("found") or [] if 0 <= i < min(len(cells), 6)})
            return {"kind": "trace", "cells": cells[:6], "found": found}
    for sc in scenes:
        lines = [l for l in str(sc.get("code") or "").splitlines() if l.strip()][:6]
        if sc.get("layout") == "code" and lines:
            return {"kind": "code", "lines": [l[:34] for l in lines]}
    return None


def thumbnail(script, out_path, cfg=None, look=None):
    """A 1280x720 thumbnail drawn by the Remotion project's Thumbnail composition: the thumbnail text, the topic (the title before its colon,
    so it does not repeat the headline) and a picture drawn from the video's own diagram, array or code."""
    bad = problems(cfg)
    if bad:
        raise VideoError("; ".join(bad))
    root = project_dir(cfg)
    install(root)
    props = Path(out_path).with_suffix(".props.json")
    props.write_text(json.dumps({"text": script.get("thumbnail_text") or script["title"], "title": script["title"].split(":")[0].strip(), "theme": looks.theme(look),
                                 "illustration": illustration(script)}))
    _run(["npx", "remotion", "still", "src/index.ts", "Thumbnail", str(out_path), f"--props={props}", "--log=error"],
         root, "Remotion thumbnail", timeout=600)
    props.unlink(missing_ok=True)
    return out_path


def channel_art(out_path, name, tagline, topics, look="ink", guides=False, cfg=None):
    """The channel cover (2560x1440): the name, a line on what the channel is, the topics. The text sits in the centre that a phone shows
    (1546x423); a quiet diagram motif fills the wide area. guides=True draws the safe areas on it, for checking only."""
    bad = problems(cfg)
    if bad:
        raise VideoError("; ".join(bad))
    root = project_dir(cfg)
    install(root)
    props = Path(out_path).with_suffix(".props.json")
    props.write_text(json.dumps({"name": name, "tagline": tagline, "topics": list(topics), "theme": looks.theme(look), "guides": bool(guides)}))
    _run(["npx", "remotion", "still", "src/index.ts", "ChannelArt", str(out_path), f"--props={props}", "--log=error"], root, "Remotion channel art", timeout=600)
    props.unlink(missing_ok=True)
    return out_path
