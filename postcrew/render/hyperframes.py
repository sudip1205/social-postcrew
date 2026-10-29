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

from .video import VideoError

PROJECT = Path(__file__).resolve().parent.parent / "hyperframes"
LAYOUTS = ("title", "statement")   # the scenes HyperFrames draws
COLORS = {"bg": "#0b0c12", "text": "#f1f2f8", "violet": "#8b7bff", "border": "#2a2c3a"}


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
    """The word that carries the idea: the longest one (the last, when tied)."""
    return max(range(len(words)), key=lambda i: (sum(ch.isalnum() for ch in words[i]), i)) if words else -1


def scene_html(scene, width, height):
    """The composition for one scene. Drifting colour fields and a faint grid sit behind; the words rise out of a blur one by
    one; the key word turns colour and is underlined (opening card) or highlighted (statement); captions follow the voice."""
    short = height > width
    seconds = max(0.5, float(scene["seconds"]))
    words = (scene.get("title") or "").split()
    key = _key_word(words)
    card = scene.get("layout") == "title"
    size = (124 if card else 96) if short else (112 if card else 88)
    spans = " ".join(f'<span class="w{" k" if i == key else ""}" id="w{i}"><i>{html.escape(w)}</i></span>' for i, w in enumerate(words))
    caps = scene.get("captions") or []
    cap_html = "".join(f'<div class="cap" id="c{i}"><span>{html.escape(c["text"])}</span></div>' for i, c in enumerate(caps))
    cap_js = json.dumps([[round(c["start"], 3), round(max(c["end"], c["start"] + 0.2), 3)] for c in caps])
    c = COLORS
    inset = "140px 64px 360px" if short else "70px 96px 170px"
    underline = "tl.to('.k', { '--u': 1, duration: 0.7, ease: 'power2.out' }, 0.9);"
    sweep = ("document.querySelectorAll('.k').forEach(k => { const m = document.createElement('span'); m.className = 'mk'; k.prepend(m); });"
             " tl.to('.mk', { scaleX: 1, duration: 0.6, ease: 'power2.out' }, 0.9); tl.from('#bar', { scaleY: 0, duration: 0.6, ease: 'power3.out' }, 0.05);")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width={width}, height={height}">
