"""YouTube Shorts thumbnails (owner, 2026-11-25: "create me thumbnail picture for each of the videos. Make it attractive so that it
catches people. Also highlight the topic it discussed with proper graphics.").

A 1080x1920 picture: a topic tag, a huge 2-6 word hook with the key words on a bright marker, one big graphic of the topic in the
middle (versus, flow, big number, bars, grid, code, or a hero icon), an optional sticker, and the channel name. The important part sits
in the centre square, because YouTube also shows Shorts thumbnails cropped. Drawn as HTML by headless Chrome, like render/card.py.
"""
import html
import re
import shutil
import tempfile
from pathlib import Path

from .card import ICONS, MONO, STATIC, _run, chrome

W, H = 1080, 1920
ACCENTS = {   # background from, to; marker; glow
    "fire": ("#1A0B2E", "#3B0A1E", "#FFD23F", "255,90,60"),
    "ocean": ("#04122B", "#08324F", "#4DF5C8", "40,160,255"),
    "violet": ("#120A2E", "#2E0F4F", "#FFD23F", "150,90,255"),
    "lime": ("#06190F", "#0E3A22", "#C6FF3D", "60,220,120"),
    "sun": ("#1F1300", "#3D1F00", "#FFE14D", "255,170,40"),
    "rose": ("#22061A", "#45102E", "#FF9EC8", "255,70,140"),
}
e = lambda s: html.escape(str(s or ""), quote=True)


def rich(s):
    out, last, s = [], 0, str(s or "")
    for m in re.finditer(r"\[\[(.+?)\]\]", s):
        out += [e(s[last:m.start()]), f'<mark>{e(m.group(1))}</mark>']
        last = m.end()
    return "".join(out + [e(s[last:])])


def ic(name, fallback="bolt"):
    n = str(name or "")
    return f'<span class="ic">{n if n in ICONS or n in EXTRA else fallback}</span>'


EXTRA = ("sort", "swap_vert", "grid_on", "route", "stacks", "data_object", "functions", "casino", "lock_open", "vpn_key",
         "devices", "smartphone", "computer", "router", "cable", "videocam", "movie", "event_seat", "music_note", "queue_music",
         "water_drop", "directions_car", "sensors", "my_location", "fingerprint", "password", "qr_code_2", "pin", "chat",
         "cloud_upload", "cloud_sync", "folder", "content_copy", "difference", "filter_alt", "ring_volume", "donut_large",
         "radio_button_checked", "alt_route", "arrow_forward", "edit_note", "image", "mail", "radar", "scatter_plot", "view_column", "electric_bolt", "power_off", "restart_alt", "stairs", "calculate", "rule", "category",
         "linear_scale", "join", "table", "dataset", "speed", "shopping_cart", "credit_card", "contactless", "wallet",
         "sports_esports", "public", "language", "http", "send", "inbox", "visibility", "hourglass_empty", "check", "close")


# ---------- the graphics ----------
def g_vs(g):
    side = lambda s, k: (f'<div class="vs-side {k}{" win" if s.get("win") else ""}"><div class="tile">{ic(s.get("icon"), "bolt")}</div>'
                         f'<b>{e(s.get("label"))}</b>' + (f'<small>{e(s.get("note"))}</small>' if s.get("note") else "") + "</div>")
    return f'<div class="vs">{side(g.get("left") or {}, "l")}<div class="vsb">VS</div>{side(g.get("right") or {}, "r")}</div>'


def g_flow(g):
    nodes = (g.get("nodes") or [])[:4]
    bad = g.get("bad")
    out = []
    for i, n in enumerate(nodes):
        cls = "bad" if bad == i else "good" if g.get("good") == i else ""
        out.append(f'<div class="node {cls}"><div class="tile">{ic(n.get("icon"), "dns")}'
                   + ('<i class="x">close</i>' if bad == i else '<i class="ok">check</i>' if g.get("good") == i else "")
                   + f'</div><b>{e(n.get("label"))}</b></div>')
        if i < len(nodes) - 1:
            out.append(f'<div class="arr"><span>{e((nodes[i + 1].get("via") or ""))}</span></div>')
    return f'<div class="flow n{len(nodes)}">{"".join(out)}</div>'


