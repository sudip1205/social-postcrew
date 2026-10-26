"""Topic briefs: the full instructions for ONE post.

A plan entry used to hold only a topic and an angle. A brief adds everything a good post needs and the agents
adapt to it: the background, a real-world example, what the reader should be able to do afterwards, the writing
pattern, tone, must-include / avoid lists, references to read first, and what the picture or animation must show.

Briefs are plain data (a dict, stored under "brief" in the plan entry) and can be written as plain text, so a whole
day can be pasted into one box in the Studio or into a week file for `postcrew plan-import`:

    Context: Why OAuth assumptions break when the caller is an autonomous agent.
    Real-world example: A support agent that reads a customer's orders and issues refunds.
    Example type: scenario
    Takeaway: Give the agent its own short-lived, narrowly scoped token.
    Pattern: problem-story
    Must include:
      - token exchange
    Avoid:
      - vendor names
    Visual: system-flow
    Systems:
      - user | Customer | user
      - agent | Support agent | agent
      - gateway | API Gateway | api-gateway
    Flow:
      1. user > agent | Refund my order | request | "Refund order 1042" | The customer asks the agent
      2. agent > gateway | Call API | request | Authorization: Bearer <token> | The agent calls the API

Everything is optional. `normalize` checks and cleans a brief; `parse_text` / `to_text` convert to and from the
text form; the `*_block` helpers turn a brief into the instructions each agent receives.
"""
import re

LIMITS = {"context": 1500, "example": 1200, "takeaway": 400, "tone": 400, "question": 200, "notes": 800,
          "item": 220, "items": 10, "references": 8, "systems": 8, "steps": 14}
EXAMPLE_KINDS = ["scenario", "incident"]
VISUAL_TYPES = ["auto", "system-flow", "poster", "none"]

# What a box in the system animation can be (icons are drawn in render/sysflow.py).
COMPONENT_KINDS = ["user", "attacker", "browser", "mobile", "service", "api-gateway", "load-balancer", "database",
                   "cache", "queue", "idp", "vault", "firewall", "llm", "agent", "cdn", "worker", "storage",
                   "external"]
# What a message between two boxes can be (sets the colour of the packet).
STEP_KINDS = ["request", "response", "data", "token", "event", "attack", "error"]

_KIND_WORDS = [
    ("attacker", ("attacker", "hacker", "malicious", "adversary", "threat actor", "phisher")),
    ("agent", ("agent",)),
    ("llm", ("llm", "model", "gpt", "claude", "openai", "inference")),
    ("idp", ("idp", "identity provider", "auth server", "authorization server", "oauth", "oidc", "okta", "entra",
             "sso", "token service", "sts", "login service", "auth")),
    ("vault", ("vault", "secret", "kms", "hsm", "key store", "keystore", "credential store")),
    ("firewall", ("firewall", "waf")),
    ("api-gateway", ("gateway", "api proxy", "reverse proxy", "proxy")),
    ("load-balancer", ("load balancer", "balancer", "alb", "nlb", "elb")),
    ("cache", ("cache", "redis", "memcached", "memcache")),
    ("queue", ("queue", "kafka", "sqs", "rabbit", "broker", "pubsub", "pub/sub", "stream", "event bus")),
    ("database", ("database", "db", "postgres", "mysql", "sql", "dynamo", "mongo", "datastore", "data store")),
    ("storage", ("s3", "bucket", "storage", "blob", "file store", "object store")),
    ("cdn", ("cdn", "edge", "cloudfront", "akamai")),
    ("worker", ("worker", "job", "consumer", "batch", "cron", "scheduler")),
    ("browser", ("browser", "spa", "frontend", "front end", "web app", "website", "web client")),
    ("mobile", ("mobile", "ios", "android", "phone", "app")),
    ("user", ("user", "customer", "person", "employee", "admin", "human", "client")),
    ("external", ("third-party", "third party", "external", "partner", "saas", "payment", "provider")),
]

