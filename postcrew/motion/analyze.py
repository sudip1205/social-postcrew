"""The AI half of Motion Studio: a vision model describes a reference video from its contact sheets, and merges the approved references
into one house style. Called from the command line (`postcrew motion analyze`, `postcrew motion style --build`) and the Studio API.

The model sees frames and measured facts only. It is told to describe production technique in general terms (pacing, layout, motion,
how a scene is built) and never to transcribe a reference's script or describe its branding, so a profile cannot be used to copy a video.
"""
import json
import shutil

from .. import platforms
from ..llm import LLMError, make_backend
from . import fetch as fetch_mod
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
SCRIPT_SYSTEM = """You are a script editor studying the narration of a reference explainer video so a writing crew can learn its CRAFT.
You get the transcript, the video's length and measured pace. Describe technique in general, reusable terms: how the hook works, the order of
the parts and how long each takes, how sentences are built, how the viewer is addressed, the devices (questions, contrasts, numbers, a
running example), how it ends. Never copy sentences: quote at most five words to point at a technique. Patterns are abstract recipes a
video on another topic could use ("open on the wrong answer most people give, then correct it"). Be honest about weaknesses."""

SCRIPT_PART = {"type": "object", "properties": {"part": {"type": "string"}, "purpose": {"type": "string", "enum": lib.PURPOSES},
                                                "share": {"type": "integer", "minimum": 0, "maximum": 100, "description": "% of the video"},
                                                "technique": {"type": "string"}},
               "required": ["part", "purpose", "share", "technique"], "additionalProperties": False}
SCRIPT_PROFILE = {"type": "object", "properties": {
    "hook_type": {"type": "string"}, "structure": {"type": "string", "description": "the parts in order, as one line"},
    "tone": {"type": "string"}, "sentence_style": {"type": "string"}, "pacing": {"type": "string"}, "ending": {"type": "string"},
    "rules": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "rules a writer can follow"}},
    "required": ["hook_type", "structure", "tone", "sentence_style", "pacing", "ending", "rules"], "additionalProperties": False}
