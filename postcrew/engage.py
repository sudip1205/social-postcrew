"""Comment replies: the crew reads the comments on your recent LinkedIn posts and answers each one from what it says.

Every check (the scheduler runs one every engage.every_minutes; Studio's Comments card can run one now):
  1. for each post you published in the last engage.lookback_days, read its comments;
  2. leave out your own comments, ones you (or the crew) already answered, and ones already seen;
  3. the Replier (llm.agents.replier) writes one reply per new comment, from the post, the comment and the thread around it, in your
     voice; spam, sales pitches and abuse are skipped, never answered;
  4. engage.replies decides what happens next: "review" (the default) keeps each reply as a draft in Studio until you send, edit or
     skip it; "auto" sends it right away; "off" does nothing. With publishing.dry_run on, nothing is sent.

Reading comments needs more than "Share on LinkedIn": LinkedIn refuses it to an app without its Community Management API product.
When LinkedIn refuses, the check stops, says so once (a notification and the Comments card) and tries again a day later.

State: state/engage.json  {"access": {...}, "checked_at": ..., "comments": {comment_urn: {...}}}
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .linkedin import LinkedIn, LinkedInError
from .llm import LLMError, make_backend
from .notify import notify

AGENT = "replier"
MODES = ("off", "review", "auto")
DEFAULTS = {"replies": "review", "lookback_days": 7, "every_minutes": 30, "max_per_check": 20}
DENIED_RETRY = timedelta(hours=24)
PROMPT = Path(__file__).parent / "prompts" / "reply.md"

SCHEMA = {
    "type": "object",
    "properties": {"replies": {"type": "array", "items": {
        "type": "object",
        "properties": {"comment": {"type": "string", "description": "the comment's id, exactly as given"},
                       "reply": {"type": "string", "description": "the reply, or empty when skipped"},
                       "skip": {"type": "boolean"},
                       "comment_text": {"type": "string", "description": "for a comment from an email: the comment's own words"},
                       "why": {"type": "string", "description": "one short line: what the comment wants, or why it is skipped"}},
        "required": ["comment", "reply", "skip", "why"]}}},
    "required": ["replies"],
}


def now():
    return datetime.now(timezone.utc)


def settings(cfg):
    return {**DEFAULTS, **(cfg.get("engage") or {})}


def load(ws):
    d = ws.state("engage", {}) or {}
    d.setdefault("comments", {})
    d.setdefault("access", {})
    return d


def save(ws, d):
    ws.save_state("engage", d)


def client(ws, client_factory=LinkedIn):
    s = ws.secrets()
    if not s.get("linkedin_access_token"):
        return None, None
    li = client_factory(s["linkedin_access_token"], ws.config()["publishing"]["linkedin_api_version"])
    return li, s.get("linkedin_person_urn") or li.person_urn()


def recent_posts(ws, days, at=None):
    since = (at or now()) - timedelta(days=days)
    out = []
    for h in ws.history():
        if h.get("platform", "linkedin") != "linkedin" or not h.get("urn") or not h.get("published_at"):
            continue
        try:
            when = datetime.fromisoformat(h["published_at"])
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= since:
            out.append(h)
    return out


def _denied(ws, d, err):
    msg = ("LinkedIn does not let Postcrew read the comments on your posts: your LinkedIn app has \"Share on LinkedIn\" only. "
           "To turn on replies, add the Community Management API product to a LinkedIn app (developer.linkedin.com > your app > "
           "Products), then reconnect LinkedIn in Credentials. Or let the Replier read LinkedIn's comment emails instead: add your mailbox in Credentials > Comment emails.")
    first = d["access"].get("ok") is not False
    d["access"] = {"ok": False, "message": msg, "error": str(err)[:400], "at": now().isoformat(timespec="seconds")}
    save(ws, d)
    if first:
        notify(ws, "Comment replies need LinkedIn access", msg, level="warning", key="engage-access",
               action={"label": "Open Credentials", "tab": "credentials"})
    return msg


class Blocked(Exception):
    pass


def check(ws, client_factory=LinkedIn, llm=None, log=print, at=None, force=False, imap=None):
    """One check of your recent posts' comments. Returns {"new": n, "sent": n, "drafted": n, "skipped": n, "source": ...} or
    {"blocked": why}. The comments come from your comment emails when a mailbox is set in Credentials (LinkedIn's API does not give a
    personal profile's comments to apps), else from the API."""
    from . import mailbox
    cfg = ws.config()
    st = settings(cfg)
    at = at or now()
    if st["replies"] == "off" and not force:
        return {"blocked": "comment replies are off"}
    d = load(ws)
    try:
        mail = mailbox.settings(ws.secrets())
    except mailbox.MailError as e:
        return {"blocked": str(e)}
    if not mail and not force and d["access"].get("ok") is False and d["access"].get("at") and \
            at - datetime.fromisoformat(d["access"]["at"]) < DENIED_RETRY:
        return {"blocked": d["access"]["message"]}
    posts = recent_posts(ws, st["lookback_days"], at)
    d["checked_at"] = at.isoformat(timespec="seconds")
    if not posts and not mail:
        save(ws, d)
        return {"new": 0, "sent": 0, "drafted": 0, "skipped": 0}
    try:
        li, owner = client(ws, client_factory)
    except LinkedInError as e:
        return {"blocked": f"LinkedIn: {e}"}
    if not li:
        return {"blocked": "LinkedIn is not connected"}
    try:
        groups = (_from_mail(ws, d, posts, mail, at, st, imap) if mail else _from_api(ws, d, posts, li, owner, log, at))
    except Blocked as e:
        save(ws, d)
        return {"blocked": str(e)}
    counts = {"new": 0, "sent": 0, "drafted": 0, "skipped": 0, "source": "email" if mail else "api"}
    budget = st["max_per_check"]
    for post, fresh, thread in groups:
        fresh = fresh[:budget]
        if not fresh:
            continue
        budget -= len(fresh)
        try:
            drafts = draft(ws, post, fresh, thread, owner, llm)
        except LLMError as e:
            log(f"replies for {post['id']}: {e}")
            break   # the same comments are tried next time
        for c in fresh:
            r = drafts.get(c["urn"]) or drafts.get(c["id"]) or {}
            if c.get("email") and (r.get("comment_text") or "").strip():
                c = {**c, "text": r["comment_text"].strip()}   # the comment's own words, out of the email around it
            counts["new"] += 1
            if c.get("message_id"):
                d.setdefault("mails", []).append(c["message_id"])
            if r.get("skip") or not (r.get("reply") or "").strip():
                d["comments"][c["urn"]] = _row(post, c, status="skipped", why=r.get("why") or "no reply written")
                counts["skipped"] += 1
                continue
            d["comments"][c["urn"]] = _row(post, c, status="drafted", reply=r["reply"].strip(), why=r.get("why", ""))
            counts["drafted"] += 1
        d["mails"] = d.get("mails", [])[-1000:]
        save(ws, d)
        if budget <= 0:
            break
    if st["replies"] == "auto":
        for urn, row in list(d["comments"].items()):
            if row["status"] == "drafted" and row.get("post_urn"):
                res = send(ws, urn, client_factory=client_factory, li=li, owner=owner, log=log)
                counts["sent"] += res.get("status") == "sent"
                counts["drafted"] -= res.get("status") == "sent"
        d = load(ws)
    save(ws, d)
    if counts["drafted"] and st["replies"] == "review":
        notify(ws, "New comments to answer", f"{counts['drafted']} new comment{'s' if counts['drafted'] != 1 else ''} on your posts: "
               "the crew wrote replies for you to send or change.", level="info", key="engage-drafts",
               action={"label": "Open Queue", "tab": "queue"})
    return counts


def _from_api(ws, d, posts, li, owner, log, at):
    """[(post, new comments, the whole thread)] from LinkedIn's comments API."""
    groups = []
    for post in posts:
        try:
            found = li.comments(post["urn"])
        except LinkedInError as e:
            if e.status in (401, 403):
                raise Blocked(_denied(ws, d, e))
            log(f"comments of {post['id']}: {e}")
            continue
        d["access"] = {"ok": True, "at": at.isoformat(timespec="seconds")}
        fresh = []
        for c in found:
            if not c["urn"] or c["urn"] in d["comments"] or c["actor"] == owner or not c["text"]:
                continue
            if c.get("replies") and _answered(li, c, owner):
                d["comments"][c["urn"]] = _row(post, c, status="answered", why="you already replied")
                continue
            fresh.append(c)
        groups.append((post, fresh, found))
    return groups


def _from_mail(ws, d, posts, mail, at, st, imap=None):
    """[(post, new comments, [])] from LinkedIn's "commented on your post" emails in your mailbox."""
    from . import mailbox
    kw = {"imap": imap} if imap else {}
    try:
        found = mailbox.fetch(ws.secrets(), at - timedelta(days=st["lookback_days"]), set(d.get("mails") or []), **kw)
    except mailbox.MailError as e:
        d["mail"] = {"ok": False, "message": str(e), "at": at.isoformat(timespec="seconds")}
        raise Blocked(str(e))
    d["mail"] = {"ok": True, "at": at.isoformat(timespec="seconds"), "server": mail["server"], "address": mail["address"]}
    by_post = {}
    for m in found:
        urn = m["comment_urn"] or f"mail:{m['message_id']}"
        if urn in d["comments"]:
            d.setdefault("mails", []).append(m["message_id"])
            continue
        post = match_post(m, posts) or {"id": m["thread_urn"] or "unknown", "urn": m["thread_urn"], "topic": "", "text": ""}
        c = {"urn": urn, "id": urn, "actor": "", "author": m["author"], "text": m["body"], "created": _ms(m["at"]), "parent": None,
             "email": True, "subject": m["subject"], "message_id": m["message_id"]}
        by_post.setdefault(post["id"], (post, []))[1].append(c)
    return [(post, fresh, []) for post, fresh in by_post.values()]


def _ms(iso):
    try:
        return int(datetime.fromisoformat(iso).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def match_post(m, posts):
    """Which of your posts an email is about: the same post id in its link, else the post whose opening words the email quotes."""
    num = (m.get("thread_urn") or "").rsplit(":", 1)[-1]
    for p in posts:
        if num and (p.get("urn") or "").rsplit(":", 1)[-1] == num:
            return p
    body = _norm(m.get("body"))
    best = None
    for p in posts:
        words = _norm(p.get("text")).split()
        for n in (12, 8, 5):
            if len(words) >= n and " ".join(words[:n]) in body:
                if not best or n > best[0]:
                    best = (n, p)
                break
    return best[1] if best else None


def _answered(li, c, owner):
    try:
        return any(r["actor"] == owner for r in li.comments(c["urn"]))
    except LinkedInError:
        return False


def _row(post, c, status, reply="", why=""):
    return {"post_id": post["id"], "post_urn": post.get("urn"), "topic": post.get("topic", "") or c.get("subject", ""),
            "comment_id": c["id"], "actor": c["actor"], "author": c.get("author", ""), "source": "email" if c.get("email") else "api",
            "text": c["text"][:3000], "created": c.get("created"), "parent": c.get("parent"), "status": status, "reply": reply,
            "why": why[:300], "seen_at": now().isoformat(timespec="seconds")}


def draft(ws, post, fresh, thread, owner, llm=None):
    """The Replier's replies for the new comments of one post: {comment urn: {"reply", "skip", "why"}}."""
    cfg = ws.config()
    p = cfg["profile"]
    if llm is None:
        if cfg["llm"]["backend"] == "demo":
            from .demo import Demo
            llm = Demo(cfg, ws.secrets())
        else:
            llm = make_backend(cfg, ws.secrets())
    system = (PROMPT.read_text().replace("{{name}}", p.get("name") or "the account owner").replace("{{voice}}", p.get("voice", ""))
              .replace("{{audience}}", p.get("audience", "")).replace("{{about}}", "\n".join(f"- {a}" for a in p.get("about", [])) or "- (nothing listed)"))
    others = [c for c in thread if c["urn"] not in {f["urn"] for f in fresh}][-15:]
    mails = any(c.get("email") for c in fresh)
    prompt = "\n".join([
        "THE POST", post.get("text", "")[:4000] or "(not known: read it from the email, which quotes its opening)", "",
        f"FIRST COMMENT (the post's source): {post.get('first_comment') or '(none)'}", "",
        "EARLIER COMMENTS ON THE POST (context only; do not answer these):",
        *([f"- {'YOU' if c['actor'] == owner else 'someone'}: {c['text'][:400]}" for c in others] or ["- (none)"]), "",
        "NEW COMMENTS TO ANSWER (one reply each):",
        *(["Each one is the email LinkedIn sent about the comment: find the comment itself in it (not the post's quoted opening, "
           "not LinkedIn's buttons and footer), put its exact words in comment_text, and answer only that."] if mails else []),
        *[json.dumps({"comment": c["urn"], "text": c["text"][:1500], **({"in_reply_to_a_comment": True} if c.get("parent") else {}),
                      **({"email_subject": c.get("subject", "")} if c.get("email") else {})})
          for c in fresh],
    ])
    res = llm.call(AGENT, system, prompt, SCHEMA, cwd=str(Path(ws.root) / "state"))
    return {r.get("comment"): r for r in (res.data or {}).get("replies") or []}


def send(ws, urn, text=None, client_factory=LinkedIn, li=None, owner=None, log=print):
    """Send one reply (the draft, or `text` when you changed it). Returns the comment's row."""
    d = load(ws)
    row = d["comments"].get(urn)
    if not row:
        raise KeyError(urn)
    if text is not None:
        row["reply"] = text.strip()
    if not row.get("reply"):
        raise ValueError("the reply is empty")
    if row["status"] == "sent":
        return row
    if not row.get("post_urn"):
        raise ValueError("LinkedIn's email had no link to this post or comment: copy the reply and post it on LinkedIn yourself")
    if ws.config()["publishing"]["dry_run"]:
        row.update(status="dry_run", sent_at=now().isoformat(timespec="seconds"))
        log(f"DRY RUN - would reply to a comment on '{row['topic']}': {row['reply']}")
    else:
        if li is None:
            li, owner = client(ws, client_factory)
            if not li:
                raise ValueError("LinkedIn is not connected")
        try:
            # a reply to a reply goes under the same top comment (LinkedIn nests one level)
            parent = row.get("parent") or (urn if urn.startswith("urn:li:comment:") else None)
            row["sent_urn"] = li.add_comment(owner, row["post_urn"], row["reply"], parent=parent)
            row.update(status="sent", sent_at=now().isoformat(timespec="seconds"), error=None)
        except LinkedInError as e:
            row.update(status="failed", error=str(e)[:400])
            log(f"reply not sent: {e}")
    d["comments"][urn] = row
    save(ws, d)
    return row


def skip(ws, urn):
    d = load(ws)
    if urn not in d["comments"]:
        raise KeyError(urn)
    d["comments"][urn]["status"] = "skipped"
    d["comments"][urn]["why"] = "you skipped it"
    save(ws, d)
    return d["comments"][urn]


def overview(ws):
    """What Studio's Comments card shows: the access state, the mode, and the comments newest first."""
    d = load(ws)
    rows = [{"urn": k, **v} for k, v in d["comments"].items()]
    rows.sort(key=lambda r: (r["status"] not in ("drafted", "failed"), -(r.get("created") or 0)))
    return {"settings": settings(ws.config()), "access": d["access"], "mail": d.get("mail") or {}, "checked_at": d.get("checked_at"), "comments": rows[:100]}


def due(ws, at=None):
    """Whether the scheduler should check now."""
    st = settings(ws.config())
    if st["replies"] == "off" or not ws.secrets().get("linkedin_access_token"):
        return False
    last = load(ws).get("checked_at")
    return not last or (at or now()) - datetime.fromisoformat(last) >= timedelta(minutes=max(5, int(st["every_minutes"])))
