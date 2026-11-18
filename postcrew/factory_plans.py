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
  making   -> you pressed Make the video: the crew renders it in the style the script was written in, and queues it
  made     -> the video is in the Queue; only now does the plan leave the list
Nothing else removes a plan, except your own Remove.
"""
import threading
import uuid
from datetime import date, datetime, timezone

from . import platforms

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
    owner = {k: item[k] for k in ("title", "angle", "context", "example", "takeaway") if item.get(k)}
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
def make(ws, pid, runner=None):
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
    _update(ws, pid, state="making", error=None)
    options = {"kept": {"topic": _topic_out(item), "writer": d["writer"]}, "kept_from": "your approved script", "plan_id": pid}

    def go():
        try:
            res = (runner or _run)(ws, options, item.get("format", "short"))
            if res and res.get("ok"):
                post = res.get("post") or {}
                _update(ws, pid, state="made", made_at=_now(), post_id=post.get("id"), video_run=res.get("run_id"))
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
    out, made = [], 0
    for i in load(ws)["items"]:
        if i.get("state") == "made":
            made += 1
            continue
        row = dict(i, job=_jobs.get(i["id"]))
        if i.get("slug"):
            try:
                row["episode"] = voice_desk.episode(ws, i["slug"])
            except ValueError:
                row["episode"] = None
        out.append(row)
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"plans": out, "made": made, "planning": _jobs.get("plan")}