def g_big(g):
    return (f'<div class="big">{ic(g.get("icon"), "bolt") if g.get("icon") else ""}<div class="num">{e(g.get("value"))}</div>'
            f'<div class="unit">{e(g.get("label"))}</div></div>')


def g_bars(g):
    vals = (g.get("values") or [])[:12]
    top = max(vals + [1])
    hi = set(g.get("highlight") or [])
    water = g.get("water") or []
    bars = "".join(f'<div class="bar{" hi" if i in hi else ""}" style="height:{max(4, 100 * v / top):.0f}%">'
                   + (f'<i class="water" style="height:{100 * water[i] / max(v, 1e-9):.0f}%;top:-{100 * water[i] / max(v, 1e-9):.0f}%"></i>' if i < len(water) and water[i] else "")
                   + "</div>" for i, v in enumerate(vals))
    return f'<div class="bars">{bars}</div>' + (f'<div class="cap">{e(g.get("caption"))}</div>' if g.get("caption") else "")


def g_grid(g):
    rows, cols = int(g.get("rows") or 5), int(g.get("cols") or 5)
    path, walls = {tuple(p) for p in g.get("path") or []}, {tuple(p) for p in g.get("walls") or []}
    marks = {tuple(m[:2]): m[2] for m in g.get("marks") or []}
    cells = "".join(f'<div class="cell{" path" if (r, c) in path else ""}{" wall" if (r, c) in walls else ""}">{e(marks.get((r, c), ""))}</div>'
                    for r in range(rows) for c in range(cols))
    return f'<div class="grid" style="grid-template-columns:repeat({cols},1fr)">{cells}</div>'


def g_code(g):
    lines = str(g.get("code") or "").split("\n")[:7]
    hl = g.get("highlight")
    body = "".join(f'<div class="ln{" hl" if hl == i + 1 else ""}">{e(l) or "&nbsp;"}</div>' for i, l in enumerate(lines))
    return f'<div class="code"><div class="dots"><i></i><i></i><i></i><span>{e(g.get("lang"))}</span></div>{body}</div>'


def g_hero(g):
    orbit = (g.get("orbit") or [])[:6]
    sats = "".join(f'<div class="sat" style="--a:{i * 360 / max(1, len(orbit)) - 90 + (180 / len(orbit) if len(orbit) % 2 == 0 else 0)}deg">{ic(o)}</div>' for i, o in enumerate(orbit))
    return f'<div class="hero"><div class="ring"></div>{sats}<div class="core">{ic(g.get("icon"), "bolt")}</div>' + \
        (f'<div class="hlabel">{e(g.get("label"))}</div>' if g.get("label") else "") + "</div>"


GRAPHICS = {"vs": g_vs, "flow": g_flow, "big": g_big, "bars": g_bars, "grid": g_grid, "code": g_code, "hero": g_hero}

