"""HyperFrames renderer (HeyGen: write HTML, render video): the kinetic-text scenes of a video.

Remotion draws the data scenes (diagrams, flows, traces, code, lists); HyperFrames draws the scenes that are only words, the
opening card and the big statements, as HTML with a GSAP timeline. `engine_for` says which engine draws a scene; the agents in
agents/frames.py run each engine and the Video Composer joins the clips. Each scene is its own tiny project: index.html next to a
copy of GSAP.
"""
import html
import json
import shutil
import subprocess
from pathlib import Path

from . import looks
from .video import VideoError

PROJECT = Path(__file__).resolve().parent.parent / "hyperframes"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
LAYOUTS = ("title", "statement")   # the scenes HyperFrames draws


def engine_for(scene):
    """Which engine draws a scene: 'hyperframes' for words on their own, 'remotion' for everything with data."""
    return "hyperframes" if scene.get("layout") in LAYOUTS else "remotion"


def available():
    """Why HyperFrames cannot run here, or '' when it can."""
    if not shutil.which("node") or not shutil.which("npx"):
        return "Node.js 22 or newer is not installed"
    if not shutil.which("ffmpeg"):
        return "ffmpeg is not installed"
    return ""


def install(root=PROJECT):
    root = Path(root)
    if (root / "node_modules" / "gsap").exists() and (root / "node_modules" / ".bin" / "hyperframes").exists():
        return
    r = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=root, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise VideoError("npm install (HyperFrames) failed: " + " | ".join((r.stderr or "").strip().splitlines()[-3:])[:500])


def _key_word(words):
    """The word that carries the idea: the longest one (the last, when tied). Shown in the accent colour."""
    return max(range(len(words)), key=lambda i: (sum(ch.isalnum() for ch in words[i]), i)) if words else -1


FONTS = (("Inter", "Inter-Regular.ttf", 400), ("Inter", "Inter-SemiBold.ttf", 600), ("Inter", "Inter-Bold.ttf", 700))


def scene_html(scene, width, height, theme=None):
    """The composition for one scene, in the look chosen in Settings (render/looks.py) and the rules of remotion/STYLE.md: a flat page,
    type that rises out of a mask word by word, a thin rule that draws itself, the key word in the highlight colour, a very slow
    push-in, plain captions. The closing scene ("Like, Comment, Share") shows each part when the voice says it."""
    th = theme or looks.theme()
    short = height > width
    seconds = max(0.5, float(scene["seconds"]))
    card, closing = scene.get("layout") == "title", bool(scene.get("closing"))
    title = scene.get("title") or ""
    words = title.split()
    key = _key_word(words)
    size = (132 if card else 98) if short else (112 if card else 86)
    mask = lambda w, cls="": f'<span class="m{cls}"><span class="w">{html.escape(w)}</span></span>'
    if closing:
        parts = scene.get("items") or [title]
        body = "".join(f'<div class="hr"></div><div class="row">{mask(p, " last" if i == len(parts) - 1 else "")}</div>' for i, p in enumerate(parts))
        cues = json.dumps([round(float(c), 3) for c in (scene.get("cues") or [])] or [0.8 + 0.8 * i for i in range(len(parts))])
    else:
        body = '<h1>' + "".join(mask(w, " key" if i == key else "") for i, w in enumerate(words)) + "</h1>"
        cues = "[]"
    caps = scene.get("captions") or []
    cap_html = "".join(f'<div class="cap" id="c{i}">{html.escape(c["text"])}</div>' for i, c in enumerate(caps))
    cap_js = json.dumps([[round(c["start"], 3), round(max(c["end"], c["start"] + 0.2), 3)] for c in caps])
    inset = "170px 96px 400px" if short else "90px 150px 190px"
    side = 96 if short else 150
    faces = "".join(f"@font-face {{ font-family: '{f}'; src: url('{file}'); font-weight: {w}; }}\n" for f, file, w in FONTS)
    rule_w, rule_h = (150 if card else 110, 9 if card else 6) if not closing else (150 if short else 130, 7)
    rows_size = 124 if short else 96
    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width={width}, height={height}">