# ---------- writing patterns ----------
PATTERNS = {
    "problem-story": {
        "label": "Problem story",
        "summary": "A concrete failure first, then why it happened, then the fix.",
        "beats": ["Hook: the specific thing that went wrong, in one line",
                  "The situation: the real-world example in 2-3 plain sentences",
                  "What happened, step by step (the same steps and component names as the animation)",
                  "The fix, in one or two lines",
                  "The takeaway the reader can apply this week",
                  "One closing question"]},
    "how-it-works": {
        "label": "How it works",
        "summary": "Explain one mechanism by following a single request through it.",
        "beats": ["Hook: the problem this mechanism solves",
                  "What it is, in one or two plain sentences",
                  "The flow in numbered steps (same names and order as the animation)",
                  "The 2-3 design choices that matter and their trade-offs",
                  "When NOT to use it",
                  "One closing question"]},
    "before-after": {
        "label": "Before and after",
        "summary": "The naive design, what breaks, and the improved design side by side.",
        "beats": ["Hook: the cost of the naive design",
                  "Before: how it works and where it breaks (animation scene 1)",
                  "After: what changes and why it holds (animation scene 2)",
                  "What it costs you to switch",
                  "One closing question"]},
    "myth-vs-reality": {
        "label": "Myth vs reality",
        "summary": "A common belief, why it is tempting, and what actually happens.",
        "beats": ["Hook: state the belief the way people say it",
                  "Why people believe it",
                  "What actually happens (shown in the animation)",
                  "What to do instead",
                  "One closing question"]},
    "incident-lessons": {
        "label": "Incident lessons",
        "summary": "What a real, public incident teaches. Every fact must be sourced.",
        "beats": ["Hook: the most concrete sourced fact about the incident",
                  "What happened, in order, with the sources' own qualifiers",
                  "The root cause, in plain words",
                  "2-3 lessons written as suggestions",
                  "One closing question"]},
    "decision-guide": {
        "label": "Decision guide",
        "summary": "Two or three options, and the rules for choosing between them.",
        "beats": ["Hook: the decision people get wrong",
                  "The options in one line each",
                  "Rules of thumb: pick A when..., pick B when...",
                  "The real-world example applied to the rules",
                  "One closing question"]},
    "walkthrough": {
        "label": "Build walkthrough",
        "summary": "A finish-it-yourself build with exact steps and what you should see.",
        "beats": ["Hook: what you will have running at the end",
                  "What you need (free tools)",
                  "Numbered steps with exact commands or code",
                  "What you should see when it works",
                  "Where to take it next",
                  "One closing question"]},
    "checklist": {
        "label": "Checklist",
        "summary": "A short list of questions or checks the reader can save and reuse.",
        "beats": ["Hook: the mistake the checklist prevents",
                  "3-5 numbered checks, each with one line on why it matters",
                  "The real-world example showing one check being skipped",
                  "One closing question"]},
}
DEFAULT_PATTERN = "how-it-works"


class BriefError(ValueError):
    """The brief is not valid; the message says what to change."""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:30] or "item"


def guess_kind(label):
    low = f" {str(label).lower()} "
    for kind, words in _KIND_WORDS:
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
                return kind
    return "service"


