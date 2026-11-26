"""Factory plans: YouTube is made by hand from the Factory, one plan at a time (owner, 2026-11-17).

    "I do not want to run any automated video. Let's only have factory, where I can add topic and click plan; then plan will create some
     similar plans as BAU. It will do some research and create the plan. Then keep the list of all the plans. Do not remove anything unless
     the video is made. Then I'll select and ask factory to create the script for that and I'll also give some instruction for script
     creation. Once the script is ready I'll record the voice. Tag the voice to the plan and save it. Mark them script approved. Then I can
     manually select the plan to make the video. So make the video based on the style selected."

The steps of one plan (state):
  planned  -> the Planner researched the topic on YouTube (trends.niche_research) and wrote it, like the monthly plans
  writing  -> the Script Writer is writing its script (a crew run that stops before the video: the Render step waits)
  script   -> its script is on the Voice desk (voice_desk.py): approve the script, upload your voice (or skip to dip_puck / am_puck)
  making   -> you pressed Make the video: the crew renders it in the style the script was written in
  editing  -> the video editor (factory_edit.py, owner 2026-11-23): watch it frame by frame, change it by hand or with an AI command,
              render it again; nothing is uploaded until you Approve the video there
  made     -> approved: the video is in the Queue, ready for upload; only now does the plan leave the list
Nothing else removes a plan, except your own Remove.
"""
import json
from pathlib import Path
import threading
import uuid
from datetime import date, datetime, timezone

from . import factory_styles, platforms

STATE = "factory-plans"
PLATFORM = "youtube"
_lock = threading.Lock()
_jobs = {}   # "plan" -> the Planner's job; <plan id> -> the script or video run of that plan


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(ws):
    return ws.state(STATE, {"items": []})


def _save(ws, st):
    ws.save_state(STATE, st)


def get(ws, pid):
    item = next((i for i in load(ws)["items"] if i["id"] == pid), None)
    if not item:
        raise ValueError("that plan is gone")
    return item


def _update(ws, pid, **kw):
    with _lock:
        st = load(ws)
        for i in st["items"]:
            if i["id"] == pid:
                i.update(kw)
                _save(ws, st)
                return i
    raise ValueError("that plan is gone")


def _job(key, fn):
    with _lock:
        j = _jobs.get(key)
        if j and j.get("done") is None:
            raise ValueError("already working on it: wait for it to finish")
        _jobs[key] = {"started": _now(), "done": None, "error": None}

    def go():
        try:
            fn()
        except Exception as e:
            _jobs[key]["error"] = f"{e}"[:500]
        finally:
            _jobs[key]["done"] = _now()

    threading.Thread(target=go, daemon=True, name=f"factory-plan-{key}").start()


def _cfg(ws):
    return platforms.view(ws.config(), PLATFORM)


# ---------- 1. plan: research the topic, write plans like the monthly ones ----------
def plan(ws, topic, count=3, hint="", fmt="short", llm=None, research=None, background=True):
    topic = " ".join(str(topic or "").split())
    if not 3 <= len(topic) <= 200:
        raise ValueError("type a topic (3-200 characters)")
    if fmt not in ("short", "long"):
        raise ValueError("format must be short or long")
    count = max(1, min(8, int(count or 3)))
    work = lambda: _plan(ws, topic, count, " ".join(str(hint or "").split()), fmt, llm, research)
    if not background:
        return work()
    _job("plan", work)
    return {"job": _jobs["plan"], "topic": topic}


def _plan(ws, topic, count, hint, fmt, llm, research):
    from .agents.base import RunContext
    from .llm import make_backend
    from .monthly import MonthPlanner, _all_items, load as month_pool
    from .runlog import RunLog
    from . import trends
    cfg = _cfg(ws)
    _jobs.setdefault("plan", {})["topic"] = topic
    run_id = datetime.now().strftime("factory-plan-%Y%m%d-%H%M%S")
    run = RunLog(ws.root / "plans" / run_id, run_id, meta={"topic": topic, "platform": PLATFORM, "source": "factory"})
    ctx = RunContext(ws=ws, cfg=cfg, day=date.today(), category="", run=run, llm=llm or make_backend(cfg, ws.secrets()), platform=PLATFORM)
    _jobs["plan"]["step"] = f"researching '{topic}' on YouTube"
    found = (research or trends.niche_research)(topic, log=lambda m: run.event("planner", "video", m))
    _jobs["plan"]["step"] = f"writing {count} plan(s)"
    avoid = ([i.get("title", "") for i in load(ws)["items"]] + [i.get("title", "") for i in _all_items(month_pool(ws, PLATFORM))]
             + [p.get("topic", "") for p in ws.recent_posts(200, PLATFORM)])
    plans = MonthPlanner().write(ctx, topic, count, [a for a in avoid if a], hint, research=found)
    if not plans:
        run.finish("failed", "no plan was accepted")
        raise ValueError("the Planner could not write a plan for this topic: try other words")
    stamp = _now()
    with _lock:
        st = load(ws)
        for p in plans:
            st["items"].append(dict(p, id=uuid.uuid4().hex[:8], topic=topic, format=fmt, hint=hint, state="planned", created_at=stamp))
        _save(ws, st)
    run.finish("succeeded", f"{len(plans)} plan(s) for {topic}")
    return {"added": len(plans)}


