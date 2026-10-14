"""Publisher agent: queues an approved post, and publishes due posts to LinkedIn at post time.

Approval modes (publishing.approval):
  auto_with_veto  queued for post_time on the post date; you can veto it in the Studio until then
  manual          waits in the queue until you click Approve
  immediate       published right away
With publishing.dry_run on, publishing logs exactly what would be sent and sends nothing.
"""
import shutil
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..linkedin import LinkedIn, LinkedInError
from ..notify import notify
from ..runlog import RunLog
from .base import Agent, AgentError
from .credentials import GOOD, run_check

DUE = ("queued", "approved")
COMMENT_WAITS_S = (5, 20)        # LinkedIn may not accept a comment the moment a post is created
COMMENT_MAX_TRIES = 3            # later publish checks retry a failed first comment this many times in all


def scheduled_at(cfg, day):
    hh, mm = map(int, cfg["schedule"]["post_time"].split(":"))
    local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ZoneInfo(cfg["schedule"]["timezone"]))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def enqueue(ws, cfg, run_id, day, category, final, review):
    pid = f"{day.isoformat()}-{category}"
    media = None
    if final.get("media_path"):
        dest = ws.root / "media" / f"{pid}{'.mp4' if final['media_kind'] == 'video' else '.png'}"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(final["media_path"], dest)
        media = str(dest.relative_to(ws.root))
    mode = cfg["publishing"]["approval"]
    post = {"id": pid, "run_id": run_id, "date": day.isoformat(), "category": category, "topic": final["title"],
            "text": final["text"], "first_comment": final.get("first_comment", ""), "media": media,
            "media_kind": final.get("media_kind"), "status": "awaiting_approval" if mode == "manual" else "queued",
            "scheduled_at": scheduled_at(cfg, day) if mode != "immediate" else datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "review": {k: review.get(k) for k in ("overall", "scores")}}
    queue = [p for p in ws.queue() if p["id"] != pid]
    ws.save_queue(queue + [post])
    return post


def post_url(urn):
    return f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""


def post_rows(ws, post, *extra):
    """The table rows that describe a post in notification emails."""
    cfg = ws.config()
    cat = cfg["categories"].get(post.get("category"), {}).get("label", post.get("category", ""))
    review = (post.get("review") or {}).get("overall")
    rows = [("Topic", post.get("topic", "")), ("Kind of post", cat), ("Post date", post.get("date", ""))]
    if post.get("scheduled_at") and post.get("status") in ("queued", "approved", "awaiting_approval"):
        local = datetime.fromisoformat(post["scheduled_at"]).astimezone(ZoneInfo(cfg["schedule"]["timezone"]))
        rows.append(("Publishes at", local.strftime("%a %d %b %Y, %H:%M ") + cfg["schedule"]["timezone"]))
    if review is not None:
        rows.append(("Editor score", f"{review} / 100"))
    rows.append(("Length", f"{len(post.get('text', ''))} characters"))
    if post.get("media_kind"):
        rows.append(("Picture", {"video": "Algorithm video", "image": "Poster image", "poster": "Poster image"}.get(post["media_kind"],
                                                                                           post["media_kind"])))
    if post.get("first_comment"):
        rows.append(("First comment", post["first_comment"]))
    return rows + list(extra)


def post_details(ws, post, *extra):
    media = ws.root / post["media"] if post.get("media") and post.get("media_kind") != "video" else None
    return {"rows": post_rows(ws, post, *extra), "text": post.get("text", ""), "image": str(media) if media else None}


