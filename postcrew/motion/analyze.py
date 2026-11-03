"""The AI half of Motion Studio: a vision model describes a reference video from its contact sheets, and merges the approved references
into one house style. Called from the command line (`postcrew motion analyze`, `postcrew motion style --build`) and the Studio API.

The model sees frames and measured facts only. It is told to describe production technique in general terms (pacing, layout, motion,
how a scene is built) and never to transcribe a reference's script or describe its branding, so a profile cannot be used to copy a video.
"""
import json

from .. import platforms
from ..llm import LLMError, make_backend
from . import library as lib

AGENT = "motion"   # its model, time limit and budget: llm.agents.motion in config.json

SYSTEM = """You are a motion-graphics director studying a reference explainer video so a production crew can learn its TECHNIQUE.
You see contact sheets: one frame per shot, labelled with the shot number and its time. You also get measured facts (cuts per minute,
seconds per shot, how much of the screen is filled, main colours) and, sometimes, the narration.

Describe production technique in general, reusable terms: how a scene is built and what it is for, how text is placed and sized,
what moves and how, how shots connect, the rhythm. Never write out the reference's script or on-screen sentences beyond a few words,
never describe logos, channel branding, faces or characters in a way that would let someone copy them, and never name the creator.
Patterns are abstract recipes another video on a different topic could use ("a big number counts up, then a short label explains it").

Be honest about weaknesses (tiny text, cluttered frames, slow stretches): the crew should learn what to avoid as well."""

SCENE = {"type": "object", "properties": {
    "shot": {"type": "integer"}, "purpose": {"type": "string", "enum": lib.PURPOSES},
    "picture": {"type": "string", "description": "what is on screen, in general terms"},
    "on_screen_text": {"type": "string", "description": "how much text and how it is set (size, position), not the words"},
    "motion": {"type": "string"}, "transition_in": {"type": "string"},
    "energy": {"type": "string", "enum": ["low", "medium", "high"]}},
    "required": ["shot", "purpose", "picture", "on_screen_text", "motion", "transition_in", "energy"], "additionalProperties": False}
PATTERN = {"type": "object", "properties": {"name": {"type": "string"}, "purpose": {"type": "string", "enum": lib.PURPOSES},
                                            "recipe": {"type": "string"}},
           "required": ["name", "purpose", "recipe"], "additionalProperties": False}
PROFILE = {"type": "object", "properties": {
    "profile_name": {"type": "string"},
    "visual_system": {"type": "object", "properties": {"background": {"type": "string"}, "palette": {"type": "array", "items": {"type": "string"}},
                                                       "typography": {"type": "string"}, "composition": {"type": "string"}},
                      "required": ["background", "palette", "typography", "composition"]},
    "motion_language": {"type": "object", "properties": {"preferred": {"type": "array", "items": {"type": "string"}},
                                                         "transitions": {"type": "array", "items": {"type": "string"}},
                                                         "motion_intensity": {"type": "string"}},
                        "required": ["preferred", "transitions", "motion_intensity"]},
    "storytelling": {"type": "object", "properties": {"hook_type": {"type": "string"}, "scene_rhythm": {"type": "string"},
                                                      "ending": {"type": "string"}},
                     "required": ["hook_type", "scene_rhythm", "ending"]},
    "constraints": {"type": "object", "properties": {"avoid": {"type": "array", "items": {"type": "string"}}}, "required": ["avoid"]}},
    "required": ["profile_name", "visual_system", "motion_language", "storytelling", "constraints"]}