def resolve_pattern(s):
    s = str(s or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[\s_]+", "-", s)
    if s in PATTERNS:
        return s
    for pid, p in PATTERNS.items():
        if s in (p["label"].lower(), slug(p["label"])):
            return pid
    raise BriefError(f"pattern {s!r} is not one of: {', '.join(PATTERNS)}")


# ---------- text format ----------
KEYMAP = {
    "topic": "topic", "angle": "angle", "category": "category", "date": "date",
    "context": "context", "background": "context",
    "example": "example", "real-world example": "example", "real world example": "example",
    "example type": "example_kind", "example kind": "example_kind",
    "takeaway": "takeaway", "reader takeaway": "takeaway", "goal": "takeaway", "outcome": "takeaway",
    "pattern": "pattern", "writing pattern": "pattern", "structure": "pattern",
    "tone": "tone", "tone notes": "tone", "voice": "tone", "style": "tone",
    "must include": "must_include", "include": "must_include", "must have": "must_include",
    "avoid": "avoid", "do not include": "avoid", "never": "avoid",
    "references": "references", "reference": "references", "sources": "references", "links": "references",
    "question": "question", "closing question": "question", "cta": "question", "ending question": "question",
    "visual": "visual_type", "visual type": "visual_type",
    "systems": "systems", "components": "systems", "system": "systems",
    "flow": "flow", "sequence": "flow", "steps": "flow", "message flow": "flow",
    "animation notes": "notes", "animation": "notes", "visual notes": "notes", "animation instructions": "notes",
    "image instructions": "notes",
}
_KEY_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z '\-/]{1,28}?)\s*:\s*(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")
_LIST_FIELDS = {"must_include", "avoid", "references"}
_TEXT_FIELDS = {"topic", "angle", "category", "date", "context", "example", "takeaway", "tone", "question", "notes"}


def _bullets(lines):
    items = []
    for ln in lines:
        if not ln.strip():
            continue
        m = _BULLET.match(ln)
        if m:
            items.append(m.group(1).strip())
        elif items:
            items[-1] += " " + ln.strip()   # a wrapped line belongs to the item above
        else:
            items.append(ln.strip())
    if len(items) == 1 and ";" in items[0]:
        items = [x.strip() for x in items[0].split(";") if x.strip()]
    return items


def _paragraphs(lines):
    return re.sub(r"[ \t]+", " ", re.sub(r"(?<!\n)\n(?!\n)", " ", "\n".join(lines).strip()))


def _parts(line):
    return [p.strip().strip('"') for p in line.split("|")]


def _parse_system(line):
    p = _parts(_BULLET.sub(r"\1", line, count=1))
    if not p or not p[0]:
        raise BriefError(f"empty system line: {line.strip()!r}")
    note = ""
    if len(p) == 1:
        sid, label, kind = slug(p[0]), p[0], guess_kind(p[0])
    elif len(p) == 2:
        label = p[0]
        sid = slug(label)
        kind, note = (p[1].lower(), "") if p[1].lower() in COMPONENT_KINDS else (guess_kind(label), p[1])
    elif len(p) >= 3 and p[2].lower() in COMPONENT_KINDS:      # id | Label | kind | note
        sid, label, kind, note = slug(p[0]), p[1] or p[0], p[2].lower(), p[3] if len(p) > 3 else ""
    elif p[1].lower() in COMPONENT_KINDS:                      # Label | kind | note
        label, kind, note = p[0], p[1].lower(), p[2]
        sid = slug(label)
    else:
        raise BriefError(f"system line {line.strip()!r}: use 'id | Label | kind | note' with kind one of "
                         f"{', '.join(COMPONENT_KINDS)}")
    return {"id": sid, "label": label, "kind": kind, "note": note}


def _parse_flow_line(line, scene):
    body = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
    p = _parts(body)
    ends = re.split(r"\s*(?:->|→|>)\s*", p[0])
    if len(ends) != 2 or not all(ends):
        raise BriefError(f"flow line {line.strip()!r}: start with 'from > to' (for example 'browser > gateway')")
    step = {"from": slug(ends[0]), "to": slug(ends[1]), "label": "", "kind": "request", "payload": "",
            "caption": "", "scene": scene, "_names": ends}
    rest = p[1:]
    if rest:
        step["label"] = rest[0]
    if len(rest) >= 2 and rest[1].lower() in STEP_KINDS:
        step["kind"] = rest[1].lower()
        rest = rest[2:]
    else:
        rest = rest[1:]
        step["kind"] = ""        # decided later from the direction of the message
    if rest:
        step["payload"] = rest[0]
    if len(rest) >= 2:
        step["caption"] = " | ".join(rest[1:])
    return step


def parse_text(text):
    """Plain text -> raw brief dict (not yet checked: pass it to `normalize`). Also returns "topic", "angle",
    "category" and "date" when the text has them (used by `plan-import`). Raises BriefError on malformed lines."""
    fields, order, cur, scene = {}, [], None, ""
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        m = _KEY_LINE.match(raw)
        key = KEYMAP.get(m.group(1).strip().lower()) if m else None
        in_flow = cur == "flow"
        if in_flow and m and m.group(1).strip().lower() == "scene":
            scene = m.group(2).strip()
            fields.setdefault("flow", []).append(("scene", scene))
            continue
        if key and not (in_flow and _BULLET.match(raw)):
            cur = key
            if key not in fields:
                fields[key] = []
                order.append(key)
            if key == "flow":
                scene = ""
            if m.group(2).strip():
                fields[key].append(m.group(2))
            continue
        if cur is not None:
            fields[cur].append(raw)
    out = {}
    for key, lines in fields.items():
        if key in _TEXT_FIELDS:
            out[key] = _paragraphs(lines)
        elif key in _LIST_FIELDS:
            out[key] = _bullets(lines)
        elif key == "example_kind":
            w = _paragraphs(lines).lower()
            out[key] = "incident" if w.startswith(("incident", "real")) else "scenario" if w else ""
        elif key == "visual_type":
            w = _paragraphs(lines).lower()
            out[key] = ("system-flow" if any(x in w for x in ("flow", "system", "animat", "diagram")) else
                        "poster" if any(x in w for x in ("poster", "image", "static")) else
                        "none" if w.startswith(("none", "no")) else "auto")
        elif key == "pattern":
            out[key] = resolve_pattern(_paragraphs(lines))
        elif key == "systems":
            out[key] = [_parse_system(ln) for ln in lines if ln.strip()]
        elif key == "flow":
            steps, scn = [], ""
            for ln in lines:
                if isinstance(ln, tuple):
                    scn = ln[1]
                elif ln.strip():
                    steps.append(_parse_flow_line(ln, scn))
            out[key] = steps
    return out


def to_text(brief):
    """A brief as the plain text `parse_text` reads, for showing and editing it."""
    b = brief or {}
    v = b.get("visual") or {}
    out = []

    def para(key, label):
        if b.get(key):
            out.append(f"{label}: {b[key]}")

    def lst(key, label):
        if b.get(key):
            out.append(f"{label}:")
            out.extend(f"  - {x}" for x in b[key])
    para("context", "Context")
    para("example", "Real-world example")
    if b.get("example") and b.get("example_kind"):
        out.append(f"Example type: {b['example_kind']}")
    para("takeaway", "Takeaway")
    if b.get("pattern"):
        out.append(f"Pattern: {b['pattern']}")
    para("tone", "Tone")
    lst("must_include", "Must include")
    lst("avoid", "Avoid")
    lst("references", "References")
    para("question", "Question")
    if v.get("type") and v["type"] != "auto":
        out.append(f"Visual: {v['type']}")
    if v.get("systems"):
        out.append("Systems:")
        out.extend("  - " + " | ".join([s["id"], s["label"], s["kind"]] + ([s["note"]] if s.get("note") else []))
                   for s in v["systems"])
    if v.get("flow"):
        out.append("Flow:")
        scn, n = None, 0
        for s in v["flow"]:
            if s.get("scene") and s["scene"] != scn:
                out.append(f"  Scene: {s['scene']}")
            scn = s.get("scene")
            n += 1
            out.append(f"  {n}. {s['from']} > {s['to']} | " + " | ".join(
                [s.get("label", ""), s.get("kind", "request"), s.get("payload", ""), s.get("caption", "")]).rstrip(" |"))
    if v.get("notes"):
        out.append(f"Animation notes: {v['notes']}")
    return "\n".join(out)


# ---------- checking ----------
def _text(raw, key, limit=None):
    v = str(raw.get(key) or "").strip()
    limit = limit or LIMITS[key]
    if len(v) > limit:
        raise BriefError(f"{key} is {len(v)} characters; keep it under {limit}")
    return v


def _items(raw, key, label):
    v = raw.get(key) or []
    if isinstance(v, str):
        v = _bullets(v.split("\n"))
    v = [str(x).strip() for x in v if str(x).strip()]
    cap = LIMITS["references"] if key == "references" else LIMITS["items"]
    if len(v) > cap:
        raise BriefError(f"{label}: at most {cap} items")
    for x in v:
        if len(x) > (400 if key == "references" else LIMITS["item"]):
            raise BriefError(f"{label}: an item is too long ({len(x)} characters): {x[:40]}...")
    return v


def normalize(raw):
    """Check and clean a raw brief; return the stored form (empty fields dropped). Raises BriefError."""
    if not raw:
        return {}
    if isinstance(raw, str):
        raw = parse_text(raw)
    if not isinstance(raw, dict):
        raise BriefError("a brief must be text or an object")
    out = {}
    for key in ("context", "example", "takeaway", "tone", "question"):
        v = _text(raw, key)
        if v:
            out[key] = v
    kind = str(raw.get("example_kind") or "").strip().lower()
    if kind and kind not in EXAMPLE_KINDS:
        raise BriefError(f"example type must be one of {EXAMPLE_KINDS}")
    if out.get("example"):
        out["example_kind"] = kind or "scenario"
    pat = resolve_pattern(raw.get("pattern"))
    if pat:
        out["pattern"] = pat
    for key, label in (("must_include", "Must include"), ("avoid", "Avoid"), ("references", "References")):
        v = _items(raw, key, label)
        if v:
            out[key] = v
    vis = raw.get("visual") if isinstance(raw.get("visual"), dict) else {}
    vtype = str(raw.get("visual_type") or vis.get("type") or "").strip().lower()
    if vtype and vtype not in VISUAL_TYPES:
        raise BriefError(f"visual must be one of {VISUAL_TYPES}")
    systems, flow = _systems(raw.get("systems", vis.get("systems"))), raw.get("flow", vis.get("flow")) or []
    flow = _flow(flow, systems)
    systems = _complete_systems(systems, flow)
    notes = _text(raw, "notes") or str(vis.get("notes") or "").strip()[:LIMITS["notes"]]
    visual = {k: v for k, v in (("type", vtype if vtype and vtype != "auto" else ""), ("systems", systems),
                                ("flow", flow), ("notes", notes)) if v}
    if visual:
        out["visual"] = visual
    if raw.get("generated"):
        out["generated"] = sorted({str(x) for x in raw["generated"]})
    return out


def _systems(v):
    out, seen = [], set()
    for s in (v or []):
        if not isinstance(s, dict):
            raise BriefError("each system needs an id, a label and a kind")
        label = str(s.get("label") or s.get("id") or "").strip()
        if not label:
            raise BriefError("a system has no label")
        sid = slug(s.get("id") or label)
        kind = str(s.get("kind") or "").strip().lower() or guess_kind(label)
        if kind not in COMPONENT_KINDS:
            raise BriefError(f"system {label!r}: kind {kind!r} is not one of {', '.join(COMPONENT_KINDS)}")
        if sid in seen:
            raise BriefError(f"system id {sid!r} is used twice")
        seen.add(sid)
        out.append({"id": sid, "label": label[:28], "kind": kind, "note": str(s.get("note") or "").strip()[:60]})
    if len(out) > LIMITS["systems"]:
        raise BriefError(f"at most {LIMITS['systems']} systems fit on the picture; merge some")
    return out


def _flow(v, systems):
    names = {}
    for s in systems:
        names[s["id"]] = s["id"]
        names[slug(s["label"])] = s["id"]
    out = []
    for i, st in enumerate(v, 1):
        if not isinstance(st, dict):
            raise BriefError(f"flow step {i} is not valid")
        a, b = slug(st.get("from", "")), slug(st.get("to", ""))
        if not st.get("from") or not st.get("to"):
            raise BriefError(f"flow step {i} needs a from and a to")
        if systems:
            for end in (a, b):
                if end not in names:
                    raise BriefError(f"flow step {i} uses '{end}', which is not listed under Systems")
            a, b = names[a], names[b]
        kind = str(st.get("kind") or "").strip().lower()
        if kind and kind not in STEP_KINDS:
            raise BriefError(f"flow step {i}: kind {kind!r} is not one of {', '.join(STEP_KINDS)}")
        out.append({k: v2 for k, v2 in (
            ("from", a), ("to", b), ("label", str(st.get("label") or "").strip()[:28]),
            ("kind", kind or "request"), ("payload", str(st.get("payload") or "").strip()[:80]),
            ("caption", str(st.get("caption") or "").strip()[:140]), ("scene", str(st.get("scene") or "").strip()[:40]),
            ("_names", st.get("_names"))) if v2 or k in ("from", "to", "kind")})
    if len(out) > LIMITS["steps"]:
        raise BriefError(f"at most {LIMITS['steps']} steps fit in a 45 second animation; split the topic")
    return out


def _complete_systems(systems, flow):
    """A flow without a Systems list is enough: every box the flow mentions is created (kind guessed)."""
    have = {s["id"] for s in systems}
    for st in flow:
        names = st.pop("_names", None) or [st["from"], st["to"]]
        for sid, name in zip((st["from"], st["to"]), names):
            if sid not in have:
                label = name if name != sid else sid.replace("-", " ").title()
                systems.append({"id": sid, "label": label[:28], "kind": guess_kind(label), "note": ""})
                have.add(sid)
    if len(systems) > LIMITS["systems"]:
        raise BriefError(f"the flow mentions {len(systems)} systems; at most {LIMITS['systems']} fit on the picture")
    return systems


# ---------- using a brief ----------
def of(ctx):
    """The brief the Topic Scout settled on for this run (possibly completed by AI), or {}."""
    return (ctx.outputs.get("topic") or {}).get("brief") or {}


def briefing_mode(cat):
    """off: ignore briefs. owner: use the owner's brief as written. auto: also let the Topic Scout fill gaps."""
    mode = cat.get("briefing")
    if mode in ("off", "owner", "auto"):
        return mode
    return "off" if cat.get("media") == "animation" else "owner"


def media_mode(cat, brief):
    """animation (built-in algorithm tracer) | sysflow | poster | video (animated poster) | none."""
    if cat.get("media") == "animation":
        return "animation"
    vt = ((brief or {}).get("visual") or {}).get("type") or "auto"
    if vt == "none":
        return "none"
    if vt == "system-flow":
        return "sysflow"
    if vt == "poster":
        return "poster"
    media = cat.get("media", "auto")
    if media in ("auto", "poster"):
        # generated from the day's context: a system-style story gets the animation, a checklist or guide a poster
        if brief and brief.get("pattern") not in ("checklist", "decision-guide"):
            return "sysflow"
        return "poster"
    return media


def missing(brief, cat):
    """The fields the Topic Scout may fill in (never one the owner wrote)."""
    b, v = brief or {}, (brief or {}).get("visual") or {}
    gaps = [k for k in ("context", "example", "takeaway", "pattern", "question") if not b.get(k)]
    if media_mode(cat, b) == "sysflow":
        gaps += [k for k in ("systems", "flow") if not v.get(k)]
    return gaps


def merge_generated(brief, got, gaps):
    """Fill only the gaps from the AI's answer; owner-written fields are never touched."""
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in (brief or {}).items()}
    vis = dict(out.get("visual") or {})
    filled = []
    for g in gaps:
        v = got.get(g)
        if not v:
            continue
        if g in ("systems", "flow"):
            vis[g] = v
        else:
            out[g] = v
        filled.append(g)
    if "example" in filled:
        out["example_kind"] = "scenario"        # an invented example is always an illustration
    if vis:
        out["visual"] = vis
    raw = dict(out, generated=sorted(set(out.get("generated", [])) | set(filled)))
    return normalize(raw)


