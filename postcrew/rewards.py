"""Rewards: your decisions in the Queue teach the crew. A post you approve or publish earns every agent that worked on it points; a post you
veto costs them points, and your reason is kept. Each agent then reads its own record, and the agents that shape a video (the Script
Writer, the Creative Director and the Storyboard Artist) read the scene-by-scene outline of your best-rated published video, so new videos
follow the same kind of script and graphics, and the list of what you vetoed and why, so they do not repeat it.

Files, in the workspace:
    state/rewards.json            points per agent (and per writer) and what was decided for each post
    motion/exemplars/<post>.json  the final script (after the Storyboard Artist and any redraws) of every video you approved

A decision counts once per post: approving and then publishing is one reward; a veto after an approval replaces the reward with the
penalty; restoring a vetoed post takes the penalty back.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REWARD, PENALTY = 10, -10
SKIP = ("credentials", "publisher", "supervisor")   # steps that do not shape the work
SHAPERS = ("writer", "direction", "graphics")        # the agents that read the exemplar
GOOD, BAD = ("approved", "published"), ("vetoed",)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file(ws):
    return Path(ws.root) / "state" / "rewards.json"


def load(ws):
    try:
        d = json.loads(_file(ws).read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("agents", {})
    d.setdefault("posts", {})
    return d


def _save(ws, d):
    p = _file(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1))


def _ex_dir(ws):
    return Path(ws.root) / "motion" / "exemplars"


def contributors(ws, run_id):
    """The steps that did work on a run (passed), and the writer whose draft was chosen: ["writer", "writer:writer-nora", ...]."""
    rd = Path(ws.runs_dir) / str(run_id or "")
    try:
        st = json.loads((rd / "status.json").read_text())
    except (OSError, ValueError):
        return []
    out = [k for k, v in (st.get("steps") or {}).items() if v.get("state") == "passed" and k not in SKIP]
    try:
        author = json.loads((rd / "writer.json").read_text()).get("author")
        if author and "writer" in out:
            out.append(f"writer:{author}")
    except (OSError, ValueError):
        pass
    return out


def record(ws, post, outcome, reason=""):
    """Your decision on a post: "approved", "published", "vetoed" or "restored". Returns the points applied now (0 when nothing changed)."""
    if not post or not post.get("run_id") or post.get("source") == "own":
        return 0
    d = load(ws)
    pid = post["id"]
    prev = d["posts"].get(pid) or {}
    want = REWARD if outcome in GOOD else PENALTY if outcome in BAD else 0
    if outcome in GOOD and prev.get("delta") == REWARD:
        return 0                                   # approved, then published: one reward
    delta = want - (prev.get("delta") or 0)
    agents = prev.get("agents") or contributors(ws, post["run_id"])
    if not delta or not agents:
        return 0
    for a in agents:
        r = d["agents"].setdefault(a, {"points": 0, "published": 0, "vetoed": 0, "history": []})
        r["points"] += delta
        if outcome in GOOD:
            r["published"] += 1
        if prev.get("delta") == REWARD:
            r["published"] = max(0, r["published"] - 1)
        if outcome in BAD:
            r["vetoed"] += 1
        if prev.get("delta") == PENALTY:
            r["vetoed"] = max(0, r["vetoed"] - 1)
        r["history"] = (r["history"] + [{"post": pid, "topic": post.get("topic", ""), "outcome": outcome, "delta": delta,
                                          "reason": reason[:300], "at": now()}])[-30:]
    d["posts"][pid] = {"delta": want, "outcome": outcome, "agents": agents, "reason": reason[:300], "topic": post.get("topic", ""),
                       "platform": post.get("platform", "linkedin"), "run_id": post["run_id"], "at": now()}
    _save(ws, d)
    if want == REWARD and post.get("platform") == "youtube":
        save_exemplar(ws, post)
    ex = _ex_dir(ws) / f"{_safe(pid)}.json"
    if ex.exists():   # its points follow your decision
        e = json.loads(ex.read_text())
        e.update(points=want, outcome=outcome, reason=reason[:300])
        ex.write_text(json.dumps(e, indent=1))
    return delta


def _safe(pid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(pid))[:120]


# ---------- exemplars ----------
def final_script(ws, run_id):
    """The scenes as they were drawn: the final script the Publisher saved, else the approved script."""
    rd = Path(ws.runs_dir) / str(run_id)
    for name in ("script.final.json", "writer.json"):
        try:
            s = json.loads((rd / name).read_text())
            if s.get("scenes"):
                return s
        except (OSError, ValueError):
            continue
    return None


def save_exemplar(ws, post):
    s = final_script(ws, post["run_id"])
    if not s:
        return None
    keep = ("part", "layout", "on_screen", "narration", "items", "nodes", "edges", "cells", "code", "direction")
    scenes = [{k: sc.get(k) for k in keep if sc.get(k)} for sc in s["scenes"]]
    yt = post.get("youtube") or {}
    e = {"post": post["id"], "run_id": post["run_id"], "topic": post.get("topic", ""), "category": post.get("category", ""),
         "format": yt.get("format", "short"), "seconds": yt.get("seconds"), "concept": s.get("concept", ""), "title": s.get("title", ""),
         "scenes": scenes, "words": len(" ".join(sc.get("narration", "") for sc in scenes).split()), "points": REWARD,
         "outcome": "approved", "pinned": False, "saved_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
    d = _ex_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    old = d / f"{_safe(post['id'])}.json"
    if old.exists():
        e["pinned"] = json.loads(old.read_text()).get("pinned", False)
    old.write_text(json.dumps(e, indent=1))
    return e


def exemplars(ws):
    out = []
    for p in sorted(_ex_dir(ws).glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except ValueError:
            continue
    return out


def pin(ws, post_id, on=True):
    """Make one approved video THE model the crew follows (or stop)."""
    p = _ex_dir(ws) / f"{_safe(post_id)}.json"
    if not p.exists():
        raise KeyError(f"no approved video {post_id}")
    for e in exemplars(ws):   # one pinned at a time
        if e.get("pinned") and e["post"] != post_id:
            e["pinned"] = False
            (_ex_dir(ws) / f"{_safe(e['post'])}.json").write_text(json.dumps(e, indent=1))
    e = json.loads(p.read_text())
    e["pinned"] = bool(on)
    p.write_text(json.dumps(e, indent=1))
    return e


def best_exemplar(ws, fmt="short", category=None):
    """The video to follow: the pinned one, else the best-rated approved one of this format (this topic first), newest first."""
    pool = [e for e in exemplars(ws) if e.get("points", 0) > 0 and e.get("format", "short") == fmt]
    if not pool:
        return None
    pinned = [e for e in pool if e.get("pinned")]
    if pinned:
        return pinned[0]
    return max(pool, key=lambda e: (e.get("points", 0), e.get("category") == category, e.get("saved_at", "")))


def outline(e, words=12):
    """A compact scene-by-scene outline of an exemplar: what to copy (the shape), never its words."""
    rows = []
    for i, sc in enumerate(e["scenes"], 1):
        narr = " ".join((sc.get("narration") or "").split()[:words])
        pic = sc.get("on_screen") or ", ".join((sc.get("nodes") or sc.get("items") or [])[:3])
        d = (sc.get("direction") or {}).get("visual")
        rows.append(f" {i:>2}. {sc.get('part') or '-'} / {sc.get('layout') or '-'}: {pic[:50]}"
                    + (f" | shows {d[:70]}" if d else "") + (f" | \"{narr}...\"" if narr else ""))
    return "\n".join(rows)


def prompt_block(ws, agent_id, platform="linkedin", fmt="short", category=None, member=None):
    """What an agent reads about its past work: its points, what you vetoed and why, and (the shaping agents of a video) the outline of
    the video to follow. Empty until you have decided on something."""
    d = load(ws)
    parts = []
    r = d["agents"].get(agent_id)
    m = d["agents"].get(f"{agent_id}:{member}") if member else None
    if r or m:
        rec = m or r
        parts.append(f"YOUR TRACK RECORD (the owner's decisions on work you did): {rec['points']:+d} points, {rec['published']} published, "
                     f"{rec['vetoed']} vetoed.")
    vetoes = [p for p in d["posts"].values() if p.get("delta", 0) < 0 and p.get("platform") == platform and agent_id in p.get("agents", [])]
    if vetoes:
        parts.append("VETOED BY THE OWNER (do not repeat what made these fail):\n"
                     + "\n".join(f"- \"{v['topic'][:80]}\"" + (f": {v['reason']}" if v.get("reason") else ": no reason given")
                                 for v in sorted(vetoes, key=lambda v: v.get("at", ""))[-4:]))
    if platform == "youtube" and agent_id in SHAPERS:
        e = best_exemplar(ws, fmt, category)
        if e:
            parts.append(f"THE OWNER'S {'CHOSEN MODEL' if e.get('pinned') else 'BEST-RATED PUBLISHED'} VIDEO ({e['points']:+d}): \"{e['topic']}\" "
                         f"({len(e['scenes'])} scenes, {e['words']} words). Make this video the same KIND of video: the same order of parts, the "
                         f"same kinds of pictures for the same jobs, the same rhythm and the same way of talking to the viewer. A new topic, so "
                         f"new words and new pictures of it: never copy its sentences."
                         + (f"\nIts visual thread: {e['concept']}" if e.get("concept") else "")
                         + "\nScene by scene (part / layout: on screen | what it shows | how the narration starts):\n" + outline(e))
    return "\n\n".join(parts)