CSS = """
:root{--b1:%(b1)s;--b2:%(b2)s;--mk:%(mk)s;--glow:%(glow)s}
*{box-sizing:border-box;margin:0;padding:0}
body{width:1080px;height:1920px;overflow:hidden;font-family:'Geist',system-ui,sans-serif;color:#fff;-webkit-font-smoothing:antialiased}
.t{position:relative;width:1080px;height:1920px;overflow:hidden;display:flex;flex-direction:column;align-items:center;padding:150px 70px 120px;
 background:radial-gradient(900px 900px at 50%% 52%%,rgba(var(--glow),.55),transparent 62%%),radial-gradient(700px 600px at 100%% 0%%,rgba(var(--glow),.35),transparent 60%%),
 linear-gradient(160deg,var(--b1),var(--b2))}
.t:before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(115deg,rgba(255,255,255,.035) 0 2px,transparent 2px 46px);pointer-events:none}
.t:after{content:"";position:absolute;inset:0;background:radial-gradient(rgba(255,255,255,.09) 1.6px,transparent 1.8px) 0 0/34px 34px;mask:linear-gradient(#000,transparent 40%%,transparent 70%%,#000);pointer-events:none}
.ic{font-family:'Material Symbols Outlined';font-weight:400;font-style:normal;line-height:1;white-space:nowrap;font-feature-settings:'liga'}
.tag{position:relative;z-index:2;display:inline-flex;align-items:center;gap:14px;padding:14px 30px;border-radius:99px;background:rgba(255,255,255,.12);
 border:2px solid rgba(255,255,255,.28);font-size:38px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;backdrop-filter:blur(6px)}
.tag i{width:18px;height:18px;border-radius:50%%;background:var(--mk);box-shadow:0 0 18px var(--mk)}
h1{position:relative;z-index:2;margin-top:40px;max-width:960px;text-align:center;font-size:var(--hs,128px);line-height:1.02;font-weight:900;letter-spacing:-.035em;
 text-shadow:0 8px 0 rgba(0,0,0,.35),0 0 50px rgba(0,0,0,.4);text-wrap:balance}
mark{background:none;color:#14100A;position:relative;z-index:0;padding:0 .12em;white-space:nowrap}
mark:before{content:"";position:absolute;z-index:-1;left:0;right:0;top:.1em;bottom:.02em;background:var(--mk);transform:rotate(-2deg);border-radius:.12em;box-shadow:0 8px 0 rgba(0,0,0,.3)}
.gfx{position:relative;z-index:2;flex:1;width:100%%;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:0;overflow:visible}
.g{flex:none;display:flex;flex-direction:column;align-items:center;transform-origin:center center}
.sub{position:relative;z-index:2;margin-top:10px;text-align:center;font-size:50px;font-weight:700;line-height:1.2;color:rgba(255,255,255,.9);text-wrap:balance}
.brand{position:relative;z-index:2;margin-top:40px;display:flex;align-items:center;gap:16px;font-size:40px;font-weight:800;opacity:.92}
.brand i{width:46px;height:46px;border-radius:14px;background:var(--mk);display:grid;place-items:center;color:#14100A;font-style:normal;font-size:26px}
.sticker{position:absolute;z-index:3;right:40px;top:var(--sy,760px);transform:rotate(9deg);padding:20px 30px;border-radius:24px;background:#fff;color:#14100A;
 font-size:54px;font-weight:900;box-shadow:0 14px 0 rgba(0,0,0,.35);border:5px solid var(--mk)}
.tile{position:relative;display:grid;place-items:center;width:var(--ts,250px);height:var(--ts,250px);border-radius:56px;background:linear-gradient(160deg,rgba(255,255,255,.22),rgba(255,255,255,.06));
 border:3px solid rgba(255,255,255,.35);box-shadow:0 24px 60px rgba(0,0,0,.45),inset 0 2px 0 rgba(255,255,255,.4)}
.tile>.ic{font-size:calc(var(--ts,250px)*.56)}
.vs{display:flex;align-items:center;gap:16px;--ts:290px}
.vs-side{display:flex;flex-direction:column;align-items:center;gap:30px;width:370px;text-align:center}.vs-side b{font-size:70px;font-weight:900;line-height:1.05}.vs-side small{font-size:44px;font-weight:600;opacity:.8}
.vs-side.win .tile{border-color:var(--mk);box-shadow:0 0 0 8px rgba(255,255,255,.08),0 0 80px rgba(var(--glow),.9)}.vs-side.win b{color:var(--mk)}
.vsb{width:150px;height:150px;flex:none;border-radius:50%%;display:grid;place-items:center;background:var(--mk);color:#14100A;font-size:64px;font-weight:900;transform:rotate(-8deg);box-shadow:0 12px 0 rgba(0,0,0,.35);margin-top:-80px}
.flow{display:flex;flex-direction:column;align-items:center;gap:0;--ts:190px}.flow.n2{--ts:230px}.flow.n4{--ts:150px}
.node{display:flex;align-items:center;gap:36px;width:820px}.node b{font-size:58px;font-weight:900;line-height:1.05}
.node.bad .tile{border-color:#FF4D4D;background:linear-gradient(160deg,rgba(255,77,77,.4),rgba(255,77,77,.1))}.node.good .tile{border-color:#4DFF9A}
.x,.ok{position:absolute;right:-18px;top:-18px;width:76px;height:76px;border-radius:50%%;display:grid;place-items:center;font-family:'Material Symbols Outlined';font-style:normal;font-size:52px;font-weight:700;color:#fff;background:#FF3B3B;box-shadow:0 6px 0 rgba(0,0,0,.35)}
.ok{background:#16C76A}
.arr{height:76px;width:820px;display:flex;align-items:center;padding-left:calc(var(--ts)/2 - 5px);gap:30px}
.arr:before{content:"";width:10px;height:100%%;background:linear-gradient(var(--mk),rgba(255,255,255,.3));border-radius:5px}
.arr span{font-size:36px;font-weight:700;color:var(--mk)}
.big{display:flex;flex-direction:column;align-items:center}.big>.ic{font-size:180px;color:var(--mk);filter:drop-shadow(0 0 30px rgba(var(--glow),.9))}
.num{white-space:nowrap;font-size:var(--ns,340px);font-weight:900;line-height:.95;letter-spacing:-.05em;background:linear-gradient(180deg,#fff 30%%,var(--mk));-webkit-background-clip:text;color:transparent;filter:drop-shadow(0 14px 0 rgba(0,0,0,.35))}
.unit{font-size:64px;font-weight:800;margin-top:6px}
.bars{display:flex;align-items:flex-end;gap:16px;height:600px;width:900px;padding:0 10px;border-bottom:8px solid rgba(255,255,255,.6)}
.bar{flex:1;position:relative;border-radius:16px 16px 4px 4px;background:linear-gradient(180deg,rgba(255,255,255,.7),rgba(255,255,255,.3))}
.bar.hi{background:linear-gradient(180deg,var(--mk),rgba(255,255,255,.4));box-shadow:0 0 40px rgba(var(--glow),.8)}
.water{position:absolute;left:0;right:0;background:linear-gradient(180deg,#5AC8FF,#1E78FF);opacity:.9;border-radius:10px 10px 0 0}
.cap{margin-top:30px;font-size:52px;font-weight:800;color:var(--mk)}
.grid{display:grid;gap:12px;width:760px}
.cell{aspect-ratio:1;border-radius:18px;background:rgba(255,255,255,.12);border:2px solid rgba(255,255,255,.2);display:grid;place-items:center;font-size:64px;font-weight:900}
.cell.path{background:var(--mk);color:#14100A;box-shadow:0 0 30px rgba(var(--glow),.7)}.cell.wall{background:rgba(0,0,0,.55);border-color:rgba(0,0,0,.6)}
.code{width:920px;border-radius:36px;background:rgba(5,8,20,.88);border:3px solid rgba(255,255,255,.2);padding:34px 0 34px;font-family:'JetBrains Mono',monospace;box-shadow:0 30px 80px rgba(0,0,0,.5)}
.dots{display:flex;gap:14px;align-items:center;padding:0 40px 26px}.dots i{width:24px;height:24px;border-radius:50%%;background:#FF5F57}.dots i:nth-child(2){background:#FEBC2E}.dots i:nth-child(3){background:#28C840}
.dots span{margin-left:auto;font-family:'Geist';font-size:34px;font-weight:800;color:rgba(255,255,255,.6);text-transform:uppercase;letter-spacing:.1em}
.ln{font-size:44px;line-height:1.6;padding:0 40px;white-space:pre;color:#E6E9F2}.ln.hl{background:rgba(var(--glow),.35);box-shadow:inset 10px 0 0 var(--mk)}
.hero{position:relative;width:780px;height:780px;display:grid;place-items:center}
.ring{position:absolute;inset:60px;border-radius:50%%;border:4px dashed rgba(255,255,255,.35)}
.core{width:380px;height:380px;border-radius:50%%;display:grid;place-items:center;background:radial-gradient(circle at 35%% 30%%,rgba(255,255,255,.45),rgba(var(--glow),.35) 60%%,rgba(0,0,0,.2));
 border:5px solid var(--mk);box-shadow:0 0 120px rgba(var(--glow),.9)}.core .ic{font-size:230px}
.sat{position:absolute;left:50%%;top:50%%;width:150px;height:150px;margin:-75px;border-radius:40px;display:grid;place-items:center;background:rgba(255,255,255,.16);border:3px solid rgba(255,255,255,.4);
 transform:rotate(var(--a)) translate(330px) rotate(calc(-1*var(--a)))}.sat .ic{font-size:86px}
.hlabel{position:absolute;bottom:-90px;white-space:nowrap;padding:14px 34px;border-radius:99px;background:var(--mk);color:#14100A;font-size:52px;font-weight:900}
"""