def _pattern_block(pid):
    p = PATTERNS.get(pid or DEFAULT_PATTERN)
    return (f"WRITING PATTERN - {p['label']}: {p['summary']}\nBeats, in this order:\n"
            + "\n".join(f"  {i}. {b}" for i, b in enumerate(p["beats"], 1)))


def _visual_lines(b):
    v = b.get("visual") or {}
    out = []
    if v.get("systems"):
        out.append("Components: " + "; ".join(f"{s['label']} ({s['kind']})" + (f" - {s['note']}" if s.get("note") else "")
                                              for s in v["systems"]))
    if v.get("flow"):
        scn = None
        for i, s in enumerate(v["flow"], 1):
            if s.get("scene") and s["scene"] != scn:
                out.append(f"Scene: {s['scene']}")
            scn = s.get("scene")
            names = {x["id"]: x["label"] for x in v.get("systems", [])}
            out.append(f"  {i}. {names.get(s['from'], s['from'])} -> {names.get(s['to'], s['to'])}"
                       + (f": {s['label']}" if s.get("label") else "") + (f" ({s['caption']})" if s.get("caption") else ""))
    if v.get("notes"):
        out.append("Animation notes: " + v["notes"])
    return out


def writer_block(brief):
    """What the Writer reads in addition to the category brief ('' when there is no brief)."""
    b = brief or {}
    if not b:
        return ""
    lines = ["OWNER'S BRIEF FOR THIS POST (follow it; where it differs from the category brief, the owner's brief wins):"]
    if b.get("context"):
        lines.append(f"Context: {b['context']}")
    if b.get("example"):
        how = ("It is an ILLUSTRATIVE scenario: introduce it as one ('Picture...', 'Say a team...', 'Imagine...'), keep "
               "it generic (no real company names, no invented incident, no figures presented as measured). It is NOT "
               "something that happened to the owner." if b.get("example_kind", "scenario") == "scenario" else
               "It is a REAL, PUBLIC incident: state only what the verified sources say, with their qualifiers, and "
               "name nothing the sources do not name.")
        lines.append(f"Real-world example (build the post around it): {b['example']}\n  {how}")
    if b.get("takeaway"):
        lines.append(f"After reading, the reader should be able to: {b['takeaway']}")
    lines.append(_pattern_block(b.get("pattern")))
    if b.get("tone"):
        lines.append(f"Tone notes: {b['tone']}")
    if b.get("must_include"):
        lines.append("Must include: " + "; ".join(b["must_include"]))
    if b.get("avoid"):
        lines.append("Avoid: " + "; ".join(b["avoid"]))
    if b.get("question"):
        lines.append(f"Closing question (use it or a close variant): {b['question']}")
    vis = _visual_lines(b)
    if vis:
        lines.append("THE PICTURE: an animated system diagram will accompany this post. It shows:\n  "
                     + "\n  ".join(vis) +
                     "\n  Use the SAME component names and the SAME order in the post's numbered steps, so the text and "
                     "the animation agree. Call it 'the animation' and, if you describe it, say it is a simplified "
                     "illustration; never say it is recorded traffic or a real system.")
    return "\n".join(lines)