<title>Postcrew scene</title>
<script src="gsap.min.js"></script>
<style>
{faces}body {{ margin: 0; background: {th['bg']}; color: {th['text']}; font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; }}
#root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {th['bg']}; }}
.stage {{ position: absolute; inset: {inset}; display: flex; flex-direction: column; justify-content: center; transform-origin: left center; }}
.rule {{ width: {rule_w}px; height: {rule_h}px; background: {th['accent']}; margin-bottom: {56 if closing else 44}px; transform-origin: left center; }}
h1 {{ margin: 0; font-size: {size}px; font-weight: 700; line-height: 1.1; letter-spacing: -0.028em; }}
.m {{ display: inline-block; overflow: hidden; vertical-align: top; padding-bottom: .16em; margin-bottom: -.16em; margin-right: .26em; }}
.w {{ display: inline-block; }}
.key .w {{ color: {th['highlight']}; }}
.row {{ padding: {'30px' if short else '20px'} 0; font-size: {rows_size}px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.05; }}
.row .m {{ margin-right: 0; }}
.hr {{ height: 2px; background: {th['rule']}; transform-origin: left center; }}
.row .last .w {{ color: {th['highlight']}; }}
.capbox {{ position: absolute; left: {side}px; right: {side}px; bottom: {200 if short else 62}px; text-align: center; height: {190 if short else 110}px; }}
.cap {{ position: absolute; left: 0; right: 0; bottom: 0; opacity: 0; font-size: {52 if short else 40}px; font-weight: 600; line-height: 1.3; letter-spacing: -0.01em; }}
</style></head><body>
<div id="root" data-composition-id="scene" data-start="0" data-width="{width}" data-height="{height}" data-duration="{seconds:.3f}">
  <div class="stage" id="stage"><div class="rule" id="rule"></div>{body}</div>
  <div class="capbox">{cap_html}</div>
</div>
<script>
const D = {seconds:.3f}, EASE = "expo.out", tl = gsap.timeline({{ paused: true }});
tl.from("#stage", {{ opacity: 0, duration: 0.7, ease: "power2.out" }}, 0);
tl.fromTo("#stage", {{ scale: 1 }}, {{ scale: 1.014, duration: D, ease: "none" }}, 0);
tl.from("#rule", {{ scaleX: 0, duration: {1.4 if closing else 1.1}, ease: EASE }}, {0.15 if closing else 0.1});
{"const cues = " + cues + "; document.querySelectorAll('.row .w').forEach((w, i) => { const at = cues[i] ?? 0.8 + i * 0.8; tl.from(document.querySelectorAll('.hr')[i], { scaleX: 0, duration: 1.0, ease: EASE }, Math.max(0, at - 0.1)); tl.from(w, { yPercent: 108, duration: 1.1, ease: EASE }, at); });" if closing
 else "tl.from('.w', { yPercent: 108, duration: 1.0, ease: EASE, stagger: 0.14 }, 0.35);"}
const caps = {cap_js};
caps.forEach((t, i) => {{ tl.fromTo("#c" + i, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, t[0]); tl.to("#c" + i, {{ opacity: 0, duration: 0.1 }}, Math.max(t[0] + 0.3, t[1] - 0.12)); }});
window.__timelines["scene"] = tl;
</script></body></html>
"""


def render_scene(scene, out_path, width, height, workdir, root=PROJECT, theme=None):
    """Render one scene to a silent mp4 (30 fps)."""
    why = available()
    if why:
        raise VideoError(why)
    install(root)
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "index.html").write_text(scene_html(scene, width, height, theme))
    for _family, file, _weight in FONTS:   # the same fonts as the Remotion scenes
        shutil.copy(FONT_DIR / file, wd / file)
    shutil.copy(Path(root) / "node_modules" / "gsap" / "dist" / "gsap.min.js", wd / "gsap.min.js")
    exe = Path(root) / "node_modules" / ".bin" / "hyperframes"
    r = subprocess.run([str(exe), "render", str(wd), "-o", str(out_path), "--fps", "30", "--quality", "looks", "--quiet"],
                       capture_output=True, text=True, errors="replace", timeout=900)
    if r.returncode != 0 or not Path(out_path).exists():
        tail = " | ".join([l for l in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if l.strip()][-5:])
        raise VideoError(f"HyperFrames render failed: {tail[:700]}")
    return out_path