def add_first_comment(ws, post, li, owner, ev, sleep=time.sleep, waits=COMMENT_WAITS_S):
    """Add the post's first comment, retrying after short waits. Records comment_status (added | failed) on post."""
    err = None
    for wait in (0,) + tuple(waits):
        if wait:
            sleep(wait)
        try:
            li.add_comment(owner, post["urn"], post["first_comment"])
            post.update(comment_status="added", comment_error=None,
                        comment_tries=post.get("comment_tries", 0) + 1)
            ev("comment", "first comment added")
            return True
        except LinkedInError as e:
            err = e
    post.update(comment_status="failed", comment_error=str(err), comment_tries=post.get("comment_tries", 0) + 1)
    ev("warning", f"post is live but the first comment failed: {err}", "warning")  # the post is live; do not lose that
    if post["comment_tries"] >= COMMENT_MAX_TRIES:
        notify(ws, "First comment not added", f"{post['topic']}: the post is live, but LinkedIn refused the first "
               "comment. Add it by hand on LinkedIn.", level="warning", key=f"comment-{post['id']}",
               action={"label": "Open Queue", "tab": "queue"},
               details={"rows": [("Topic", post["topic"]), ("Post on LinkedIn", post_url(post["urn"])),
                                 ("Comment to add", post["first_comment"]), ("Tries", post["comment_tries"]),
                                 ("LinkedIn said", str(err)[:300])]})
    return False


def retry_comments(ws, client_factory=LinkedIn, log=print, sleep=time.sleep):
    """Retry first comments that failed on published posts. Returns how many were added."""
    todo = [h for h in ws.history() if h.get("comment_status") == "failed" and h.get("urn")
            and h.get("comment_tries", 0) < COMMENT_MAX_TRIES]
    if not todo or ws.config()["publishing"]["dry_run"]:
        return 0
    s = ws.secrets()
    if not s.get("linkedin_access_token"):
        return 0
    li = client_factory(s["linkedin_access_token"], ws.config()["publishing"]["linkedin_api_version"])
    added = 0
    for h in todo:
        run = RunLog(ws.runs_dir / h["run_id"]) if h.get("run_id") and (ws.runs_dir / h["run_id"]).exists() else None

        def ev(kind, msg, level="info"):
            log(msg)
            if run:
                run.event("publisher", kind, msg, level=level)
        try:
            owner = s.get("linkedin_person_urn") or li.person_urn()
        except LinkedInError as e:
            log(f"first comment retry skipped: {e}")
            return added
        post = dict(h)
        added += add_first_comment(ws, post, li, owner, ev, sleep, waits=())
        ws.remove_history(lambda p: p.get("id") == h["id"] and p.get("urn") == h["urn"])
        ws.add_history(post)
    return added