def media_block(brief):
    """What the Visual Designer reads when designing the system animation."""
    b = brief or {}
    vis = _visual_lines(b)
    pat = PATTERNS.get(b.get("pattern") or "", {})
    parts = []
    if b.get("example"):
        parts.append(f"Real-world example the animation should play out: {b['example']}")
    if b.get("pattern") == "before-after" or any(s.get("scene") for s in (b.get("visual") or {}).get("flow", [])):
        parts.append("Use TWO scenes: the naive design first (show where it breaks, attack/error packets in red), then "
                     "the improved design.")
    if vis:
        parts.append("The owner's components and sequence (keep their names and order; you may add status, state, "
                     "wire payloads and captions, and one or two steps the sequence is missing):\n" + "\n".join(vis))
    if pat:
        parts.append(f"Writing pattern of the post: {pat['label']}.")
    return "\n\n".join(parts)


def editor_rules(brief):
    """Added to the Editor's (and the Pre-reviewer's) instructions; '' when there is no brief."""
    if not brief:
        return ""
    return ("THE OWNER WROTE A BRIEF for this post (it is in <owner_brief>). Judge adherence inside 'value' and "
            "'format':\n"
            "- the post is built around the real-world example; an example marked scenario is framed as illustrative "
            "('picture...', 'say...') and never as something that really happened; one marked incident is backed by "
            "<sources>\n"
            "- the post follows the writing pattern's beats, in order\n"
            "- every 'must include' item is present and no 'avoid' item is\n"
            "- the closing question matches the brief's, if one was given\n"
            "- if the brief lists components or a sequence, the post names the same components in the same order\n"
            "A clear miss caps the matching criterion at 69 and puts the fix with the writer (or with media when only "
            "the picture is off). Do not penalise anything the brief did not ask for.\n"
            "THE ANIMATION (when the draft has one) is a simplified illustration that shows the scenario step by step "
            "with more detail than the post can carry. It does NOT have to match the post's step count or numbering, "
            "and you must not ask for steps to be deleted or renumbered to make them match. Use 'poster_text_mismatch' "
            "only when the animation contradicts the post or the sources: a different name, number or claim. Detail "
            "the post does not repeat, and an attacker or failure scene the brief asked for, are fine.")


