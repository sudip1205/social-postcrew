"""postcrew - a crew of AI agents that writes, reviews and publishes your LinkedIn posts.

  python3 -m postcrew demo                 try it: a full crew run on scripted answers (no AI, no LinkedIn)
  python3 -m postcrew init                 create the workspace (settings, secrets, queue)
  python3 -m postcrew serve [--port 8765]  open the Studio and start the scheduler (add --lan to open it to your network)
  python3 -m postcrew run [--date D] [--category C] [--dry-run]   run the crew once now
  python3 -m postcrew publish              publish whatever is due
  python3 -m postcrew check                check LinkedIn + Claude credentials
  python3 -m postcrew doctor               check everything needed is installed and configured
  python3 -m postcrew status               queue and recent runs
  python3 -m postcrew plan                 write this month's plans for your topics now (assign them to days in the Studio)
  python3 -m postcrew import FILE          add posts you published elsewhere, so they are never repeated
"""
import argparse
import json
import shutil
from pathlib import Path
import sys

from . import __version__
from .workspace import Workspace, default_root, validate_config


def cmd_doctor(ws):
    from .agents.credentials import check_ai
    cfg = ws.config()
    rows = [("Python 3.9+", sys.version_info >= (3, 9), sys.version.split()[0])]
    try:
        import PIL
        rows.append(("Pillow (posters)", True, PIL.__version__))
    except ImportError:
        rows.append(("Pillow (posters)", False, "pip install Pillow"))
    rows.append(("ffmpeg (algorithm videos)", bool(shutil.which("ffmpeg")),
                 "found" if shutil.which("ffmpeg") else "brew install ffmpeg / sudo apt install ffmpeg"))
    cl = check_ai(ws, cfg)
    rows.append((f"AI: {cl['provider']}", cl["state"] == "ok", cl["message"]))
    errs = validate_config(cfg)
    rows.append(("Settings", not errs, "valid" if not errs else "; ".join(errs[:3])))
    s = ws.secrets()
    rows.append(("LinkedIn app", bool(s.get("linkedin_client_id") and s.get("linkedin_client_secret")),
                 "set" if s.get("linkedin_client_id") else "add it in Studio > Credentials"))
    rows.append(("LinkedIn connected", bool(s.get("linkedin_access_token")),
                 s.get("linkedin_name") or "click Connect LinkedIn in Studio > Credentials"))
    rows.append(("Publishing mode", True, "DRY RUN (nothing is sent)" if cfg["publishing"]["dry_run"] else
                 f"LIVE, approval: {cfg['publishing']['approval']}"))
    if cfg["platforms"]["youtube"]["enabled"]:
        yt = cfg["platforms"]["youtube"]
        rows.append(("YouTube: ffmpeg (videos)", bool(shutil.which("ffmpeg")), "found" if shutil.which("ffmpeg") else
                     "brew install ffmpeg / sudo apt install ffmpeg"))
        rows.append(("YouTube: ElevenLabs voice", bool(s.get("elevenlabs_api_key") and yt["video"]["voice"].get("voice_id")),
                     yt["video"]["voice"].get("voice_name") or "add the API key in Credentials and choose a voice in Settings"))
        rows.append(("YouTube connected", bool(s.get("youtube_refresh_token")),
                     s.get("youtube_channel_title") or "click Connect YouTube in Studio > Credentials"))
        rows.append(("YouTube publishing", True, "DRY RUN (nothing is uploaded)" if yt["publishing"]["dry_run"] else
                     f"LIVE, approval: {yt['publishing']['approval']}, {yt['publishing'].get('visibility', 'public')}"))
    for name, ok, detail in rows:
        print(f"  {'OK ' if ok else 'NO '} {name:<28} {detail}")
    return 0 if all(ok for _, ok, _ in rows[:5]) else 1


def cmd_import(ws, path):
    """FILE: JSON list of posts, or {"posts": [...]}; each needs "date" and "topic" ("text", "category" optional)."""
    with open(path) as f:
        data = json.load(f)
    posts = data.get("posts", []) if isinstance(data, dict) else data
    have = {(p.get("date"), p.get("topic")) for p in ws.history()}
    added = 0
    for p in posts:
        if not (isinstance(p, dict) and p.get("date") and p.get("topic")):
            print(f"  skipped (needs date and topic): {str(p)[:60]}")
            continue
        if (p["date"], p["topic"]) in have:
            continue
        ws.add_history({"id": p.get("id") or f"import-{p['date']}", "date": p["date"], "topic": p["topic"],
                        "category": p.get("category", ""), "text": p.get("text", ""), "imported": True})
        have.add((p["date"], p["topic"]))
        added += 1
    print(f"Imported {added} post(s) into the history; the crew will not repeat them.")
    return 0