def publish_one(ws, post, client_factory=LinkedIn, log=print, sleep=time.sleep):
    """Publish one queued post. Returns the updated post (status published | dry_run | failed)."""
    cfg = ws.config()
    run = RunLog(ws.runs_dir / post["run_id"]) if post.get("run_id") and (ws.runs_dir / post["run_id"]).exists() else None

    def ev(kind, msg, level="info"):
        log(msg)
        if run:
            run.event("publisher", kind, msg, level=level)

    if cfg["publishing"]["dry_run"]:
        ev("dry_run", f"DRY RUN - would publish '{post['topic']}' ({len(post['text'])} chars, media: "
                      f"{post.get('media') or 'none'}). Turn off dry run in Settings to post for real.")
        post.update(status="dry_run", published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if run:
            run.step("publisher", "passed", summary="dry run: nothing sent")
        return post
    creds = run_check(ws, client_factory=client_factory)
    if creds["linkedin"]["state"] not in GOOD:
        post.update(status="queued", error=creds["linkedin"]["message"])
        ev("blocked", f"not published: {creds['linkedin']['message']}", "error")
        if run:
            run.step("publisher", "blocked", summary="LinkedIn credentials invalid")
        return post
    s = ws.secrets()
    li = client_factory(s["linkedin_access_token"], cfg["publishing"]["linkedin_api_version"])
    try:
        owner = s.get("linkedin_person_urn") or li.person_urn()
        media_urn = None
        if post.get("media"):
            path = ws.root / post["media"]
            ev("upload", f"uploading {path.name}")
            media_urn = (li.upload_video(owner, path, log=lambda m: ev("upload", m)) if post["media_kind"] == "video"
                         else li.upload_image(owner, path))
        urn = li.create_post(owner, post["text"], media_urn, post["topic"])
    except LinkedInError as e:
        post.update(status="failed", error=str(e))
        ev("failed", f"publishing failed: {e}", "error")
        if run:
            run.step("publisher", "failed", errors=[str(e)])
        notify(ws, "Publishing failed", f"{post['topic']} was not published. It stays in the queue.", level="error",
               key=f"publish-{post['id']}", action={"label": "Open Queue", "tab": "queue"},
               details={"rows": post_rows(ws, post, ("LinkedIn said", str(e)[:300]))})
        return post
    post.update(status="published", urn=urn, published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                error=None)
    ev("published", f"published {urn}")
    if post.get("first_comment"):
        add_first_comment(ws, post, li, owner, ev, sleep)
    if run:
        run.step("publisher", "passed", summary=f"published {urn}")
    ws.add_history({k: post.get(k) for k in ("id", "date", "category", "topic", "text", "first_comment", "media",
                                             "urn", "published_at", "run_id", "comment_status", "comment_error",
                                             "comment_tries")})
    comment = {"added": "added", "failed": "failed, will retry"}.get(post.get("comment_status"), "none")
    notify(ws, "Posted to LinkedIn", f"{post['topic']} is live on your profile.", level="success",
           action={"label": "Open Queue", "tab": "queue"},
           details=post_details(ws, post, ("Post on LinkedIn", post_url(urn)), ("First comment status", comment)))
    return post


def publish_due(ws, now=None, client_factory=LinkedIn, log=print, sleep=time.sleep):
    now = now or datetime.now(timezone.utc)
    retry_comments(ws, client_factory, log, sleep)
    results = []
    for p in sorted(ws.queue(), key=lambda p: p["scheduled_at"]):
        if p["status"] in DUE and datetime.fromisoformat(p["scheduled_at"]) <= now:
            updated = publish_one(ws, dict(p), client_factory, log, sleep)
            ws.save_queue([updated if q["id"] == p["id"] else q for q in ws.queue()]
                          if updated["status"] != "published" else [q for q in ws.queue() if q["id"] != p["id"]])
            results.append(updated)
            if updated["status"] in ("published", "dry_run"):
                break  # at most one post per publish window
    return results


class PublisherAgent(Agent):
    id = "publisher"
    title = "Publisher"
    name = "Echo"
    role = "Queues the approved post for post time (or for your approval) and publishes it to LinkedIn."
    uses_llm = False

    def run(self, ctx, guidance):
        post = enqueue(ctx.ws, ctx.cfg, ctx.run.status["run_id"], ctx.day, ctx.category, ctx.outputs["formatter"],
                       ctx.outputs["editor"])
        mode = ctx.cfg["publishing"]["approval"]
        if mode == "immediate":
            published = publish_due(ctx.ws)
            if not published:
                raise AgentError("immediate publish found nothing due")
            return {"post_id": post["id"], "status": published[-1]["status"], "mode": mode}
        notify(ctx.ws, "Post ready" if mode != "manual" else "Post waiting for your approval",
               f"{post['topic']} - {'publishes ' + post['date'] + ' ' + ctx.cfg['schedule']['post_time'] if mode != 'manual' else 'approve it in the Queue'}",
               level="info", action={"label": "Review in Queue", "tab": "queue"},
               details=post_details(ctx.ws, post, ("Cost of this run", f"${ctx.run.cost:.2f} at API prices"),
                                    ("What to do", "Nothing: it goes out at the time above. Veto or edit it in the "
                                                   "Queue before then." if mode != "manual"
                                     else "Approve, edit or veto it in the Queue.")))
        return {"post_id": post["id"], "status": post["status"], "scheduled_at": post["scheduled_at"], "mode": mode}

    def summary(self, out):
        return {"queued": f"queued for {out.get('scheduled_at', '')[:16]}Z",
                "awaiting_approval": "waiting for your approval"}.get(out["status"], out["status"])