ANALYSIS = {"type": "object", "properties": {
    "summary": {"type": "string"}, "scenes": {"type": "array", "items": SCENE, "maxItems": 40}, "profile": PROFILE,
    "patterns": {"type": "array", "items": PATTERN, "maxItems": 10},
    "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    "weaknesses": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["summary", "scenes", "profile", "patterns", "strengths", "weaknesses"], "additionalProperties": False}
HOUSE = {"type": "object", "properties": {"profile": PROFILE, "patterns": {"type": "array", "items": PATTERN, "maxItems": 14},
                                          "why": {"type": "string"}},
         "required": ["profile", "patterns", "why"], "additionalProperties": False}


def backend(ws, llm=None):
    if llm:
        return llm
    cfg = platforms.view(ws.config(), "youtube")
    if cfg["llm"]["backend"] == "demo":
        raise lib.fr.FrameError("the demo AI cannot look at videos: choose a real AI provider in Settings")
    return make_backend(cfg, ws.secrets())


def analyze(ws, rid, llm=None, log=print):
    """Measure a reference, then have the vision model describe it. Leaves it in profile_review for you to approve."""
    L = lib.Library(ws)
    try:
        m = L.measure_reference(rid, log)
        meta = L.meta(rid)
        facts = m["facts"]
        narration = (m["transcript"] or {}).get("text", "")
        prompt = (f"REFERENCE: {meta['title']} ({meta['seconds']:.0f}s, {meta['width']}x{meta['height']}, {facts['shots']} shots)\n"
                  f"MEASURED: {json.dumps(facts)}\n"
                  f"PER SHOT (start-end s, fill = share of the picture area with content, height = share of its height used): "
                  + "; ".join(f"S{s['shot']} {s['start']}-{s['end']} fill {s['fill']} height {s['height']}" for s in m["shots"])
                  + (f"\nNARRATION (for pacing and structure only; never copy it): {narration[:3000]}" if narration else "\nNARRATION: not transcribed")
                  + (f"\nOWNER'S NOTES: {meta['notes']}" if meta.get("notes") else ""))
        log(f"asking the vision model about {len(m['sheets'])} contact sheet(s)")
        res = backend(ws, llm).call(AGENT, SYSTEM, prompt, ANALYSIS, cwd=str(L.refs / rid), images=m["sheets"])
        a = dict(res.data, measured=facts)
        meta = L.save_analysis(rid, a)
        log(f"analysed: {len(a.get('scenes') or [])} scenes, {len(a.get('patterns') or [])} patterns (${res.cost_usd:.3f}). "
            f"Review it, then `postcrew motion approve {rid}`")
        return meta, a
    except (LLMError, lib.fr.FrameError, OSError, ValueError) as e:
        L.set_status(rid, "failed", str(e)[:300])
        raise


def build_house(ws, llm=None, log=print):
    """Merge the approved references into a new version of the house style. The built-in quality floor always stays."""
    L = lib.Library(ws)
    refs = L.approved()
    if not refs:
        raise ValueError("no approved reference yet: add one (`postcrew motion add`), analyse it and approve it first")
    base = lib.DEFAULT_HOUSE
    prompt = ("Merge these approved reference profiles into ONE coherent house style for a channel of short coding and system-design "
              "explainers. Keep what they share and what works on a phone; drop what conflicts or what the weaknesses warn against. "
              "Patterns must stay abstract. The quality floor below always applies and cannot be relaxed.\n\n"
              f"QUALITY FLOOR: {json.dumps(base['constraints'])}; text at least {base['visual_system']['min_text_px']} px\n\n"
              + "\n\n".join(f"REFERENCE {m['id']} ({m['title']}):\nprofile: {json.dumps(a['profile'])}\npatterns: {json.dumps(a.get('patterns'))}\n"
                            f"strengths: {a.get('strengths')}\nweaknesses: {a.get('weaknesses')}\nmeasured: {json.dumps(a.get('measured'))}"
                            for m, a in refs))
    log(f"merging {len(refs)} approved reference(s) into a house style")
    res = backend(ws, llm).call(AGENT, SYSTEM, prompt, HOUSE, cwd=str(L.root))
    prof = res.data["profile"]
    shot = [a.get("measured", {}).get("shot_seconds") for _m, a in refs if a.get("measured", {}).get("shot_seconds")]
    cpm = [a.get("measured", {}).get("cuts_per_minute") for _m, a in refs if a.get("measured", {}).get("cuts_per_minute")]
    style = json.loads(json.dumps(base))
    style.update(profile_name=prof.get("profile_name") or "House style", why=res.data.get("why", ""))
    style["visual_system"].update({k: v for k, v in prof["visual_system"].items() if k != "palette"},
                                  reference_palette=prof["visual_system"].get("palette", []))   # the video look keeps its own colours
    style["motion_language"].update(prof["motion_language"])
    style["storytelling"].update(prof["storytelling"])
    style["constraints"]["avoid"] = list(dict.fromkeys(base["constraints"]["avoid"] + prof["constraints"].get("avoid", [])))[:14]
    style["patterns"] = res.data["patterns"] or base["patterns"]
    if shot:   # measured, not guessed: the rhythm of the references, kept within what a teaching video can carry
        style["pacing"] = {"shot_seconds": round(min(max(sum(shot) / len(shot), 1.8), 5.0), 1),
                           "cuts_per_minute": round(sum(cpm) / len(cpm), 1) if cpm else base["pacing"]["cuts_per_minute"]}
        style["motion_language"]["max_still_seconds"] = round(min(max(style["pacing"]["shot_seconds"] * 1.3, 2.5), 5.0), 1)
    saved = L.save_house(style, [m["id"] for m, _a in refs])
    log(f"house style v{saved['version']} saved (${res.cost_usd:.3f}): {saved['profile_name']}")
    return saved