<title>Postcrew scene</title>
<script src="gsap.min.js"></script>
<style>
body {{ margin: 0; background: {c['bg']}; color: {c['text']}; font-family: system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; }}
#root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {c['bg']}; }}
.orb {{ position: absolute; border-radius: 50%; filter: blur({90 if short else 80}px); opacity: .55; }}
#o1 {{ width: 62%; height: {'34%' if short else '70%'}; left: -12%; top: 4%; background: #4b3fd6; }}
#o2 {{ width: 50%; height: {'28%' if short else '60%'}; right: -10%; top: 38%; background: #0f8f86; opacity: .32; }}
#o3 {{ width: 46%; height: {'24%' if short else '52%'}; left: 22%; bottom: -6%; background: #a23b8f; opacity: .28; }}
.grid {{ position: absolute; inset: 0; opacity: .07; background-image: linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px); background-size: 90px 90px; }}
.vig {{ position: absolute; inset: 0; background: radial-gradient(ellipse at center, transparent 45%, rgba(5,6,10,.72) 100%); }}
.ring {{ position: absolute; left: 50%; top: {'40%' if short else '48%'}; width: 30%; aspect-ratio: 1; margin: -15% 0 0 -15%; border: 3px solid {c['violet']}; border-radius: 50%; opacity: 0; }}
.stage {{ position: absolute; inset: {inset}; display: flex; align-items: center; justify-content: {'center' if card else 'flex-start'}; text-align: {'center' if card else 'left'}; }}
.bar {{ width: 14px; align-self: center; height: 46%; margin-right: 44px; border-radius: 7px; background: linear-gradient({c['violet']}, #3ddc97); transform-origin: top; }}
h1 {{ margin: 0; font-size: {size}px; font-weight: 800; line-height: 1.1; letter-spacing: -1px; text-wrap: balance; }}
.w {{ display: inline-block; position: relative; margin: 0 .12em; }}
.w i {{ display: inline-block; font-style: normal; }}
.k i {{ background: linear-gradient(90deg, #b7acff, #3ddc97); -webkit-background-clip: text; background-clip: text; color: transparent; }}
.k::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: -4px; height: {'14px' if card else '0'}; border-radius: 7px; background: {c['violet']}; transform: scaleX(var(--u, 0)); transform-origin: left; }}
.mk {{ position: absolute; left: -8px; right: -8px; top: 6%; bottom: 6%; z-index: -1; background: rgba(139,123,255,.42); border-radius: 10px; transform: scaleX(0); transform-origin: left; }}
.capbox {{ position: absolute; left: 64px; right: 64px; bottom: {190 if short else 56}px; text-align: center; height: {150 if short else 80}px; }}
.cap {{ position: absolute; left: 0; right: 0; bottom: 0; opacity: 0; }}
.cap span {{ display: inline-block; background: rgba(11,12,18,.82); border: 2px solid {c['border']}; border-radius: 20px; padding: 14px 30px; font-size: {56 if short else 44}px; font-weight: 800; line-height: 1.2; }}
</style></head><body>
<div id="root" data-composition-id="scene" data-start="0" data-width="{width}" data-height="{height}" data-duration="{seconds:.3f}">
  <div class="orb" id="o1"></div><div class="orb" id="o2"></div><div class="orb" id="o3"></div>
  <div class="grid" id="grid"></div><div class="ring" id="r1"></div><div class="ring" id="r2"></div><div class="vig"></div>
  <div class="stage">{'' if card else '<div class="bar" id="bar"></div>'}<h1 id="title">{spans}</h1></div>
  <div class="capbox">{cap_html}</div>
</div>
<script>
const D = {seconds:.3f}, tl = gsap.timeline({{ paused: true }});
tl.to("#o1", {{ x: 160, y: 90, duration: D, ease: "sine.inOut" }}, 0);
tl.to("#o2", {{ x: -140, y: -110, duration: D, ease: "sine.inOut" }}, 0);
tl.to("#o3", {{ x: 120, y: -70, duration: D, ease: "sine.inOut" }}, 0);
tl.fromTo("#grid", {{ y: 0 }}, {{ y: 90, duration: D, ease: "none" }}, 0);
tl.fromTo(".ring", {{ scale: .5, opacity: .55 }}, {{ scale: 1.7, opacity: 0, duration: 1.4, stagger: 0.35, ease: "power2.out" }}, 0.15);
tl.from(".w i", {{ y: 90, opacity: 0, rotateX: -60, filter: "blur(18px)", duration: 0.7, stagger: 0.1, ease: "power3.out" }}, 0.15);
{underline if card else sweep}
tl.fromTo("#title", {{ scale: 1 }}, {{ scale: 1.05, duration: D, ease: "none" }}, 0);
const caps = {cap_js};
caps.forEach((t, i) => {{ tl.fromTo("#c" + i, {{ opacity: 0, y: 14 }}, {{ opacity: 1, y: 0, duration: 0.14 }}, t[0]); tl.to("#c" + i, {{ opacity: 0, duration: 0.1 }}, t[1]); }});
window.__timelines["scene"] = tl;
</script></body></html>
"""


def render_scene(scene, out_path, width, height, workdir, root=PROJECT):
    """Render one scene to a silent mp4 (30 fps)."""
    why = available()
    if why:
        raise VideoError(why)
    install(root)
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "index.html").write_text(scene_html(scene, width, height))
    shutil.copy(Path(root) / "node_modules" / "gsap" / "dist" / "gsap.min.js", wd / "gsap.min.js")
    exe = Path(root) / "node_modules" / ".bin" / "hyperframes"
    r = subprocess.run([str(exe), "render", str(wd), "-o", str(out_path), "--fps", "30", "--quality", "looks", "--quiet"],
                       capture_output=True, text=True, errors="replace", timeout=900)
    if r.returncode != 0 or not Path(out_path).exists():
        tail = " | ".join([l for l in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if l.strip()][-5:])
        raise VideoError(f"HyperFrames render failed: {tail[:700]}")
    return out_path
