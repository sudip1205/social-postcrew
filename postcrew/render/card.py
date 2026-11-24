"""LinkedIn images in the "Signal Board" style (owner, 2026-11-24: "for linkedin post do not create movies. create images instead.
Refer this kind of images. and create a own attractive style.").

The references were editorial infographics: a dark stat card with a two-tone headline and big numbers, a comparison table of options,
a decision flow, a bar chart with the point highlighted, a hub of grouped items, numbered key points. Signal Board is Postcrew's own take:
deep ink background with one coloured glow, a kicker with a square bullet, a white headline whose key words carry the accent gradient,
glass panels, one takeaway bar in the accent, and a quiet footer (handle and source).

The Visual Designer writes a JSON spec (agents/media.py, prompts/card.md); this module turns it into HTML and headless Chrome takes
the 1080x1350 picture. The page shrinks its own text a little when it is full; when it still does not fit, CardError says what to cut.
"""
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

W, H = 1080, 1350
STATIC = Path(__file__).resolve().parents[1] / "studio" / "static"
MONO = Path(__file__).resolve().parent / "fonts"
LAYOUTS = ("stats", "compare", "flow", "bars", "hub", "points", "code")
ACCENTS = {   # gradient from, to, glow
    "ember": ("#FFB547", "#FF6B4A", "255,122,69"),
    "violet": ("#C4B5FD", "#8B7CF6", "139,124,246"),
    "mint": ("#6EE7B7", "#22C59A", "34,197,154"),
    "sky": ("#93C5FD", "#3B82F6", "59,130,246"),
    "rose": ("#FDA4AF", "#F43F5E", "244,63,94"),
}
# Material Symbols the cards may use (they are in the Studio's icon font: design/icons-extra.txt)
ICONS = ("bolt", "speed", "schedule", "timer", "warning", "error", "check_circle", "cancel", "shield", "lock", "key", "security",
         "cloud", "dns", "storage", "database", "memory", "hub", "account_tree", "lan", "api", "code", "terminal", "bug_report",
         "build", "settings", "tune", "trending_up", "trending_down", "payments", "account_balance", "savings", "monitoring",
         "insights", "analytics", "psychology", "smart_toy", "neurology", "group", "person", "rocket_launch", "verified",
         "sync", "swap_horiz", "merge", "fork_right", "inventory_2", "description", "search", "visibility", "public", "factory",
         "paid", "credit_card", "receipt_long", "pause_circle", "block", "layers", "deployed_code", "integration_instructions")


class CardError(Exception):
    pass


