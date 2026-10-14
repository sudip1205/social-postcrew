"""Teams: several Researchers and several Writers work on every post, and the best combination is used.

The roster (state/roster.json) lists each member, their working style ("persona"), an optional model, and a
record of how their work turned out. After every run the roster is reviewed: a member whose recent work is
consistently bad is fired, and a new member is hired in their place. The new hire is briefed with lessons
drawn from the mistakes the team made, and those lessons are shown to every member of that role from then on.

Outcomes recorded per member and run:
  research  good = their sources were verified and every fact they gave was backed by a quote
  writer    good = their draft passed the checks, and the pre-review (and the Editor, if theirs was chosen)
            scored it at the passing bar with no red flag
"""
import threading
from collections import Counter
from datetime import datetime, timezone

_lock = threading.Lock()
ROLES = ("research", "writer")

# Working styles. The first two of each role are the founding team; the rest are used for new hires.
PERSONAS = {
    "research": [
        ("Ada", "Primary sources first: the vendor's own announcement, release notes, official docs or the "
                "standard itself. Prefer one page that states the facts plainly over many that repeat them."),
        ("Ravi", "Cross-checker: the primary source plus one reputable independent report that confirms the key "
                 "facts. Quote the exact sentences with numbers, dates and versions."),
        ("Mei", "Detail hunter: pricing pages, changelogs, GitHub READMEs and spec pages; pick pages that "
                "download as plain HTML and quote the sentences that carry the concrete details."),
        ("Omar", "Skeptic: look for what is actually shipped versus planned. Quote the qualifiers (beta, preview, "
                 "'plans to', 'up to') exactly, so nothing is overstated later."),
        ("Lena", "Documentation reader: official docs, quick-start guides and API references; quote the exact "
                 "commands, limits and requirements a reader needs to try it."),
    ],
    "writer": [
        ("Maya", "Precise explainer: lead with the single most concrete sourced fact, explain it plainly, keep "
                 "every qualifier from the sources, and give practical steps."),
        ("Leo", "Hands-on practitioner: open with what the reader can now do, then a short numbered how-to, and "
                "frame any implication as your own opinion ('I'd try...', 'If this takes off...')."),
        ("Nora", "Story-led but strict: one specific situation the reader recognises, then the sourced facts, "
                 "then what to do. Never states a possibility as a fact."),
        ("Sam", "Minimalist: short lines, few claims, each one backed by a quote; cuts anything the sources do "
                "not say. Hooks with a precise number or name from the sources."),
        ("Ivy", "Teacher: explains the 'why' in plain words, uses one concrete example, ends with a practical "
                "takeaway and a question practitioners can answer."),
    ],
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _member(role, name, persona, model=None, lessons_seen=0):
    return {"id": f"{role}-{name.lower()}", "role": role, "name": name, "persona": persona, "model": model,
            "hired_at": _now(), "lessons_seen": lessons_seen,
            "stats": {"tries": 0, "good": 0, "chosen": 0, "editor_passed": 0, "editor_failed": 0},
            "recent": []}


def load(ws):
    data = ws.state("roster", {})
    if not data.get("members"):
        data = {"members": [_member(r, *PERSONAS[r][i]) for r in ROLES for i in range(2)],
                "fired": [], "lessons": {r: [] for r in ROLES}}
        ws.save_state("roster", data)
    data.setdefault("fired", [])
    data.setdefault("lessons", {r: [] for r in ROLES})
    return data


def save(ws, data):
    ws.save_state("roster", data)


def active(ws, role, n):
    """The first n members of a role (the roster keeps hiring order)."""
    return [m for m in load(ws)["members"] if m["role"] == role][:max(1, n)]


def lessons(ws, role):
    return load(ws)["lessons"].get(role, [])


def persona_block(ws, member):
    ls = lessons(ws, member["role"])
    return (f"\n\nYOUR WORKING STYLE ({member['name']}): {member['persona']}"
            + ("\n\nLESSONS FROM THE TEAM'S PAST MISTAKES (follow every one):\n" + "\n".join(f"- {x}" for x in ls)
               if ls else ""))


def record(ws, member_id, run_id, good, score=None, problems=(), chosen=False, editor=None):
    """Add or update this run's outcome for a member. editor: True/False once the Editor judged their draft."""
    with _lock:
        data = load(ws)
        m = next((x for x in data["members"] if x["id"] == member_id), None)
        if not m:
            return
        r = next((x for x in m["recent"] if x["run"] == run_id), None)
        if r is None:
            r = {"run": run_id, "at": _now(), "good": good, "score": score, "problems": list(problems)[:6],
                 "chosen": False, "editor": None}
            m["recent"].append(r)
            m["stats"]["tries"] += 1
            m["stats"]["good"] += int(good)
        elif editor is None:  # a later attempt in the same run (a revision) replaces the earlier verdict
            m["stats"]["good"] += int(good) - int(r["good"])
            r.update(good=good, score=score if score is not None else r["score"],
                     problems=list(problems)[:6] or r["problems"])
        if chosen and not r["chosen"]:
            m["stats"]["chosen"] += 1
            r["chosen"] = True
        if editor is not None:  # the Editor has the last word on this run's work
            if r["editor"] is not None:
                m["stats"]["editor_passed" if r["editor"] else "editor_failed"] -= 1
            r["editor"] = editor
            m["stats"]["editor_passed" if editor else "editor_failed"] += 1
            m["stats"]["good"] += int(editor) - int(r["good"])
            r["good"] = editor
            if score is not None:
                r["score"] = score
            if problems:
                r["problems"] = list(problems)[:6]
        m["recent"] = m["recent"][-20:]
        save(ws, data)


def verdicts(m, window):
    return [r["good"] for r in m["recent"][-window:]]


def should_fire(m, cfg):
    t = cfg["team"]
    v = verdicts(m, t["fire_window"])
    return len(v) >= t["fire_window"] and sum(v) / len(v) < t["fire_min_success"]


def review(ws, cfg, llm=None, notify_user=True):
    """Fire members whose recent work is consistently bad and hire replacements briefed with lessons.
    Returns [(fired, hired)]."""
    changes = []
    data = load(ws)
    for m in list(data["members"]):
        if should_fire(m, cfg):
            changes.append(fire(ws, m["id"], cfg, llm=llm, reason="consistently bad output: "
                                f"{sum(verdicts(m, cfg['team']['fire_window']))} good of the last "
                                f"{cfg['team']['fire_window']} posts", notify_user=notify_user))
    return changes


def fire(ws, member_id, cfg, llm=None, reason="fired from the Studio", notify_user=True):
    """Remove a member, learn from their mistakes, and hire a replacement in the same role."""
    data = load(ws)
    m = next((x for x in data["members"] if x["id"] == member_id), None)
    if not m:
        raise KeyError(member_id)
    new_lessons = learn(m, cfg, llm, data["lessons"].get(m["role"], []), ws.secrets())
    with _lock:
        data = load(ws)
        data["members"] = [x for x in data["members"] if x["id"] != member_id]
        data["fired"] = (data["fired"] + [{**{k: m[k] for k in ("id", "role", "name", "persona", "hired_at", "stats")},
                                           "fired_at": _now(), "reason": reason, "lessons": new_lessons}])[-30:]
        data["lessons"][m["role"]] = list(dict.fromkeys(data["lessons"].get(m["role"], []) + new_lessons))[-12:]
        save(ws, data)
    hired = hire(ws, m["role"], avoid=m["name"])
    if notify_user:
        from ..notify import notify
        notify(ws, f"{m['name']} was replaced by {hired['name']}",
               f"{m['name']} ({m['role']}) was let go: {reason}. {hired['name']} joins with "
               f"{len(lessons(ws, m['role']))} lesson(s) from past mistakes.", level="warning",
               action={"label": "Open Crew", "tab": "team"},
               details={"rows": [("Role", m["role"]), ("Replaced", m["name"]), ("Why", reason),
                                 ("New member", f"{hired['name']}: {hired['persona'][:160]}")]
                        + [(f"Lesson {i}", t) for i, t in enumerate(new_lessons, 1)]})
    return m, hired


def hire(ws, role, avoid=None):
    with _lock:
        data = load(ws)
        taken = {x["name"] for x in data["members"]} | {avoid}
        recent_fired = [f["name"] for f in data["fired"][-len(PERSONAS[role]):]]
        pool = [p for p in PERSONAS[role] if p[0] not in taken]
        pool.sort(key=lambda p: p[0] in recent_fired)          # prefer styles that were never fired
        name, persona = pool[0] if pool else (f"{role.title()} {len(data['members']) + 1}", PERSONAS[role][0][1])
        base = name
        for n in range(2, 99):
            if f"{role}-{name.lower()}" not in {x["id"] for x in data["members"]}:
                break
            name = f"{base} {n}"
        m = _member(role, name, persona, lessons_seen=len(data["lessons"].get(role, [])))
        data["members"].append(m)
        save(ws, data)
        return m


LESSON_SCHEMA = {
    "type": "object",
    "properties": {"lessons": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5,
                               "description": "short, specific rules (imperative, under 200 chars each)"}},
    "required": ["lessons"], "additionalProperties": False,
}