FIT = """
(function(){var h=document.querySelector('h1'),g=document.querySelector('.gfx'),inner=document.querySelector('.g'),s=[190,176,164,152,142,132,122,112,104,96],i=0;
// the hook as big as it fits in at most three lines and 600 px, so the picture keeps at least 760 px
for(;i<s.length;i++){document.documentElement.style.setProperty('--hs',s[i]+'px');var r=h.getBoundingClientRect();
  var lines=Math.round(r.height/(s[i]*1.02));var wide=[].some.call(h.querySelectorAll('mark'),function(m){return m.getBoundingClientRect().width>960;});
  if(lines<=3&&r.height<=600&&!wide&&g.clientHeight>=760)break;}
var n=document.querySelector('.num');if(n){var k=340;while(n.scrollWidth>940&&k>140){k-=20;document.documentElement.style.setProperty('--ns',k+'px');}}
// the graphic grows to fill its space (up to 1.6x), never past it
var gw=g.clientWidth-20,gh=g.clientHeight-(document.querySelector('.hlabel')?110:30),iw=inner.scrollWidth,ih=inner.scrollHeight;
var k2=Math.min(2.2,gw/iw,gh/ih);inner.style.transform='scale('+k2+')';
var st=document.querySelector('.sticker');if(st){   // in the gap above the picture, else below it, else bottom-left; never on the hook or the picture
  var ir=inner.getBoundingClientRect(),hb=h.getBoundingClientRect().bottom,sh=st.getBoundingClientRect().height+30,br=document.querySelector('.brand').getBoundingClientRect().top;
  if(ir.top-hb>=sh){document.documentElement.style.setProperty('--sy',(hb+(ir.top-hb-sh)/2+10)+'px');}
  else if(br-ir.bottom>=sh){document.documentElement.style.setProperty('--sy',(ir.bottom+(br-ir.bottom-sh)/2+10)+'px');}
  else{k2=Math.min(k2,(gh-sh)/ih);inner.style.transform='scale('+k2+')';ir=inner.getBoundingClientRect();document.documentElement.style.setProperty('--sy',(ir.bottom+8)+'px');}}
var ok=document.querySelector('.t').scrollHeight<=1922&&k2>0.55;
document.title=ok?'FIT':'OVERFLOW '+(g.scrollHeight-g.clientHeight);})();
"""


