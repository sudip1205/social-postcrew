"""The looks a factory video may use, ticked in the Studio's Factory (owner, 2026-11-12).

Signal (the blue diagram look), Story (the cast, Shorts only) and VS Code (real typed and run code, long algorithm videos only). The
ticked looks are saved (state "factory-styles") and used both by the Factory chat and by the crew's Script Writer: it may use and mix
only those, as the skill's references/mixing-styles.md says, and `npm run make` refuses any other look.
"""
STYLES = {   # owner, 2026-11-21: "on factory only keep single blue and isometric pastel and remove all other option"
    "signal": {"label": "Signal (blue)", "icon": "insights",
               "what": "the blue look, rendered by the Tech Glow engine (navy glow, icon tiles, light-pulse connectors; owner, 2026-11-15) with "
                       "glowing glass 3D bars and objects, like the published Binary Search Short (owner, 2026-11-17)"},
    "iso": {"label": "Isometric (pastel)", "icon": "deployed_code",
            "what": "the owner's Isometric Pastel style: a hand-drawn 2D-canvas isometric world filmed by a moving, turning camera, built from "
                    "the object library, with synced sound effects (styles/iso-pastel); pick a variation for the kind of video"},
    # owner, 2026-11-26: "I want realism ... create characters, like handdrawn ... also some real screenshots, like vscode or phone screen"
    "sketch": {"label": "Sketch Screens", "icon": "draw",
               "what": "hand-drawn people and real devices on a dark board: phones, laptops and monitors with live screens (VS Code, terminal, "
                       "browser, a game, chat, notifications), neon line art and a pixel title (styles/sketch-screens); for topics about "
                       "people and devices, such as multiplayer games, notifications and uploads"},
}
# The Isometric variations (owner, 2026-11-21): the same kit, camera and object library in a different stage and materials, each taken
# from a Short the owner picked (shorts-factory/styles/iso-pastel/VARIANTS.md). "auto" lets the Script Writer choose by topic.
VARIANTS = {
    "pastel": {"label": "Pastel (house look)", "what": "pastel paper, matte blocks: anything; software, data, systems"},
    "auto": {"label": "Auto (by topic)", "what": "the Script Writer picks the variation that fits the topic (VARIANTS.md)"},
    "night": {"label": "Night Lab", "what": "black stage, neon-edged parts, glowing traces, macro push-ins: hardware, chips, signals"},
    "cream": {"label": "Cream Blueprint", "what": "one big beige world, pan and tilt, leader-line call-outs: home networks, buildings, cities"},
    "sky": {"label": "Sky Toy", "what": "glossy white toys on sky blue, glowing rings, rainbow waves: physics and everyday science"},
    "studio": {"label": "Studio Build", "what": "one hero object built piece by piece in a blue studio, one long orbit: anatomy of a GPU, CPU, phone"},
    "ink": {"label": "Ink", "what": "black-outline line art, only the explained part in colour: exploded views, which part does what"},
    "maker": {"label": "Maker Bench", "what": "green cutting mat, real colours: electronics projects, sensors, wiring"},
}
DEFAULT_VARIANT = "pastel"
SOLO = "3d"   # the retired 3D look (video-engine): no longer offered, kept so old episodes still read
SOLOS = ("signal", "iso", "sketch")   # every look makes the whole video by itself: one is ticked at a time
DEFAULT = ["iso"]   # owner, 2026-11-15: "this video style is perfect and the timing of shorts are perfect. keep it consistent"
STATE = "factory-styles"


# Retired looks (owner, 2026-11-21): no longer offered in the Factory and refused by save(); a state saved before still reads, so its
# pipeline keeps working until the owner picks one of the two looks
RETIRED = {"story": "Story (cast)", "code": "VS Code", "3d": "3D (isometric)"}


def ticked(ws):
    got = [s for s in (ws.state(STATE, {}) or {}).get("styles", DEFAULT) if s in STYLES or s in RETIRED]
    return got or list(DEFAULT)


def variant(ws):
    v = (ws.state(STATE, {}) or {}).get("variant") or DEFAULT_VARIANT
    return v if v in VARIANTS else DEFAULT_VARIANT


def save(ws, styles, variant_id=None):
    got = [s for s in STYLES if s in (styles or [])]
    if not got:
        raise ValueError("tick a look")
    if len(got) > 1:
        raise ValueError("each look makes the whole video: tick one of them")
    v = str(variant_id or "").strip() or variant(ws)
    if v not in VARIANTS:
        raise ValueError(f"unknown Isometric variation: {v}")
    ws.save_state(STATE, {"styles": got, "variant": v})
    return got