def add_own(ws, title, angle="", fmt="short"):
    """A plan typed by you, without research."""
    title = " ".join(str(title or "").split())
    if not 5 <= len(title) <= 90:
        raise ValueError("the title must be 5-90 characters")
    with _lock:
        st = load(ws)
        item = {"id": uuid.uuid4().hex[:8], "title": title, "angle": str(angle or "").strip() or title, "context": "", "example": "", "takeaway": "",
                "topic": title, "format": fmt if fmt in ("short", "long") else "short", "state": "planned", "created_at": _now(), "own": True}
        st["items"].append(item)
        _save(ws, st)
    return item


TAGS_SYSTEM = ("You write YouTube tags for one planned video of a channel that makes animated visual explainers (Shorts and long videos) "
               "about how technology, algorithms and everyday science work. Tags decide who the video reaches: use what people really search.")


def set_tags(ws, pid, tags=None, llm=None):
    """The plan's YouTube tags (owner, 2026-11-21): save yours, or with none given the Planner writes them from the plan and its research.
    A script already written for the plan gets them too (youtube.json starts from the plan's tags)."""
    from . import yt_tags
    item = get(ws, pid)
    if tags is None:
        from .llm import make_backend
        r = item.get("research") or {}
        prompt = "\n".join(x for x in [
            f"Title: {item.get('title')}", f"What the viewer learns: {item.get('angle')}", f"Context: {item.get('context', '')}",
            f"Example: {item.get('example', '')}", f"Broad topic: {item.get('topic', '')}",
            ("Top videos on it: " + "; ".join(v.get("title", "") for v in r.get("videos") or [])) if r.get("videos") else "",
            ("Search phrases: " + ", ".join(item.get("search_queries") or [])) if item.get("search_queries") else "",
            "", yt_tags.TAG_RULE] if x is not None)
        schema = {"type": "object", "properties": {"tags": yt_tags.TAGS_SCHEMA}, "required": ["tags"], "additionalProperties": False}
        data = (llm or make_backend(_cfg(ws), ws.secrets())).call("planner", TAGS_SYSTEM, prompt, schema, tools=()).data or {}
        tags = data.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    got = yt_tags.clean(tags)
    if not got:
        raise ValueError("no usable tags: write them separated by commas")
    item = _update(ws, pid, tags=got)
    if item.get("slug"):   # the written script's youtube.json follows the plan
        from . import voice_desk
        f = voice_desk._root(ws) / "episodes" / item["slug"] / "youtube.json"
        try:
            meta = json.loads(f.read_text())
            meta["tags"] = yt_tags.merge(got, meta.get("tags"))
            f.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        except (OSError, ValueError):
            pass
    return item


def remove(ws, pid):
    """Delete a plan from the Factory (its written script stays in the factory's episodes folder, unused)."""
    item = get(ws, pid)
    if item.get("state") in ("writing", "making"):
        raise ValueError("this plan is being worked on: delete it when the script or the video is finished")
    with _lock:
        st = load(ws)
        st["items"] = [i for i in st["items"] if i["id"] != pid]
        _save(ws, st)
    return {"ok": True}


# ---------- 2. the script: a crew run that writes it and stops before the video ----------
def _topic_out(item):
    owner = {k: item[k] for k in ("title", "angle", "context", "example", "takeaway", "tags") if item.get(k)}
    if item.get("instructions"):
        owner["instructions for the script"] = item["instructions"]
    return {"topic": item["title"], "angle": item.get("angle") or item["title"], "why_now": "your Factory plan", "planned": "factory",
            "owner_plan": owner}


def _run(ws, options, fmt):
    from . import crew, monthly
    cfg = _cfg(ws)
    category = monthly.category_for_item(ws, PLATFORM, fmt)
    if crew.is_running():
        raise ValueError("a crew run is in progress: try again when it finishes")
    return crew.run_crew(ws, crew.target_date(cfg), category, platform=PLATFORM, options=dict(options, format=fmt))