def review_block(brief):
    if not brief:
        return []
    return ["", "<owner_brief>", to_text({k: v for k, v in brief.items() if k != "generated"}), "</owner_brief>"]


def reference_urls(brief):
    return [r for r in (brief or {}).get("references", []) if re.match(r"https://\S+$", r)]


def numbers_in(brief):
    """Numbers the owner wrote in the brief: they count as supplied facts for the number checks."""
    from .checks import significant_numbers
    return list(dict.fromkeys(significant_numbers(to_text({k: v for k, v in (brief or {}).items()
                                                           if k != "generated"}))))


def supplied(ctx):
    """The owner's brief as a pseudo-source, so numbers the owner wrote do not fail the number checks."""
    nums = numbers_in(of(ctx))
    return [{"url": "owner-brief", "verified": True, "page": " ".join(nums), "excerpts": []}] if nums else []


def cat_context(cat):
    """The owner's notes on this type of topic: what it is about, and how to plan it (Settings > Topics)."""
    out = []
    if (cat.get("context") or "").strip():
        out.append("ABOUT THIS TYPE OF TOPIC (the owner's context): " + cat["context"].strip())
    if (cat.get("plan_context") or "").strip():
        out.append("HOW TO PLAN TOPICS OF THIS TYPE (the owner's guidance): " + cat["plan_context"].strip())
    return "\n".join(out)