def cmd_plan_import(ws, path, apply_schedule=False):
    """Load per-day briefs from a text file: `## YYYY-MM-DD` sections of `Key: value` lines (see docs/topic-briefs.md)."""
    import re
    from datetime import datetime
    from . import brief as briefmod
    from .agents.planner import set_entry
    from .workspace import WEEKDAYS
    text = Path(path).read_text()
    parts = re.split(r"(?m)^##\s+(\d{4}-\d{2}-\d{2})\s*$", text)
    if len(parts) < 3:
        print("No '## YYYY-MM-DD' sections found.")
        return 2
    cfg, bad, done = ws.config(), [], []
    for day, body in zip(parts[1::2], parts[2::2]):
        try:
            wd = WEEKDAYS[datetime.strptime(day, "%Y-%m-%d").weekday()]
            raw = briefmod.parse_text(body)
            topic, angle = (raw.get("topic") or "").strip(), (raw.get("angle") or "").strip()
            cat = raw.get("category") or cfg["schedule"]["days"].get(wd) or "briefed"
            if cat not in cfg["categories"]:
                raise ValueError(f"unknown category {cat!r}")
            if not 5 <= len(topic) <= 90:
                raise ValueError("Topic: must be 5-90 characters")
            entry = {"category": cat, "topic": topic, "angle": angle[:400], "search_queries": [], "source": "manual",
                     "rejected": []}
            brief = briefmod.normalize(raw)
            if brief:
                entry["brief"] = brief
            if cfg["schedule"]["days"].get(wd) != cat:
                if not apply_schedule:
                    print(f"  note: {day} is a {wd} and {wd} is scheduled as {cfg['schedule']['days'].get(wd)!r}, not {cat!r}; "
                          f"use --apply-schedule to schedule {cat!r} on every {wd}.")
                else:
                    cfg["schedule"]["days"][wd] = cat
            set_entry(ws, day, entry)
            done.append(day)
        except (ValueError, briefmod.BriefError) as e:
            bad.append(f"{day}: {e}")
    if apply_schedule:
        ws.save_config(cfg)
    print(f"Planned {len(done)} day(s): {', '.join(done)}")
    for b in bad:
        print("  skipped " + b)
    return 1 if bad else 0


