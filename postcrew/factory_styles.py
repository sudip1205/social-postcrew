"""The looks a factory video may use, ticked in the Studio's Factory (owner, 2026-11-12).

Signal (the blue diagram look), Story (the cast, Shorts only) and VS Code (real typed and run code, long algorithm videos only). The
ticked looks are saved (state "factory-styles") and used both by the Factory chat and by the crew's Script Writer: it may use and mix
only those, as the skill's references/mixing-styles.md says, and `npm run make` refuses any other look.
"""
STYLES = {
    "signal": {"label": "Signal (blue)", "icon": "insights", "what": "the dark-blue diagram look: boards, traces, tables (Shorts and long videos)"},
    "story": {"label": "Story (cast)", "icon": "groups", "what": "the cast acting out an everyday story in a fitting set (Shorts only)"},
    "code": {"label": "VS Code", "icon": "code", "what": "real VS Code, the code typed and run, the camera zooming on it (long algorithm videos only)"},
    "3d": {"label": "3D (Three.js)", "icon": "view_in_ar",
           "what": "the whole video made by the 3D explainer pipeline and its own agents (Shorts and long videos); it is not mixed with the other looks"},
}
SOLO = "3d"   # makes the whole video by itself: ticked alone (owner, 2026-11-13)
DEFAULT = ["signal"]   # owner, 2026-11-13: the blue look only, unless Story or VS Code is ticked in the Factory
STATE = "factory-styles"


def ticked(ws):
    got = [s for s in (ws.state(STATE, {}) or {}).get("styles", DEFAULT) if s in STYLES]
    return got or list(DEFAULT)


def save(ws, styles):
    got = [s for s in STYLES if s in (styles or [])]
    if not got:
        raise ValueError("tick at least one look")
    if SOLO in got and len(got) > 1:
        raise ValueError("3D makes the whole video with its own pipeline: tick it on its own, or untick it to mix the other looks")
    ws.save_state(STATE, {"styles": got})
    return got


def options(ws):
    on = set(ticked(ws))
    return [{"id": k, **v, "on": k in on} for k, v in STYLES.items()]


def is_3d(styles):
    return list(styles) == [SOLO]


def instruction(styles):
    """The line the Script Writer (and the Factory chat) gets about the looks."""
    if is_3d(styles):
        return ("LOOK ticked in the Factory: 3D (Three.js). Do NOT write scenes: the 3D pipeline in ~/Youtube/youtube-3d plans, writes, directs and "
                "renders the whole video with its own agents. For a new video, write shorts-factory/episodes/<slug>/script.json as "
                "{\"style\": \"3d\", \"topic\": \"<the topic as a viewer would search it>\", \"notes\": \"<angle, what to focus on>\", "
                "\"format\": \"short\" (or \"long\"), \"seconds\": 55 (or about 480 for long)}, then run `npm run make -- episodes/<slug>` in "
                "shorts-factory (it takes 15-40 minutes; run it in the background and report when out/<slug>-hyperframes.mp4 exists). To change "
                "how 3D videos look, edit ~/Youtube/youtube-3d (knowledge/lessons.md, prompts/), not the Signal skill.")
    names = ", ".join(f'"{s}" ({STYLES[s]["label"]})' for s in styles)
    return (f"LOOKS ticked in the Factory: {names}. Use ONLY these looks, set \"styles\": {list(styles)} in script.json, and mix them scene by "
            f"scene as .claude/skills/explainer-short-style/references/mixing-styles.md says (read it, and the reference of each ticked look). "
            f"Story is for Shorts only; VS Code is for long algorithm videos only (explain on the blue board, then write and run the code in "
            f"VS Code); a look that does not fit this video is simply not used.").replace("'", '"')