# What the Week Planner (and the Topic Scout) write for a day: the same fields an owner's brief has.
_SYSTEM_SCHEMA = {"type": "object", "required": ["id", "label", "kind", "note"], "additionalProperties": False,
                  "properties": {"id": {"type": "string"}, "label": {"type": "string", "description": "max 16 chars"},
                                 "kind": {"type": "string", "enum": COMPONENT_KINDS},
                                 "note": {"type": "string", "description": "max 24 chars"}}}
_STEP_SCHEMA = {"type": "object", "required": ["from", "to", "label", "kind", "payload", "caption", "scene"],
                "additionalProperties": False,
                "properties": {"from": {"type": "string"}, "to": {"type": "string"},
                               "label": {"type": "string", "description": "max 16 chars"},
                               "kind": {"type": "string", "enum": STEP_KINDS},
                               "payload": {"type": "string", "description": "what is really sent, max 80 chars"},
                               "caption": {"type": "string", "description": "one plain sentence"},
                               "scene": {"type": "string", "description": "'Before'/'After' for a two-scene story, else empty"}}}
BRIEF_PROPS = {
    "context": {"type": "string", "description": "2-4 sentences: why this matters and what readers get wrong"},
    "example": {"type": "string", "description": "one concrete real-world scenario the post is built around"},
    "example_kind": {"type": "string", "enum": EXAMPLE_KINDS,
                     "description": "incident ONLY for a real public incident you found, with its source in references"},
    "references": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                   "description": "https primary-source links (required for an incident, else empty)"},
    "takeaway": {"type": "string", "description": "what the reader can do after reading"},
    "pattern": {"type": "string", "enum": list(PATTERNS)},
    "question": {"type": "string", "description": "specific closing question"},
    "visual": {"type": "string", "enum": ["system-flow", "poster"]},
    "systems": {"type": "array", "items": _SYSTEM_SCHEMA, "maxItems": 8,
                "description": "components of the system (empty for a poster)"},
    "flow": {"type": "array", "items": _STEP_SCHEMA, "maxItems": 12,
             "description": "ordered messages between the components (empty for a poster)"},
}
