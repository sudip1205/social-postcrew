"""Does the picture go with the voice? The check the Video Editor runs on a finished blackboard video.

For every scene it takes what was drawn and when (the timeline render/blackboard.py returns) and compares it with when the voice
says the same words: the real voice file is measured for its pauses (render/timeline.py), so a box that appears seconds before
or after its name is spoken is found. It also finds things drawn that the voice never mentions, an explanation that jumps
back to something already drawn, and long stretches where the voice talks over an unchanging board.

Nothing here touches the voice. `reorder` fixes the simplest mismatch (the arrows or bullets are listed in a different order
than the narrator explains them) without asking anyone.
"""
from . import timeline
from .scenes import parse_edge

LATE_S, EARLY_S, DEAD_AIR_S = 1.0, 1.5, 7.0
PENALTY = {"error": 15, "warn": 5}


def _audio(audios, i):
    return audios[i] if isinstance(audios, (list, tuple)) and i < len(audios) else None


def check(scenes, entries, audios=None):
    """(findings, score, measured): findings are {scene, kind, severity, thing, message}; score 0-100 (100 = in step);
    measured = every scene's words were timed on the real voice, not estimated."""
    findings, measured_all = [], True
    for i, (sc, t) in enumerate(zip(scenes, entries), 1):
        words, measured = timeline.voice_words(str(sc.get("narration", "")), t["seconds"], _audio(audios, i - 1))
        measured_all = measured_all and measured
        prev, last_end = 0.0, 0.0
        for th in t["things"]:
            cue = th.get("cue")
            if not cue:
                last_end = max(last_end, th["end"])
                continue
            said = timeline.cue_time(cue, words, after=prev)
            earlier = said is None
            if earlier:
                said = timeline.cue_time(cue, words)
            if said is None:
                bad = th.get("what") == "box"
                findings.append({"scene": i, "kind": "unspoken", "severity": "error" if bad else "warn", "thing": cue,
                                 "message": f"scene {i}: '{cue}' is drawn ({th.get('what') or 'item'}) but the voice never says it"})
                continue
            lag = th["start"] - said
            if earlier or lag > LATE_S:
                findings.append({"scene": i, "kind": "late" if not earlier else "order", "severity": "error", "thing": cue,
                                 "message": f"scene {i}: '{cue}' is drawn at {th['start']:.1f}s but the voice says it at {said:.1f}s"
                                            + (" (the voice explains it before the thing drawn just before it)" if earlier else "")})
            elif lag < -EARLY_S:
                findings.append({"scene": i, "kind": "early", "severity": "warn", "thing": cue,
                                 "message": f"scene {i}: '{cue}' is drawn at {th['start']:.1f}s, {-lag:.1f}s before the voice says it"})
            prev = max(prev, said) if not earlier else prev
            last_end = max(last_end, th["end"])
        starts = sorted(th["start"] for th in t["things"])
        if t["seconds"] > 9 and starts:
            stops = sorted(th["end"] for th in t["things"])
            gaps = [(a, b) for a, b in zip(stops, starts[1:]) if b - a > DEAD_AIR_S] + \
                   ([(stops[-1], t["seconds"])] if t["seconds"] - stops[-1] > DEAD_AIR_S + 0.5 else [])
            if gaps:
                a, b = max(gaps, key=lambda g: g[1] - g[0])
                findings.append({"scene": i, "kind": "dead_air", "severity": "warn", "thing": "",
                                 "message": f"scene {i}: nothing changes on the board from {a:.0f}s to {b:.0f}s while the voice talks"})
    score = max(0, 100 - sum(PENALTY[f["severity"]] for f in findings))
    return findings, score, measured_all


def reorder(scene, words):
    """The scene with its arrows (or bullets) listed in the order the voice explains them; None when it already is."""
    def when(label, after=0.0):
        return timeline.cue_time(label, words, after=after)

    if scene.get("layout") == "diagram":
        nodes = [str(n) for n in scene.get("nodes") or []]
        keyed = []
        for k, e in enumerate(scene.get("edges") or []):
            p = parse_edge(e, nodes)
            t = (when(p[2]) if p and p[2] else None)
            if t is None and p:
                t = when(nodes[p[1]])
            keyed.append((t if t is not None else float("inf"), k, e))
        if all(t == float("inf") for t, _k, _e in keyed):
            return None
        order = [e for _t, _k, e in sorted(keyed)]
        return dict(scene, edges=order) if order != list(scene.get("edges") or []) else None
    if scene.get("layout") == "points" and scene.get("items"):
        keyed = [(when(it), k, it) for k, it in enumerate(scene["items"])]
        if any(t is None for t, _k, _it in keyed):
            return None
        order = [it for _t, _k, it in sorted(keyed)]
        return dict(scene, items=order) if order != list(scene["items"]) else None
    return None


def autofix(scenes, entries, audios=None):
    """(scenes, changed): the order fixes for every scene whose things are explained in a different order than drawn."""
    out, changed = [dict(s) for s in scenes], []
    for i, (sc, t) in enumerate(zip(scenes, entries)):
        words, _m = timeline.voice_words(str(sc.get("narration", "")), t["seconds"], _audio(audios, i))
        new = reorder(sc, words)
        if new:
            out[i] = new
            changed.append(i)
    return out, changed