def write_script(ws, pid, instructions="", runner=None):
    """Write (or write again) the plan's script with your instructions, in the Looks ticked in the Factory now."""
    from . import factory_styles
    item = get(ws, pid)
    if item.get("state") in ("writing", "making"):
        raise ValueError("this plan is already being worked on")
    instructions = str(instructions or "").strip()[:2000]
    item = _update(ws, pid, instructions=instructions, state="writing", looks=factory_styles.ticked(ws), error=None)
    options = {"kept": {"topic": _topic_out(item)}, "kept_from": "your Factory plan", "rewrite": True, "plan_id": pid,
               "notes": [instructions] if instructions else []}

    def go():
        try:
            res = (runner or _run)(ws, options, item.get("format", "short"))
            slug = _slug_of(ws, res)
            if slug:
                _update(ws, pid, state="script", slug=slug, script_run=res.get("run_id"), error=None)
            else:
                _update(ws, pid, state="planned", error=(res or {}).get("reason") or "the script was not written")
        except Exception as e:
            _update(ws, pid, state="planned", error=str(e)[:400])
            raise
    _job(pid, go)
    return get(ws, pid)


def _slug_of(ws, res):
    import json
    rid = (res or {}).get("run_id")
    if not rid:
        return None
    try:
        return json.loads((ws.runs_dir / rid / "writer.json").read_text()).get("slug")
    except (OSError, ValueError):
        return None


# ---------- 3. the video: by hand, once the script and the voice are approved ----------
# The looks a video can be made in from the Factory's "Use a plan" list (owner, 2026-11-18: "select approved plan script from the drop
# down to create a video and select style also"). Isometric and Signal (blue) are both canvas looks with the same narration beats, so an
# approved script and voice made for one can be drawn again in the other; the other looks write a different kind of script.
LOOKS = {"iso": "Isometric Pastel", "blue": "Signal (blue)"}


def look_of(d, ep=None):
    """The look an episode's script was written in: "iso", "blue", or another factory style ("3d", "signal", "story", ...)."""
    import json
    w = (d or {}).get("writer") or {}
    if w.get("look"):
        return w["look"]
    try:
        style = json.loads((ep / "script.json").read_text()).get("style") if ep else None
    except (OSError, ValueError):
        style = None
    return style or w.get("style") or ""


def looks_for(current):
    """The looks this script can be made in, each {id, label, ok, why}."""
    out = [{"id": k, "label": v, "ok": current in LOOKS, "why": "" if current in LOOKS else "needs a script written in this look (Write again with it ticked)"}
           for k, v in LOOKS.items()]
    if current and current not in LOOKS:
        out.insert(0, {"id": current, "label": f"{current.capitalize()} (as written)", "ok": True, "why": ""})
    return out


def busy():
    return any(j.get("done") is None for j in _jobs.values())


def recover(ws):
    """At start: a plan left "writing" or "making" by a restart has no job any more. Put it back where it was, with the reason."""
    notes = []
    for i in load(ws)["items"]:
        if i.get("state") in ("writing", "making") and (_jobs.get(i["id"]) or {}).get("done", "x") is not None:
            back = "planned" if i["state"] == "writing" else "script"
            what = "writing its script" if i["state"] == "writing" else "making its video"
            _update(ws, i["id"], state=back, error=f"the Studio restarted while {what}: press {'Write script' if back == 'planned' else 'Make the video'} again")
            notes.append(f"Factory plan {i['id']} ({i.get('title', '')[:50]}) was interrupted while {what}: back to {back}")
    return notes


def _by_slug(ws, slug):
    return next((i for i in load(ws)["items"] if slug and i.get("slug") == slug), None)


def unmake(ws, slug):
    """Its video was deleted in the Factory: the plan is ready to be made again (script and voice stay approved), and the copy waiting
    in the Queue goes."""
    from . import voice_desk
    ep = voice_desk._root(ws) / "episodes" / slug
    d = voice_desk.desk(ep)
    run_id = (d.get("run") or {}).get("id")
    ws.save_queue([p for p in ws.queue() if not (p.get("platform") == "youtube" and p.get("status") not in ("published", "publishing")
                                                 and (p.get("factory_slug") == slug or (run_id and p.get("run_id") == run_id)))])
    if d:
        d.pop("run", None)
        voice_desk._save_desk(ep, d)
    item = _by_slug(ws, slug)
    if item and item.get("state") in ("made", "making", "script", "editing"):
        _update(ws, item["id"], state="script", error=None)
    return item