def page(spec, channel):
    b1, b2, mk, glow = ACCENTS.get(spec.get("accent"), ACCENTS["violet"])
    fonts = (STATIC / "fonts.css").read_text().replace("url(/static/fonts/", f"url(file://{STATIC}/fonts/")
    mono = f"@font-face{{font-family:'JetBrains Mono';font-weight:700;src:url(file://{MONO}/JetBrainsMono-Bold.ttf)}}"
    g = spec.get("graphic") or {"type": "hero", "icon": "bolt"}
    gfx = GRAPHICS.get(g.get("type"), g_hero)(g)
    css = CSS % {"b1": b1, "b2": b2, "mk": mk, "glow": glow}
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>render</title><style>{fonts}{mono}{css}</style></head><body><div class="t">'
            + (f'<div class="tag"><i></i>{e(spec.get("tag"))}</div>' if spec.get("tag") else "")
            + f'<h1>{rich(spec.get("hook"))}</h1><div class="gfx"><div class="g">{gfx}</div></div>'
            + (f'<div class="sub">{rich(spec.get("sub"))}</div>' if spec.get("sub") else "")
            + (f'<div class="sticker">{e(spec.get("sticker"))}</div>' if spec.get("sticker") else "")
            + f'<div class="brand"><i>▶</i>{e(channel)}</div></div><script>document.fonts.ready.then(function(){{{FIT}}});</script></body></html>')


def render_thumb(spec, path, channel=""):
    binary = chrome()
    if not binary:
        raise RuntimeError("Chrome is not installed")
    with tempfile.TemporaryDirectory(prefix="postcrew-thumb-") as d:
        f = Path(d) / "t.html"
        f.write_text(page(spec, channel))
        dom = _run(binary, ["--dump-dom", f"file://{f}"], timeout=90, size=(W, H))
        m = re.search(r"<title>(.*?)</title>", dom.stdout or "")
        verdict = m.group(1) if m else "no answer"
        shot = Path(d) / "s.png"
        r = _run(binary, [f"--screenshot={shot}", f"file://{f}"], timeout=90, size=(W, H))
        if not shot.exists():
            raise RuntimeError(f"Chrome did not save the picture: {(r.stderr or '')[-200:]}")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot, path)
    return verdict