def cmd_demo(ws, port, browser=True):
    """A separate demo workspace on the scripted demo provider: start one practice run, open the Studio."""
    import threading
    import webbrowser
    from . import demo
    from .crew import post_for, run_crew, target_date
    from .studio.server import serve
    cfg = ws.config()
    if cfg["llm"]["backend"] != "demo":   # first time: set the demo workspace up
        cfg["llm"]["backend"] = "demo"
        cfg["publishing"]["dry_run"] = True
        cfg["notifications"]["desktop"] = False
        cfg["profile"].update(name=cfg["profile"]["name"] or "Demo User",
                              handle=cfg["profile"]["handle"] or "example.com/demo")
        cfg["schedule"]["days"] = {d: demo.CATEGORY for d in cfg["schedule"]["days"]}
        ws.save_config(cfg)
    day = target_date(cfg)
    url = f"http://localhost:{port}/#{'queue' if post_for(ws, day) else 'workflow'}"
    print(f"Postcrew demo: scripted answers, practice mode, nothing leaves this computer.\n"
          f"Workspace: {ws.root}\nWatch the crew at {url}  (Ctrl+C to stop)\n"
          f"To write real posts: python3 -m postcrew init, then serve (see docs/getting-started.md).", flush=True)

    def start():
        if not post_for(ws, day):
            run_crew(ws, day, demo.CATEGORY)
    threading.Timer(1.5, start).start()
    if browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    serve(ws, port, scheduler=False)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="postcrew", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", help="workspace folder (default: $POSTCREW_HOME, ./workspace in a checkout, or ~/.postcrew)")
    ap.add_argument("--version", action="version", version=f"postcrew {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="a full crew run on scripted answers: no AI account, key or LinkedIn needed")
    dm.add_argument("--port", type=int, default=8765)
    dm.add_argument("--no-browser", action="store_true")
    sub.add_parser("init")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    sv.add_argument("--lan", action="store_true", help="listen on the local network (same as --host 0.0.0.0); needs the access token")
    sv.add_argument("--token", help="the access token for a Studio opened to the network (default: made once, kept in the workspace)")
    sv.add_argument("--no-scheduler", action="store_true", help="Studio only; use cron/systemd for the schedule")
    r = sub.add_parser("run")
    r.add_argument("--date", help="post date YYYY-MM-DD (default: per schedule.lead_days)")
    r.add_argument("--category")
    r.add_argument("--dry-run", action="store_true", help="run every agent but do not queue the post")
    r.add_argument("--platform", default="linkedin", help="the app to write for (default: linkedin)")
    r.add_argument("--format", choices=["short", "long"], help="YouTube: make a short or a long video this time")
    r.add_argument("--seconds", type=int, help="YouTube: about how long the video should be")
    sub.add_parser("publish")
    sub.add_parser("check")
    sub.add_parser("doctor")
    sub.add_parser("status")
    pl = sub.add_parser("plan")
    pl.add_argument("--platform", default="linkedin", help="the app to plan (default: linkedin)")
    im = sub.add_parser("import")
    im.add_argument("file")
    pi = sub.add_parser("plan-import", help="load per-day topic briefs from a text file")
    pi.add_argument("file")
    pi.add_argument("--apply-schedule", action="store_true", help="also schedule each day's category on that weekday")
    a = ap.parse_args(argv)

    if a.cmd == "demo" and not a.workspace:
        a.workspace = default_root("workspace-demo")   # never the real workspace
    ws = Workspace(a.workspace).init()
    if a.cmd == "demo":
        return cmd_demo(ws, a.port, browser=not a.no_browser)
    if a.cmd == "init":
        print(f"Workspace ready: {ws.root}\nNext: python3 -m postcrew serve, then open http://localhost:8765")
        return 0
    if a.cmd == "serve":
        from .studio.server import serve
        serve(ws, a.port, scheduler=not a.no_scheduler, host="0.0.0.0" if a.lan else a.host, token=a.token)
        return 0
    if a.cmd == "doctor":
        return cmd_doctor(ws)
    if a.cmd == "check":
        from .agents.credentials import run_check
        st = run_check(ws)
        print(json.dumps({k: v for k, v in st.items()}, indent=2))
        return 0 if st["ok"] else 2
    if a.cmd == "publish":
        if ws.paused():
            print("PAUSE file present: not publishing.")
            return 0
        from .agents.publisher import publish_due
        res = publish_due(ws)
        print(f"{len(res)} post(s) processed" + "".join(f"\n  {p['id']}: {p['status']}" for p in res))
        return 1 if any(p["status"] == "failed" for p in res) else 0
    if a.cmd == "run":
        if ws.paused():
            print("PAUSE file present: not running.")
            return 0
        errs = validate_config(ws.config())
        if errs:
            print("Fix the settings first:\n  " + "\n  ".join(errs))
            return 2
        from .crew import run_crew
        options = {k: v for k, v in (("format", a.format), ("target_seconds", a.seconds)) if v}
        res = run_crew(ws, a.date, a.category, dry_run=a.dry_run, echo=True, platform=a.platform, options=options)
        print(json.dumps({k: res.get(k) for k in ("ok", "run_id", "reason", "failed_step", "cost_usd")}, indent=2))
        return 0 if res.get("ok") else 1
    if a.cmd == "import":
        return cmd_import(ws, a.file)
    if a.cmd == "plan-import":
        return cmd_plan_import(ws, a.file, a.apply_schedule)
    if a.cmd == "plan":
        from . import monthly
        from .crew import local_now
        try:
            out = monthly.generate(ws, a.platform, monthly.month_key(local_now(ws.config()).date()))
        except ValueError as e:
            print(e)
            return 2
        for topic, r in out["topics"].items():
            print(f"  {topic}: " + (f"FAILED: {r['error']}" if isinstance(r, dict) else f"{r} plan(s) written"))
        print(f"{out['added']} plan(s) written. Assign them to days in the Plan page.")
        return 0
    if a.cmd == "status":
        from .crew import list_runs
        for p in ws.queue():
            print(f"  queue  {p['date']}  {p.get('platform') or 'linkedin':<9} {p['status']:<18} {p['topic'][:60]}")
        for r_ in list_runs(ws, 8):
            print(f"  run    {r_['run_id']:<20} {r_['state']:<10} {str(r_.get('result'))[:70]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