def mark_published(ws, slug, post):
    item = _by_slug(ws, slug)
    if item:
        _update(ws, item["id"], state="published", published={"at": _now(), "url": post.get("url") or post.get("video_url"),
                                                             "visibility": post.get("privacy") or post.get("visibility")})


def ticked_look(ws):
    """The canvas look the ticked Looks ask for: Signal ticked alone = "blue", Isometric = "iso"; None for any other choice."""
    t = factory_styles.ticked(ws)
    return {("signal",): "blue", ("iso",): "iso"}.get(tuple(t))


def ready(ws):
    """Plans whose script and voice are approved: they can be made now, in their own look or one that keeps the same narration."""
    from . import voice_desk
    out = []
    for i in load(ws)["items"]:
        if i.get("state") != "script" or not i.get("slug") or (_jobs.get(i["id"]) or {}).get("done", "x") is None:
            continue
        ep = voice_desk._root(ws) / "episodes" / i["slug"]
        d = voice_desk.desk(ep)
        if d.get("script") != "approved" or (d.get("voice") or {}).get("state") != "approved":
            continue
        cur = look_of(d, ep)
        out.append({"id": i["id"], "title": i.get("title") or d.get("title") or i["slug"], "format": i.get("format", "short"), "look": cur,
                    "want": (ticked_look(ws) if cur in LOOKS and cur != "iso" else None) or cur,
                    "voice": (d.get("voice") or {}).get("mode") or "", "looks": looks_for(cur)})
    return out


def stale_drawing(ep):
    """An Isometric animation drawn before the owner's label rules (2026-11-22: texts blocked each other; names must be printed on the
    objects with nameOn, states float with label()). Make video then draws it again in the same look; the approved words and voice stay.
    (2026-11-23: a video made from a script written that morning still had the old floating, overlapping chips.)"""
    f = Path(ep) / "explainer.js"
    try:
        return f.exists() and "nameOn(" not in f.read_text()
    except OSError:
        return False


def themes():
    """The Isometric themes the owner can pick at Make video and in the video editor (owner, 2026-11-24)."""
    from .factory_styles import VARIANTS
    return [{"id": k, "label": v["label"], "what": v["what"]} for k, v in VARIANTS.items() if k != "auto"]


def set_theme(ep, theme):
    """An Isometric video's theme lives in its script.json ("variant"); the drawing stays, its colours and set change."""
    import json
    from .factory_styles import VARIANTS
    theme = str(theme or "").strip()
    if not theme:
        return None
    if theme not in VARIANTS or theme == "auto":
        raise ValueError(f"unknown theme {theme!r}")
    f = Path(ep) / "script.json"
    script = json.loads(f.read_text())
    if script.get("style", "iso") != "iso":
        raise ValueError("themes are for Isometric videos")
    if script.get("variant") != theme:
        script["variant"] = theme
        f.write_text(json.dumps(script, indent=1, ensure_ascii=False))
    return theme


