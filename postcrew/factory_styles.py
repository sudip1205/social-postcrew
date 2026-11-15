"""The looks a factory video may use, ticked in the Studio's Factory (owner, 2026-11-12).

Signal (the blue diagram look), Story (the cast, Shorts only) and VS Code (real typed and run code, long algorithm videos only). The
ticked looks are saved (state "factory-styles") and used both by the Factory chat and by the crew's Script Writer: it may use and mix
only those, as the skill's references/mixing-styles.md says, and `npm run make` refuses any other look.
"""
STYLES = {
    "signal": {"label": "Signal (blue)", "icon": "insights", "what": "the dark-blue diagram look: boards, traces, tables (Shorts and long videos)"},
    "story": {"label": "Story (cast)", "icon": "groups", "what": "the cast acting out an everyday story in a fitting set (Shorts only)"},
    "code": {"label": "VS Code", "icon": "code", "what": "real VS Code, the code typed and run, the camera zooming on it (long algorithm videos only)"},
    "3d": {"label": "3D (isometric)", "icon": "view_in_ar",
           "what": "isometric 3D explainer rendered by video-engine: the Script Writer writes the storyboard, the channel voice narrates "
                   "(Shorts 9:16, long videos 16:9); it is not mixed with the other looks"},
    "iso": {"label": "Isometric (pastel)", "icon": "deployed_code",
            "what": "the owner's Isometric Pastel reference style: a hand-drawn 2D-canvas isometric world the camera glides along, with "
                    "synced sound effects (styles/iso-pastel); the Script Writer writes the animation; it is not mixed with the other looks"},
}
SOLO = "3d"   # makes the whole video by itself: ticked alone (owner, 2026-11-13; video-engine since 2026-11-14)
SOLOS = ("3d", "iso")   # every look that makes the whole video by itself (Isometric Pastel: owner, 2026-11-14)
DEFAULT = ["signal"]   # owner, 2026-11-13: the blue look only, unless Story or VS Code is ticked in the Factory
STATE = "factory-styles"


def ticked(ws):
    got = [s for s in (ws.state(STATE, {}) or {}).get("styles", DEFAULT) if s in STYLES]
    return got or list(DEFAULT)


def save(ws, styles):
    got = [s for s in STYLES if s in (styles or [])]
    if not got:
        raise ValueError("tick at least one look")
    for solo in SOLOS:
        if solo in got and len(got) > 1:
            raise ValueError(f"{STYLES[solo]['label']} makes the whole video with its own pipeline: tick it on its own, or untick it to mix "
                             "the other looks")
    ws.save_state(STATE, {"styles": got})
    return got


def options(ws):
    on = set(ticked(ws))
    return [{"id": k, **v, "on": k in on} for k, v in STYLES.items()]


def is_3d(styles):
    return list(styles) == [SOLO]


def is_iso(styles):
    return list(styles) == ["iso"]


def instruction(styles):
    """The line the Script Writer (and the Factory chat) gets about the looks."""
    if is_3d(styles):
        return ("LOOK ticked in the Factory: 3D (isometric, video-engine). Do NOT write scenes: write the storyboard program "
                "shorts-factory/episodes/<slug>/scene.js (function build(sb) {...}) following ~/video-engine/RULES.md, plus "
                "shorts-factory/episodes/<slug>/script.json as {\"style\": \"3d\", \"topic\": \"<topic>\", \"format\": \"short\" (or \"long\")} "
                "and youtube.json. Check it with `node ~/video-engine/ve.mjs compile episodes/<slug>/scene.js /tmp/sb.json` (free) until it "
                "compiles cleanly, then run `npm run make -- episodes/<slug>` in shorts-factory: the channel voice narrates it and video-engine "
                "renders it (9:16 Short, 16:9 long video) to out/<slug>-hyperframes.mp4. To change how 3D videos look, edit ~/video-engine, "
                "not the Signal skill.")
    if is_iso(styles):
        return ("LOOK ticked in the Factory: Isometric (pastel). Do NOT write scenes: read shorts-factory/styles/iso-pastel/STYLE.md and "
                "reference.js, then write shorts-factory/episodes/<slug>/script.json ({\"style\": \"iso\", \"topic\", \"format\", \"beats\": "
                "[{\"say\"}...]}), explainer.js (function explainer(ctx, W, H_, t) and function scoreSound(k)) and youtube.json. Run "
                "`node pipeline/make-iso.mjs episodes/<slug> --check` and LOOK at build-iso/storyboard.png; fix until the checks and the "
                "storyboard are clean, then `npm run make -- episodes/<slug>` (the channel voice narrates it; out/<slug>-hyperframes.mp4).")
    names = ", ".join(f'"{s}" ({STYLES[s]["label"]})' for s in styles)
    return (f"LOOKS ticked in the Factory: {names}. Use ONLY these looks, set \"styles\": {list(styles)} in script.json, and mix them scene by "
            f"scene as .claude/skills/explainer-short-style/references/mixing-styles.md says (read it, and the reference of each ticked look). "
            f"Story is for Shorts only; VS Code is for long algorithm videos only (explain on the blue board, then write and run the code in "
            f"VS Code); a look that does not fit this video is simply not used.").replace("'", '"')