SCRIPT_ANALYSIS = {"type": "object", "properties": {
    "summary": {"type": "string"}, "structure": {"type": "array", "items": SCRIPT_PART, "maxItems": 12},
    "devices": {"type": "array", "items": {"type": "string"}, "maxItems": 8}, "profile": SCRIPT_PROFILE,
    "patterns": {"type": "array", "items": PATTERN, "maxItems": 8},
    "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    "weaknesses": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["summary", "structure", "devices", "profile", "patterns", "strengths", "weaknesses"], "additionalProperties": False}

HOUSE = {"type": "object", "properties": {"profile": PROFILE, "patterns": {"type": "array", "items": PATTERN, "maxItems": 14},
                                          "script": SCRIPT_PROFILE,
                                          "script_patterns": {"type": "array", "items": PATTERN, "maxItems": 10},
                                          "why": {"type": "string"}},
         "required": ["profile", "patterns", "script", "script_patterns", "why"], "additionalProperties": False}


def backend(ws, llm=None):
    if llm:
        return llm
    cfg = platforms.view(ws.config(), "youtube")
    if cfg["llm"]["backend"] == "demo":
        raise lib.fr.FrameError("the demo AI cannot look at videos: choose a real AI provider in Settings")
    return make_backend(cfg, ws.secrets())


class AnalyzeError(RuntimeError):
    pass


def analyze_screen(ws, rid, llm=None, log=print):
    """Measure the reference's frames, then have the vision model describe its look and motion."""
    L = lib.Library(ws)
    if not L.video_path(rid):
        raise AnalyzeError("there is no video to look at: add the video file (or a URL with the screens selected)")
    m = L.measure_reference(rid, log)
    meta = L.meta(rid)
    facts = m["facts"]
    narration = L.transcript(rid)
    prompt = (f"REFERENCE: {meta['title']} ({meta['seconds']:.0f}s, {meta['width']}x{meta['height']}, {facts['shots']} shots)\n"
              f"MEASURED: {json.dumps(facts)}\n"
              f"PER SHOT (start-end s, fill = share of the picture area with content, height = share of its height used): "
              + "; ".join(f"S{s['shot']} {s['start']}-{s['end']} fill {s['fill']} height {s['height']}" for s in m["shots"])
              + (f"\nNARRATION (for pacing and structure only; never copy it): {narration[:3000]}" if narration else "\nNARRATION: none")
              + (f"\nOWNER'S NOTES: {meta['notes']}" if meta.get("notes") else ""))
    log(f"asking the vision model about {len(m['sheets'])} contact sheet(s)")
    res = backend(ws, llm).call(AGENT, SYSTEM, prompt, ANALYSIS, cwd=str(L.refs / rid), images=m["sheets"])
    log(f"screens analysed: {len(res.data.get('scenes') or [])} scenes, {len(res.data.get('patterns') or [])} patterns (${res.cost_usd:.3f})")
    return L.save_analysis(rid, "screen", dict(res.data, measured=facts))


def analyze_script(ws, rid, llm=None, log=print):
    """Have the model study the narration's craft from the transcript."""
    L = lib.Library(ws)
    meta = L.meta(rid)
    text = L.transcript(rid)
    if len(text.split()) < 20:
        raise AnalyzeError("there is no transcript to study: paste it, use a video with subtitles, or install faster-whisper")
    words = len(text.split())
    secs = float(meta.get("seconds") or 0)
    prompt = (f"REFERENCE: {meta['title']} ({secs:.0f}s, {words} words"
              + (f", {words / secs:.2f} words per second" if secs else "") + ")\n"
              + (f"OWNER'S NOTES: {meta['notes']}\n" if meta.get("notes") else "")
              + f"TRANSCRIPT (study it; never copy it):\n{text[:20000]}")
    log("studying the script")
    res = backend(ws, llm).call(AGENT, SCRIPT_SYSTEM, prompt, SCRIPT_ANALYSIS, cwd=str(L.refs / rid))
    log(f"script analysed: {len(res.data.get('structure') or [])} parts, {len(res.data.get('patterns') or [])} patterns (${res.cost_usd:.3f})")
    measured = {"words": words, "seconds": secs, **({"words_per_second": round(words / secs, 2)} if secs else {})}
    return L.save_analysis(rid, "script", dict(res.data, measured=measured))


def process(ws, rid, modes=("screen",), transcript="", llm=None, log=print):
    """The whole job for one reference: fetch it (a URL), find its transcript, analyse what was asked. Ends in profile_review (for you
    to approve) or failed, with the reason on the reference."""
    L = lib.Library(ws)
    modes = [m for m in lib.MODES if m in modes]
    if not modes:
        raise ValueError("choose what to analyse: screen, script or both")
    try:
        meta = L.meta(rid)
        L.update(rid, modes=modes, status_reason="")
        if transcript and transcript.strip():
            L.save_transcript(rid, transcript, "pasted")
        if meta.get("source_type") == "url" and (("screen" in modes and not L.video_path(rid)) or
                                                 ("script" in modes and not L.transcript(rid) and not L.video_path(rid))):
            L.set_status(rid, "downloading")
            work = L.refs / rid / "download"
            got = fetch_mod.fetch(meta["source_url"], work, video="screen" in modes, subs="script" in modes, log=log)
            fields = {}
            if got["title"] and meta.get("title") in ("", meta["source_url"]):   # you gave no title: the video's own
                fields["title"] = got["title"]
            if got["creator"] and not meta.get("creator"):
                fields["creator"] = got["creator"]
            L.update(rid, seconds=got["seconds"] or meta.get("seconds", 0), **fields)
            if got["video"]:
                L.attach_file(rid, got["video"])
            if got["transcript"] and not L.transcript(rid):
                L.save_transcript(rid, got["transcript"], "subtitles")
            shutil.rmtree(work, ignore_errors=True)
        L.set_status(rid, "analyzing")
        if "script" in modes and not L.transcript(rid) and L.video_path(rid):
            t = lib.transcribe(L.video_path(rid), log)
            if t and t.get("text"):
                L.save_transcript(rid, t["text"], "faster-whisper")
        done = []
        for m in modes:
            (analyze_screen if m == "screen" else analyze_script)(ws, rid, llm, log)
            done.append(m)
        L.set_status(rid, "profile_review")
        log(f"done: {', '.join(done)} analysed. Review it, then approve it")
        return L.meta(rid), L.analysis(rid)
    except (LLMError, lib.fr.FrameError, fetch_mod.FetchError, AnalyzeError, OSError, ValueError) as e:
        L.set_status(rid, "failed", str(e)[:400])
        raise


def analyze(ws, rid, llm=None, log=print):
    """The screens only (kept for callers of the first version)."""
    return process(ws, rid, ("screen",), llm=llm, log=log)


def build_house(ws, llm=None, log=print):
    """Merge the approved references into a new version of the house style. The built-in quality floor always stays."""
    L = lib.Library(ws)
    refs = L.approved()
    screens = [(m, a["screen"]) for m, a in refs if a.get("screen")]
    scripts = [(m, a["script"]) for m, a in refs if a.get("script")]
    if not screens and not scripts:
        raise ValueError("no approved reference yet: add one, analyse it and approve it first")
    base = lib.DEFAULT_HOUSE
    prompt = ("Merge these approved references into ONE coherent house style for a channel of short coding and system-design "
              "explainers: the visual profile and scene patterns from the SCREEN analyses, the script profile and script patterns from "
              "the SCRIPT analyses. Keep what they share and what works on a phone; drop what conflicts or what the weaknesses warn "
              "against. Patterns stay abstract. The quality floor below always applies and cannot be relaxed. When a side has no "
              "references, answer that side from the quality floor and the built-in style.\n\n"
              f"QUALITY FLOOR: {json.dumps(base['constraints'])}; text at least {base['visual_system']['min_text_px']} px\n"
              f"BUILT-IN STYLE: {json.dumps({k: base[k] for k in ('visual_system', 'motion_language', 'storytelling')})}\n\n"
              + "\n\n".join(f"SCREEN {m['id']} ({m['title']}):\nprofile: {json.dumps(a['profile'])}\npatterns: {json.dumps(a.get('patterns'))}\n"
                             f"strengths: {a.get('strengths')}\nweaknesses: {a.get('weaknesses')}\nmeasured: {json.dumps(a.get('measured'))}"
                             for m, a in screens)
              + "\n\n" + "\n\n".join(f"SCRIPT {m['id']} ({m['title']}):\nprofile: {json.dumps(a['profile'])}\nstructure: {json.dumps(a.get('structure'))}\n"
                                        f"patterns: {json.dumps(a.get('patterns'))}\nstrengths: {a.get('strengths')}\nweaknesses: {a.get('weaknesses')}\n"
                                        f"measured: {json.dumps(a.get('measured'))}" for m, a in scripts))
    log(f"merging {len(screens)} screen and {len(scripts)} script analyses into a house style")
    res = backend(ws, llm).call(AGENT, SYSTEM, prompt, HOUSE, cwd=str(L.root))
    style = json.loads(json.dumps(base))
    style.update(profile_name=res.data["profile"].get("profile_name") or "House style", why=res.data.get("why", ""))
    if screens:
        prof = res.data["profile"]
        style["visual_system"].update({k: v for k, v in prof["visual_system"].items() if k != "palette"},
                                      reference_palette=prof["visual_system"].get("palette", []))   # the video look keeps its own colours
        style["motion_language"].update(prof["motion_language"])
        style["storytelling"].update(prof["storytelling"])
        style["constraints"]["avoid"] = list(dict.fromkeys(base["constraints"]["avoid"] + prof["constraints"].get("avoid", [])))[:14]
        style["patterns"] = res.data["patterns"] or base["patterns"]
        shot = [a.get("measured", {}).get("shot_seconds") for _m, a in screens if a.get("measured", {}).get("shot_seconds")]
        cpm = [a.get("measured", {}).get("cuts_per_minute") for _m, a in screens if a.get("measured", {}).get("cuts_per_minute")]
        if shot:   # measured, not guessed: the rhythm of the references, kept within what a teaching video can carry
            style["pacing"] = {"shot_seconds": round(min(max(sum(shot) / len(shot), 1.8), 5.0), 1),
                               "cuts_per_minute": round(sum(cpm) / len(cpm), 1) if cpm else base["pacing"]["cuts_per_minute"]}
            style["motion_language"]["max_still_seconds"] = round(min(max(style["pacing"]["shot_seconds"] * 1.3, 2.5), 5.0), 1)
    if scripts:
        style["script"] = dict(res.data["script"], patterns=res.data.get("script_patterns") or [])
        wps = [a.get("measured", {}).get("words_per_second") for _m, a in scripts if a.get("measured", {}).get("words_per_second")]
        if wps:
            style["script"]["words_per_second"] = round(sum(wps) / len(wps), 2)
    saved = L.save_house(style, [m["id"] for m, _a in refs])
    log(f"house style v{saved['version']} saved (${res.cost_usd:.3f}): {saved['profile_name']}")
    return saved