def chrome():
    for c in (os.environ.get("POSTCREW_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", shutil.which("google-chrome"),
              shutil.which("chromium"), *sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"), reverse=True)):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def available():
    """POSTCREW_CARDS=off draws the plain Pillow poster instead (the tests, whose scripted designer writes poster specs)."""
    return os.environ.get("POSTCREW_CARDS", "").lower() != "off" and chrome() is not None


e = lambda s: html.escape(str(s or ""), quote=True)


def rich(s):
    """Text with [[key words]] in the accent gradient."""
    out, last = [], 0
    for m in re.finditer(r"\[\[(.+?)\]\]", str(s or "")):
        out.append(e(str(s)[last:m.start()]))
        out.append(f'<span class="acc">{e(m.group(1))}</span>')
        last = m.end()
    out.append(e(str(s or "")[last:]))
    return "".join(out)


def plain(s):
    return re.sub(r"\[\[(.+?)\]\]", r"\1", str(s or ""))


def icon(name, fallback="bolt"):
    n = str(name or "").strip()
    return f'<span class="ic">{n if n in ICONS else fallback}</span>'


# ---------- the layouts ----------
def _stats(s):
    q = s.get("quote") or {}
    quote = (f'<blockquote class="panel quote fit"><p>&ldquo;{e(q.get("text"))}&rdquo;</p>'
             + (f'<cite>{e(q.get("who"))}</cite>' if q.get("who") else "") + "</blockquote>") if q.get("text") else ""
    st = (s.get("stats") or [])[:4]
    cols = 2 if len(st) == 4 else max(1, len(st))
    cells = "".join(f'<div class="stat"><div class="val">{e(x.get("value"))}</div><div class="lab">{e(x.get("label"))}</div></div>' for x in st)
    return f'{quote}<div class="stats" style="grid-template-columns:repeat({cols},1fr)">{cells}</div>'


def _compare(s):
    cols = (s.get("columns") or [])[:3]
    best = s.get("best")
    head = "".join(
        f'<div class="ch{" best" if best == i else ""}">{icon(c.get("icon"), "layers")}<b>{e(c.get("name"))}</b>'
        + (f'<small>{e(c.get("sub"))}</small>' if c.get("sub") else "") + (f'<em>Best fit</em>' if best == i else "") + "</div>"
        for i, c in enumerate(cols))
    rows = "".join(
        f'<div class="rl">{icon(r.get("icon"), "tune")}<span>{e(r.get("label"))}</span></div>'
        + "".join(f'<div class="cell{" best" if best == i else ""}">{rich(c)}</div>' for i, c in enumerate((r.get("cells") or [])[:len(cols)]))
        for r in (s.get("rows") or [])[:5])
    return f'<div class="cmp" style="grid-template-columns:210px repeat({len(cols)},1fr)"><div class="corner">{e(s.get("dimension") or "")}</div>{head}{rows}</div>'


def _flow(s):
    tone_icon = {"good": "check_circle", "bad": "warning", "normal": None}
    steps = (s.get("steps") or [])[:6]
    out = []
    for i, st in enumerate(steps):
        tone = st.get("tone") if st.get("tone") in tone_icon else "normal"
        ic = icon(st.get("icon"), tone_icon[tone] or "bolt")
        out.append(f'<div class="step {tone}"><div class="num">{i + 1}</div>{ic}<div class="txt"><b>{e(st.get("head"))}</b>'
                   + (f'<p>{rich(st.get("body"))}</p>' if st.get("body") else "") + "</div>"
                   + (f'<div class="tag">{e(st.get("tag"))}</div>' if st.get("tag") else "") + "</div>")
        if i < len(steps) - 1:
            via = steps[i + 1].get("via") or st.get("via_next") or ""
            out.append(f'<div class="link"><i></i>{f"<span>{e(via)}</span>" if via else ""}</div>')
    return f'<div class="flow">{"".join(out)}</div>'


def _bars(s):
    bars = (s.get("bars") or [])[:7]
    top = max([float(b.get("value") or 0) for b in bars] + [1e-9])
    rows = "".join(
        f'<div class="bar{" hi" if b.get("highlight") else ""}"><span class="bl">{e(b.get("label"))}</span>'
        f'<span class="track"><i style="width:{max(2.0, 100 * float(b.get("value") or 0) / top):.1f}%"></i></span>'
        f'<span class="bv">{e(b.get("display") or b.get("value"))}</span></div>' for b in bars)
    leg = s.get("legend") or []
    legend = ('<div class="legend">' + "".join(f'<span class="{"hi" if i == 0 else ""}"><i></i>{e(x)}</span>' for i, x in enumerate(leg[:2])) + "</div>") if leg else ""
    unit = f'<div class="unit">{e(s.get("bars_title"))}</div>' if s.get("bars_title") else ""
    return f'<div class="panel bars fit">{unit}{rows}{legend}</div>'


def _hub(s):
    groups = (s.get("groups") or [])[:6]
    cards = "".join(f'<div class="grp">{icon(g.get("icon"), "hub")}<b>{e(g.get("head"))}</b><div class="chips">'
                    + "".join(f"<span>{e(x)}</span>" for x in (g.get("items") or [])[:5]) + "</div></div>" for g in groups)
    return (f'<div class="hubwrap"><svg class="wires"></svg><div class="hub"><span class="ic">{(s.get("hub_icon") if s.get("hub_icon") in ICONS else "hub")}</span>'
            f'<b>{e(s.get("hub") or "")}</b></div><div class="grps">{cards}</div></div>')


def _points(s):
    pts = (s.get("points") or [])[:5]
    return '<div class="pts">' + "".join(
        f'<div class="pt">{icon(p.get("icon"), "bolt")}<div><b>{rich(p.get("head"))}</b>' + (f'<p>{rich(p.get("body"))}</p>' if p.get("body") else "")
        + f'</div><span class="n">{i + 1:02d}</span></div>' for i, p in enumerate(pts)) + "</div>"


def _code(s):
    lines = str(s.get("code") or "").rstrip("\n").split("\n")[:16]
    hl = s.get("highlight")
    body = "".join(f'<div class="ln{" hl" if hl == i + 1 else ""}"><i>{i + 1}</i><span>{e(ln) or "&nbsp;"}</span></div>' for i, ln in enumerate(lines))
    bullets = "".join(f"<li>{rich(b)}</li>" for b in (s.get("bullets") or [])[:3])
    return (f'<div class="panel codebox fit"><div class="dots"><i></i><i></i><i></i><span>{e(s.get("language") or "")}</span></div>{body}</div>'
            + (f'<ul class="bul">{bullets}</ul>' if bullets else ""))


BODY = {"stats": _stats, "compare": _compare, "flow": _flow, "bars": _bars, "hub": _hub, "points": _points, "code": _code}


def shown_text(spec):
    """Every word the picture shows (the checks compare its numbers and names with the post)."""
    parts = [spec.get(k) for k in ("kicker", "title", "subtitle", "takeaway", "dimension", "hub", "bars_title", "code")]
    q = spec.get("quote") or {}
    parts += [q.get("text"), q.get("who")]
    for k in ("stats", "columns", "steps", "bars", "groups", "points", "rows"):
        for x in spec.get(k) or []:
            if isinstance(x, dict):
                for v in x.values():
                    parts += v if isinstance(v, list) else [v]
    parts += spec.get("bullets") or []
    parts += spec.get("legend") or []
    return " ".join(plain(p) for p in parts if isinstance(p, (str, int, float)) and str(p).strip())


CSS = """
:root{--a1:%(a1)s;--a2:%(a2)s;--glow:%(glow)s;--ink:#0A0F1E;--fg:#F4F6FB;--mut:#A3ACC2;--dim:#6B7591;--line:rgba(255,255,255,.09);--glass:rgba(255,255,255,.045)}
*{box-sizing:border-box;margin:0;padding:0}
html{font-size:16px}
body{width:1080px;height:1350px;overflow:hidden;background:var(--ink);color:var(--fg);font-family:'Geist',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.card{position:relative;width:1080px;height:1350px;padding:72px 68px 0;display:flex;flex-direction:column;overflow:hidden;
 background:radial-gradient(900px 620px at 92%% -8%%,rgba(var(--glow),.30),transparent 62%%),radial-gradient(700px 520px at -10%% 108%%,rgba(var(--glow),.12),transparent 60%%),
 radial-gradient(rgba(255,255,255,.06) 1.2px,transparent 1.3px) 0 0/28px 28px,var(--ink)}
.card:before{content:"";position:absolute;left:0;top:0;right:0;height:6px;background:linear-gradient(90deg,var(--a1),var(--a2))}
.ic{font-family:'Material Symbols Outlined';font-weight:400;font-style:normal;line-height:1;letter-spacing:normal;text-transform:none;white-space:nowrap;-webkit-font-feature-settings:'liga';font-feature-settings:'liga'}
.kick{display:flex;align-items:center;gap:14px;font-size:1.45rem;font-weight:700;letter-spacing:.16em;color:var(--a1);text-transform:uppercase}
.kick:before{content:"";width:14px;height:14px;background:linear-gradient(135deg,var(--a1),var(--a2));border-radius:3px}
h1{margin-top:26px;font-size:4.5rem;line-height:1.04;font-weight:800;letter-spacing:-.025em}
.acc{background:linear-gradient(90deg,var(--a1),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{margin-top:22px;font-size:1.75rem;line-height:1.38;color:var(--mut);max-width:920px}
.main{flex:1;min-height:0;margin-top:40px;display:flex;flex-direction:column;justify-content:center;gap:1.6em;overflow:hidden;font-size:16px}
.main>*{flex-shrink:0}
.panel{background:var(--glass);border:1px solid var(--line);border-radius:22px}
.quote{padding:26px 30px;border-left:5px solid var(--a2);border-radius:14px}
.quote p{font-size:1.6em;line-height:1.45;font-style:italic;color:#DDE2EE}.quote cite{display:block;margin-top:12px;font-style:normal;font-weight:700;font-size:1.3em;color:var(--fg)}
.stats{display:grid;gap:18px}
.stat{padding:26px 24px;border-top:2px solid rgba(var(--glow),.55);background:linear-gradient(180deg,rgba(var(--glow),.10),transparent 70%%);border-radius:0 0 18px 18px}
.val{font-size:4.6em;font-weight:800;letter-spacing:-.03em;line-height:1;background:linear-gradient(90deg,var(--a1),var(--a2));-webkit-background-clip:text;color:transparent}
.lab{margin-top:14px;font-size:1.32em;line-height:1.4;color:var(--mut)}
.cmp{display:grid;border:1px solid var(--line);border-radius:22px;overflow:hidden;background:var(--glass)}
.cmp>div{padding:18px 18px;border-bottom:1px solid var(--line);font-size:1.28em;line-height:1.38;color:#D6DBE7}
.corner{display:flex;align-items:flex-end;color:var(--dim)!important;font-weight:700;font-size:1.05em!important;letter-spacing:.12em;text-transform:uppercase}
.ch{display:flex;flex-direction:column;gap:6px;background:rgba(255,255,255,.035);position:relative}
.ch .ic{font-size:2.2em;color:var(--a1)}.ch b{font-size:1.5em;color:var(--fg)}.ch small{font-size:1.05em;color:var(--dim)}
.ch em{position:absolute;top:14px;right:14px;font-style:normal;font-size:.9em;font-weight:700;padding:4px 10px;border-radius:99px;background:linear-gradient(90deg,var(--a1),var(--a2));color:#111}
.best{background:rgba(var(--glow),.10)!important;box-shadow:inset 1px 0 0 rgba(var(--glow),.45),inset -1px 0 0 rgba(var(--glow),.45)}
.rl{display:flex;align-items:center;gap:12px;font-weight:700;color:var(--fg)!important}.rl .ic{font-size:1.9em;color:var(--a1)}
.flow{display:flex;flex-direction:column}
.step{display:flex;align-items:center;gap:20px;padding:20px 24px;border:1px solid var(--line);border-radius:20px;background:var(--glass);position:relative}
.step .num{width:44px;height:44px;flex:none;border-radius:12px;display:grid;place-items:center;font-weight:800;font-size:1.3em;background:rgba(255,255,255,.07);color:var(--mut)}
.step>.ic{font-size:2.5em;color:var(--a1);flex:none}.step .txt{flex:1;min-width:0}.step b{font-size:1.65em}.step p{margin-top:6px;font-size:1.3em;line-height:1.4;color:var(--mut)}
.step .tag{flex:none;font-size:1em;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:6px 12px;border-radius:99px;border:1px solid var(--line);color:var(--mut)}
.step.good{border-color:rgba(52,211,153,.55);background:rgba(52,211,153,.08)}.step.good>.ic{color:#34D399}
.step.bad{border-color:rgba(251,113,133,.55);background:rgba(251,113,133,.08)}.step.bad>.ic{color:#FB7185}
.link{height:46px;margin-left:46px;display:flex;align-items:center;gap:14px}
.link i{width:2px;height:100%%;background:linear-gradient(var(--a1),var(--a2))}.link span{font-size:1.1em;color:var(--dim);font-style:italic}
.bars{padding:30px 32px;display:flex;flex-direction:column;gap:20px}
.unit{font-size:1.05em;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.bar{display:grid;grid-template-columns:200px 1fr 120px;align-items:center;gap:18px}
.bl{font-size:1.4em;font-weight:600;color:var(--mut)}.bv{text-align:right;font-size:1.5em;font-weight:800;color:var(--mut)}
.track{height:34px;background:rgba(255,255,255,.05);border-radius:8px;overflow:hidden}.track i{display:block;height:100%%;background:#4B5470;border-radius:8px}
.bar.hi .bl,.bar.hi .bv{color:var(--fg)}.bar.hi .track i{background:linear-gradient(90deg,var(--a1),var(--a2))}
.legend{display:flex;gap:28px;font-size:1.1em;color:var(--mut)}.legend i{display:inline-block;width:16px;height:16px;border-radius:4px;background:#4B5470;margin-right:8px;vertical-align:-2px}.legend .hi i{background:linear-gradient(90deg,var(--a1),var(--a2))}
.hubwrap{position:relative;display:flex;flex-direction:column;align-items:center;gap:34px}
.wires{position:absolute;inset:0;width:100%%;height:100%%;pointer-events:none;overflow:visible}
.hub{position:relative;z-index:1;display:flex;align-items:center;gap:14px;padding:20px 34px;border-radius:99px;font-size:1.8em;font-weight:800;
 background:linear-gradient(135deg,rgba(var(--glow),.30),rgba(var(--glow),.08));border:1px solid rgba(var(--glow),.6);box-shadow:0 0 60px rgba(var(--glow),.35)}
.hub .ic{font-size:2.4em;color:var(--a1)}
.grps{position:relative;z-index:1;width:100%%;display:grid;grid-template-columns:1fr 1fr;gap:18px}
.grp{padding:20px 22px;border:1px solid var(--line);border-radius:18px;background:rgba(14,20,38,.92)}
.grp>.ic{font-size:1.9em;color:var(--a1);vertical-align:-6px;margin-right:10px}.grp>b{font-size:1.45em}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.chips span{font-size:1.12em;padding:6px 12px;border-radius:10px;background:rgba(255,255,255,.06);color:#D6DBE7}
.pts{display:flex;flex-direction:column;gap:16px}
.pt{display:flex;gap:22px;align-items:flex-start;padding:24px 26px;border:1px solid var(--line);border-radius:20px;background:var(--glass);position:relative}
.pt>.ic{font-size:2.5em;color:var(--a1);flex:none;margin-top:2px}.pt b{font-size:1.65em;line-height:1.3}.pt p{margin-top:8px;font-size:1.32em;line-height:1.42;color:var(--mut)}
.pt .n{position:absolute;right:22px;top:16px;font-size:1em;font-weight:800;color:var(--dim);letter-spacing:.1em}
.codebox{padding:22px 0 18px;font-family:'JetBrains Mono',monospace;background:rgba(6,10,22,.85)}
.dots{display:flex;gap:9px;align-items:center;padding:0 24px 16px}.dots i{width:13px;height:13px;border-radius:50%%;background:#3A4257}.dots i:first-child{background:#FF6B6B}.dots i:nth-child(2){background:#FFC24B}.dots i:nth-child(3){background:#3DDC97}
.dots span{margin-left:auto;font-family:'Geist';font-size:1em;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.ln{display:flex;font-size:1.3em;line-height:1.75;padding-right:24px;white-space:pre}.ln i{width:62px;flex:none;text-align:right;padding-right:20px;font-style:normal;color:#4B5470}
.ln.hl{background:rgba(var(--glow),.14);box-shadow:inset 4px 0 0 var(--a2)}
.bul{list-style:none;display:flex;flex-direction:column;gap:10px}.bul li{font-size:1.4em;line-height:1.4;color:var(--mut);padding-left:28px;position:relative}
.bul li:before{content:"";position:absolute;left:0;top:.55em;width:12px;height:12px;border-radius:3px;background:linear-gradient(135deg,var(--a1),var(--a2))}
.take{flex:none;margin-top:30px;padding:26px 32px;border-radius:18px;background:linear-gradient(90deg,var(--a1),var(--a2));color:#14100C;font-size:1.65rem;font-weight:800;line-height:1.35}
.foot{flex:none;height:96px;margin-top:26px;display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);font-size:1.1rem;color:var(--dim)}
.brand{display:flex;align-items:center;gap:12px;font-weight:700;color:var(--mut);font-size:1.2rem}.brand i{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--a1),var(--a2))}
.src{max-width:620px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""

FIT_JS = """
(function(){
  function wires(){
    var w=document.querySelector('.hubwrap'); if(!w) return;
    var svg=w.querySelector('.wires'), hb=w.querySelector('.hub').getBoundingClientRect(), r0=w.getBoundingClientRect();
    var hx=hb.left+hb.width/2-r0.left, hy=hb.top+hb.height/2-r0.top, out='';
    w.querySelectorAll('.grp').forEach(function(g){var b=g.getBoundingClientRect(),gx=b.left+b.width/2-r0.left,gy=b.top-r0.top;
      out+='<path d="M'+hx+','+hy+' C'+hx+','+(hy+(gy-hy)*0.6)+' '+gx+','+(gy-(gy-hy)*0.5)+' '+gx+','+gy+'" fill="none" stroke="url(#wg)" stroke-width="2.5" opacity=".75"/>';
      out+='<circle cx="'+gx+'" cy="'+gy+'" r="5" fill="var(--a2)"/>';});
    svg.innerHTML='<defs><linearGradient id="wg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--a1)"/><stop offset="1" stop-color="var(--a2)"/></linearGradient></defs>'+out;
  }
  function over(){
    var m=document.querySelector('.main'); if(m.scrollHeight>m.clientHeight+2) return 'the picture is too full: '+(m.scrollHeight-m.clientHeight)+' px too tall';
    var bad=[];document.querySelectorAll('.fit,.cmp>div,.step,.pt,.grp,.stat,h1,.sub,.take').forEach(function(x){if(x.scrollWidth>x.clientWidth+2) bad.push((x.innerText||'').slice(0,40));});
    return bad.length?'text too wide: '+bad.slice(0,3).join(' | '):'';
  }
  // the header keeps its size; the body grows to fill the card (no empty middle), and shrinks a little when it is full
  var m=document.querySelector('.main'), sizes=[30,28,26,24,23,22,21,20,19,18,17,16,15,14.2,13.5], i=0, why='', fill=function(){return m.scrollHeight<=m.clientHeight+2;};
  m.style.justifyContent='flex-start';
  for(;i<sizes.length;i++){m.style.fontSize=sizes[i]+'px';why=over();if(!why&&fill())break;}
  m.style.justifyContent='';
  wires();
  document.title=why?'OVERFLOW '+why:'FIT '+sizes[Math.min(i,sizes.length-1)];
})();
"""


def page(spec, handle="", source=""):
    a1, a2, glow = ACCENTS.get(spec.get("accent"), ACCENTS["ember"])
    fonts = (STATIC / "fonts.css").read_text().replace("url(/static/fonts/", f"url(file://{STATIC}/fonts/")
    mono = "".join(f"@font-face{{font-family:'JetBrains Mono';font-weight:{w};src:url(file://{MONO}/JetBrainsMono-{n}.ttf)}}"
                   for w, n in ((400, "Regular"), (700, "Bold")) if (MONO / f"JetBrainsMono-{n}.ttf").exists())
    layout = spec.get("layout") if spec.get("layout") in BODY else "points"
    body = BODY[layout](spec)
    take = f'<div class="take">{rich(spec.get("takeaway"))}</div>' if spec.get("takeaway") else ""
    sub = f'<p class="sub">{rich(spec.get("subtitle"))}</p>' if spec.get("subtitle") else ""
    kick = f'<div class="kick">{e(spec.get("kicker"))}</div>' if spec.get("kicker") else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>render</title><style>{fonts}{mono}{CSS % {"a1": a1, "a2": a2, "glow": glow}}</style></head>'
            f'<body><div class="card">{kick}<h1>{rich(spec.get("title"))}</h1>{sub}<div class="main">{body}</div>{take}'
            f'<div class="foot"><div class="brand"><i></i>{e(handle)}</div><div class="src">{e(source)}</div></div></div>'
            f'<script>document.fonts.ready.then(function(){{{FIT_JS}}});</script></body></html>')


def _run(binary, args, timeout=90):
    r = subprocess.run([binary, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--allow-file-access-from-files", "--run-all-compositor-stages-before-draw", "--virtual-time-budget=6000",
                        f"--window-size={W},{H}", *args], capture_output=True, text=True, timeout=timeout)
    return r


def render_card(spec, path, handle="", source=""):
    """spec -> 1080x1350 PNG at path. Raises CardError when the text does not fit (say what to cut) or Chrome is missing."""
    binary = chrome()
    if not binary:
        raise CardError("Chrome is not installed, so the image cannot be drawn")
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="postcrew-card-") as d:
        f = Path(d) / "card.html"
        f.write_text(page(spec, handle, source))
        dom = _run(binary, ["--dump-dom", f"file://{f}"])
        m = re.search(r"<title>(.*?)</title>", dom.stdout or "", re.S)
        verdict = html.unescape(m.group(1)) if m else ""
        if verdict.startswith("OVERFLOW"):
            raise CardError(verdict[len("OVERFLOW "):] + ": shorten the text or use fewer items")
        if not verdict.startswith("FIT"):
            raise CardError(f"Chrome did not draw the image: {(dom.stderr or '')[-200:]}")
        shot = Path(d) / "shot.png"
        _run(binary, [f"--screenshot={shot}", f"file://{f}"])
        if not shot.exists() or shot.stat().st_size < 10_000:
            raise CardError("Chrome did not save the image")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shot, path)
    return {"scale": float(verdict.split()[1]) / 16 if len(verdict.split()) > 1 else 1.0}


SCHEMA = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": list(LAYOUTS)},
        "accent": {"type": "string", "enum": list(ACCENTS)},
        "kicker": {"type": "string"}, "title": {"type": "string"}, "subtitle": {"type": "string"}, "takeaway": {"type": "string"},
        "quote": {"type": "object", "properties": {"text": {"type": "string"}, "who": {"type": "string"}}, "additionalProperties": False},
        "stats": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {"value": {"type": "string"}, "label": {"type": "string"}},
                                                            "additionalProperties": False}},
        "dimension": {"type": "string"},
        "columns": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {k: {"type": "string"} for k in ("name", "sub", "icon")},
                                                              "additionalProperties": False}},
        "rows": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {"label": {"type": "string"}, "icon": {"type": "string"},
                                                                                           "cells": {"type": "array", "items": {"type": "string"}, "maxItems": 3}},
                                                           "additionalProperties": False}},
        "best": {"type": "integer"},
        "steps": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "head": {"type": "string"}, "body": {"type": "string"}, "icon": {"type": "string"}, "tag": {"type": "string"}, "via": {"type": "string"},
            "tone": {"type": "string", "enum": ["normal", "good", "bad"]}}, "additionalProperties": False}},
        "bars_title": {"type": "string"},
        "bars": {"type": "array", "maxItems": 7, "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "value": {"type": "number"}, "display": {"type": "string"}, "highlight": {"type": "boolean"}}, "additionalProperties": False}},
        "legend": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
        "hub": {"type": "string"}, "hub_icon": {"type": "string"},
        "groups": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "head": {"type": "string"}, "icon": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}, "maxItems": 5}}, "additionalProperties": False}},
        "points": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {k: {"type": "string"} for k in ("head", "body", "icon")},
                                                             "additionalProperties": False}},
        "language": {"type": "string"}, "code": {"type": "string"}, "highlight": {"type": "integer"},
        "bullets": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["layout", "title"],
    "additionalProperties": False,
}


def validate_spec(spec):
    """What the layout needs before it is drawn (the Visual Designer is asked again with these)."""
    L, bad = spec.get("layout"), []
    need = {"stats": ("stats", 2), "compare": ("rows", 2), "flow": ("steps", 2), "bars": ("bars", 2), "hub": ("groups", 3), "points": ("points", 2)}
    if L in need and len(spec.get(need[L][0]) or []) < need[L][1]:
        bad.append(f"the {L} layout needs at least {need[L][1]} {need[L][0]}")
    if L == "compare" and len(spec.get("columns") or []) < 2:
        bad.append("the compare layout needs 2 or 3 columns")
    if L == "compare" and any(len(r.get("cells") or []) != len(spec.get("columns") or []) for r in spec.get("rows") or []):
        bad.append("every compare row needs one cell per column")
    if L == "hub" and not spec.get("hub"):
        bad.append("the hub layout needs the hub's name")
    if L == "code" and not str(spec.get("code") or "").strip():
        bad.append("the code layout needs the code")
    if L == "code" and any(len(x) > 58 for x in str(spec.get("code") or "").split("\n")):
        bad.append("code lines must be under 58 characters")
    if len(plain(spec.get("title"))) > 80:
        bad.append("the title is over 80 characters")
    return bad


if __name__ == "__main__":   # python3 -m postcrew.render.card spec.json out.png
    import sys
    print(json.dumps(render_card(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2], "example.com/you", "Source: example.com")))