GRAPHIC = {"type": "object", "properties": {
    "type": {"type": "string", "enum": list(GRAPHICS)},
    "icon": {"type": "string"}, "label": {"type": "string"}, "value": {"type": "string"}, "caption": {"type": "string"},
    "orbit": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    "left": {"type": "object", "properties": {"icon": {"type": "string"}, "label": {"type": "string"}, "note": {"type": "string"}, "win": {"type": "boolean"}}, "additionalProperties": False},
    "right": {"type": "object", "properties": {"icon": {"type": "string"}, "label": {"type": "string"}, "note": {"type": "string"}, "win": {"type": "boolean"}}, "additionalProperties": False},
    "nodes": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {"icon": {"type": "string"}, "label": {"type": "string"}, "via": {"type": "string"}}, "additionalProperties": False}},
    "bad": {"type": "integer"}, "good": {"type": "integer"},
    "values": {"type": "array", "items": {"type": "number"}, "maxItems": 12}, "highlight": {"type": "array", "items": {"type": "integer"}},
    "water": {"type": "array", "items": {"type": "number"}, "maxItems": 12},
    "rows": {"type": "integer"}, "cols": {"type": "integer"},
    "path": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
    "walls": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
    "marks": {"type": "array", "items": {"type": "array", "items": {"type": ["integer", "string"]}}},
    "code": {"type": "string"}, "lang": {"type": "string"}}, "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {
    "tag": {"type": "string"}, "accent": {"type": "string", "enum": list(ACCENTS)}, "hook": {"type": "string"},
    "sticker": {"type": "string"}, "graphic": GRAPHIC}, "required": ["tag", "accent", "hook", "graphic"], "additionalProperties": False}

SYSTEM = """You design the thumbnail of a YouTube Short so people stop scrolling and tap it. A program draws a 1080x1920 picture
from your JSON: a topic tag, a huge hook at the top, one big picture of the topic in the middle, an optional sticker.

- tag: the topic in 1-3 words ("System design", "Sorting in Java", "2FA").
- hook: 2-6 words, the video's sharpest question, surprise or promise, never the full title. Wrap the 1-3 punch words in
  [[double brackets]] (they get a bright marker). Examples: "The server [[dies.]] Now what?", "Is it [[1 or 16?]]",
  "Stop [[double booking]]", "[[16]] cells, not 26".
- accent: fire (failures, outages, warnings), ocean (networking, cloud, data), violet (design, architecture, AI), lime (how-tos,
  good practice, algorithms), sun (puzzles, numbers, tips), rose (security, crypto, AI basics).
- sticker (optional): 1-3 words that add curiosity ("No internet!", "60 sec", "Amazon Q", "We tested it").
- graphic: the picture that SHOWS the topic. Pick the type that fits:
  vs {left, right: {icon, label, note?, win?}} two choices compared; flow {nodes: 2-4 {icon, label, via?}, bad?, good?} steps or
  a request path (via: the words on the arrow coming INTO that step, none on the first; bad/good: index of the failing / healthy step); big {value, label, icon?} one striking number or expression;
  bars {values, highlight?, water?, caption} sorting, arrays, rain water; grid {rows, cols, path, walls, marks:[r,c,"S"]} paths,
  puzzles; code {lang, code (3-5 short lines), highlight} when a snippet is the point; hero {icon, orbit: 3-5 icons, label}
  one system and its parts.
- Icons: only these Material Symbols names: {icons}.
Every word and number must agree with the video; add no claims it does not make. No colons in the hook."""


def design(llm, title, description="", narration="", icons=None):
    """The thumbnail spec for a video, written by the planner model."""
    names = ", ".join(sorted(set(ICONS) | set(EXTRA)))
    prompt = (f"VIDEO TITLE: {title}\n\nDESCRIPTION:\n{(description or '')[:1500]}\n\nWHAT THE VIDEO SAYS:\n{(narration or '')[:3000]}\n\n"
              "Design its thumbnail.")
    return llm.call("planner", SYSTEM.replace("{icons}", names), prompt, SCHEMA, tools=()).data or {}