def learn(m, cfg, llm=None, known=(), secrets=None):
    """Turn a member's recorded problems into a few rules for the next hire. Falls back to the most common
    problems as written when the model is unavailable."""
    probs = [p for r in m["recent"] if not r["good"] for p in r.get("problems", [])]
    if not probs:
        return []
    common = [p for p, _ in Counter(probs).most_common(12)]
    try:
        from ..llm import make_backend
        res = (llm or make_backend(cfg, secrets)).call(
            "supervisor", "You coach a content team. Reply only through the schema.",
            f"A {m['role']} on a LinkedIn writing team was replaced because of these recurring problems:\n"
            + "\n".join(f"- {p[:300]}" for p in common)
            + "\n\nRules the team already follows:\n" + ("\n".join(f"- {k}" for k in known) or "- (none)")
            + "\n\nWrite up to 5 NEW short rules that would have prevented these problems. Be specific and general "
              "enough to apply to any topic; do not repeat the existing rules.", LESSON_SCHEMA)
        out = [x.strip() for x in res.data.get("lessons", []) if 10 <= len(x.strip()) <= 240]
        if out:
            return out
    except Exception:
        pass
    return [f"Avoid this past problem: {p[:200]}" for p in common[:3]]


def remove_lesson(ws, role, index):
    with _lock:
        data = load(ws)
        ls = data["lessons"].get(role, [])
        if not 0 <= index < len(ls):
            raise KeyError(index)
        ls.pop(index)
        save(ws, data)
    return load(ws)