def options(ws):
    on, v = set(ticked(ws)), variant(ws)
    out = []
    for k, d in STYLES.items():
        row = {"id": k, **d, "on": k in on}
        if k == "iso":
            row.update(variants=[{"id": i, **x} for i, x in VARIANTS.items()], variant=v)
        out.append(row)
    return out


def is_3d(styles):
    return list(styles) == [SOLO]


def is_iso(styles):
    return list(styles) == ["iso"]


def is_sketch(styles):
    return list(styles) == ["sketch"]


def variant_line(v):
    """What the Script Writer is told about the Isometric variation."""
    if v == "auto":
        return ("VARIATION: Auto. Pick the variant from VARIANTS.md whose 'use it for' fits this topic (pastel when none fits) and set it "
                "as \"variant\" in script.json.")
    v = v if v in VARIANTS else DEFAULT_VARIANT
    return (f"VARIATION ticked in the Factory: {VARIANTS[v]['label']}. Set \"variant\": \"{v}\" in script.json and follow its row in "
            "VARIANTS.md (stage, materials, camera habits).")


def instruction(styles, variant_id=None):
    """The line the Script Writer (and the Factory chat) gets about the looks."""
    if is_sketch(styles):
        return ("LOOK ticked in the Factory: Sketch Screens (shorts-factory/styles/sketch-screens): hand-drawn people, real devices with "
                "live screens, neon line art on a dark board. script.json \"style\": \"sketch\".")
    if is_3d(styles):
        return ("LOOK ticked in the Factory: 3D (isometric, video-engine). Do NOT write scenes: write the storyboard program "
                "shorts-factory/episodes/<slug>/scene.js (function build(sb) {...}) following ~/video-engine/RULES.md, plus "
                "shorts-factory/episodes/<slug>/script.json as {\"style\": \"3d\", \"topic\": \"<topic>\", \"format\": \"short\" (or \"long\")} "
                "and youtube.json. Check it with `node ~/video-engine/ve.mjs compile episodes/<slug>/scene.js /tmp/sb.json` (free) until it "
                "compiles cleanly, then run `npm run make -- episodes/<slug>` in shorts-factory: the channel voice narrates it and video-engine "
                "renders it (9:16 Short, 16:9 long video) to out/<slug>-hyperframes.mp4. To change how 3D videos look, edit ~/video-engine, "
                "not the Signal skill.")
    if is_iso(styles):
        return ("LOOK ticked in the Factory: Isometric. Do NOT write scenes: read shorts-factory/styles/iso-pastel/STYLE.md, VARIANTS.md, "
                "camera.js and objects.js, then write shorts-factory/episodes/<slug>/script.json ({\"style\": \"iso\", \"variant\": ..., \"topic\", "
                "\"format\", \"beats\": [{\"say\"}...]}), explainer.js (function explainer(ctx, W, H_, t) and function scoreSound(k)) and "
                "youtube.json. " + variant_line(variant_id) + " Run "
                "`node pipeline/make-iso.mjs episodes/<slug> --check` and LOOK at build-iso/storyboard.png; fix until the checks and the "
                "storyboard are clean, then `npm run make -- episodes/<slug>` (the channel voice narrates it; out/<slug>-hyperframes.mp4).")
    if list(styles) == ["signal"]:
        return ("LOOK ticked in the Factory: Signal (blue), rendered by the Tech Glow engine (owner, 2026-11-15). Do NOT write scenes: read "
                "shorts-factory/styles/tech-glow/STYLE.md and reference.js, then write shorts-factory/episodes/<slug>/script.json "
                "({\"style\": \"blue\", \"topic\", \"format\", \"beats\": [{\"say\"}...]}), explainer.js and youtube.json, matching the timing of "
                "styles/iso-pastel/examples/. Run `node pipeline/make-iso.mjs episodes/<slug> --check`, look at build-iso/storyboard.png, fix, "
                "then `npm run make -- episodes/<slug>`.")
    names = ", ".join(f'"{s}" ({(STYLES.get(s) or {}).get("label") or RETIRED.get(s, s)})' for s in styles)
    return (f"LOOKS ticked in the Factory: {names}. Use ONLY these looks, set \"styles\": {list(styles)} in script.json, and mix them scene by "
            f"scene as .claude/skills/explainer-short-style/references/mixing-styles.md says (read it, and the reference of each ticked look). "
            f"Story is for Shorts only; VS Code is for long algorithm videos only (explain on the blue board, then write and run the code in "
            f"VS Code); a look that does not fit this video is simply not used.").replace("'", '"')