def dark_drawing(ws, ep):
    """The storyboard check says the drawing is dark although its theme is light (make-iso.mjs, 2026-11-25)."""
    import subprocess
    from . import voice_desk
    root = voice_desk._root(ws)
    try:
        r = subprocess.run(["node", str(root / "pipeline" / "make-iso.mjs"), str(ep), "--check"], cwd=str(root), capture_output=True,
                           text=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return False
    return "theme is light but the frames are dark" in (r.stderr or "")


def make(ws, pid, look=None, runner=None, theme=None):
    from . import voice_desk
    item = get(ws, pid)
    if not item.get("slug"):
        raise ValueError("write the script first")
    ep = voice_desk._root(ws) / "episodes" / item["slug"]
    d = voice_desk.desk(ep)
    if d.get("script") != "approved" or (d.get("voice") or {}).get("state") != "approved":
        raise ValueError("approve the script and the voice first")
    if item.get("state") == "making":
        raise ValueError("the video is already being made")
    cur, look = look_of(d, ep), str(look or "").strip()
    if not look and cur in LOOKS and cur != "iso":
        # no look picked: the Looks ticked in the Factory (owner, 2026-11-18: "single blue" made it isometric). An Isometric script
        # stays Isometric (owner, 2026-11-25: "my isometric is not coming as before": a Signal tick redrew it in Tech Glow)
        look = ticked_look(ws) or ""
    if look and look != cur:
        if look not in LOOKS or cur not in LOOKS:
            raise ValueError(f"this script was written for the {cur or 'other'} look: write it again with that look ticked to make it in another one")
    else:
        look = ""
    if not look and cur == "iso" and stale_drawing(ep):   # drawn before the label rules (owner, 2026-11-22): draw it again, same look
        look = cur
    if theme and (look or cur) == "iso":   # the theme picked at Make video (owner, 2026-11-24)
        set_theme(ep, theme)
    _update(ws, pid, state="making", error=None, made_look=look or cur, **({"theme": theme} if theme else {}))
    if look:   # draw it again in the other canvas look; the approved words and voice stay (ShortsWriter.run, options.restyle)
        options = {"kept": {"topic": _topic_out(item)}, "kept_from": "your approved script", "plan_id": pid, "restyle": look, "slug": item["slug"],
                   **({"variant": theme} if theme else {})}
    else:
        options = {"kept": {"topic": _topic_out(item), "writer": d["writer"]}, "kept_from": "your approved script", "plan_id": pid}

    def go():
        try:
            if not options.get("restyle") and (look or cur) == "iso" and runner is None and dark_drawing(ws, ep):
                # drawn dark in a light theme (owner, 2026-11-25: "trying to create in pastel look but it is generating in black"):
                # draw it again in the theme, same words and voice
                options.update(kept={"topic": _topic_out(item)}, restyle="iso", slug=item["slug"])
            res = (runner or _run)(ws, options, item.get("format", "short"))
            if res and res.get("ok"):
                post = res.get("post") or {}
                # it waits in the video editor until the owner approves it there (owner, 2026-11-23); an older queue path goes straight to made
                _update(ws, pid, state="editing" if post.get("status") == "editing" else "made", made_at=_now(), post_id=post.get("id") or post.get("post_id"),
                        video_run=res.get("run_id"))
                voice_desk.mark_run(ws, item["slug"], res.get("run_id"), "made")
            else:
                _update(ws, pid, state="script", error=(res or {}).get("reason") or "the video was not made", video_run=(res or {}).get("run_id"))
        except Exception as e:
            _update(ws, pid, state="script", error=str(e)[:400])
            raise
    _job(pid, go)
    return get(ws, pid)


# ---------- the Studio's view ----------
def view(ws):
    from . import voice_desk
    import json
    out, made, thumbs = [], 0, []
    waiting = {(p.get("youtube") or {}).get("episode") for p in ws.queue() if p.get("status") not in ("published", "publishing", "vetoed")}
    for i in load(ws)["items"]:
        # a made video stays on the list until it is uploaded, so it can still be edited (owner, 2026-11-24: "how to update once the
        # video is made?")
        editable = bool(i.get("slug")) and (voice_desk._root(ws) / "episodes" / i["slug"] / "explainer.js").exists()
        if i.get("state") == "published" or (i.get("state") == "made" and not (editable and i.get("slug") in waiting)):
            made += 1
            th = voice_desk._root(ws) / "episodes" / i["slug"] / "thumbnail.jpg" if i.get("slug") else None
            if th and th.exists():   # its designed thumbnail stays downloadable (owner, 2026-11-26: "I'll add it manually")
                thumbs.append({"title": i.get("title") or i["slug"], "slug": i["slug"], "at": th.stat().st_mtime,
                               "url": f"/factory-thumb/{i['slug']}.jpg?v={int(th.stat().st_mtime)}"})
            continue
        row = dict(i, job=_jobs.get(i["id"]))
        if i.get("slug"):
            try:
                row["episode"] = voice_desk.episode(ws, i["slug"])
                cur = look_of(voice_desk.desk(voice_desk._root(ws) / "episodes" / i["slug"]), voice_desk._root(ws) / "episodes" / i["slug"])
                row["want"] = (ticked_look(ws) if cur in LOOKS and cur != "iso" else None) or cur
                ep = voice_desk._root(ws) / "episodes" / i["slug"]
                if cur == "iso" or (row["want"] == "iso"):
                    try:
                        row["theme"] = json.loads((ep / "script.json").read_text()).get("variant") or "pastel"
                    except (OSError, ValueError):
                        row["theme"] = "pastel"
                row["editable"] = (ep / "explainer.js").exists() and i.get("state") in ("editing", "made")
            except ValueError:
                row["episode"] = None
        out.append(row)
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    for row in out:
        th = voice_desk._root(ws) / "episodes" / row["slug"] / "thumbnail.jpg" if row.get("slug") else None
        if th and th.exists():
            row["thumbnail"] = f"/factory-thumb/{row['slug']}.jpg?v={int(th.stat().st_mtime)}"
    thumbs.sort(key=lambda t: t["at"], reverse=True)
    return {"plans": out, "made": made, "planning": _jobs.get("plan"), "themes": themes(), "thumbnails": thumbs[:12]}
