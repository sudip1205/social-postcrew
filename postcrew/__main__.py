"""postcrew - a crew of AI agents that writes, reviews and publishes your LinkedIn posts.

  python3 -m postcrew init                 create the workspace (settings, secrets, queue)
  python3 -m postcrew serve [--port 8765]  open the Studio and start the scheduler
  python3 -m postcrew run [--date D] [--category C] [--dry-run]   run the crew once now
  python3 -m postcrew publish              publish whatever is due
  python3 -m postcrew check                check LinkedIn + Claude credentials
  python3 -m postcrew doctor               check everything needed is installed and configured
  python3 -m postcrew status               queue and recent runs
"""
import argparse
import json
import shutil
import sys

from . import __version__
from .workspace import Workspace, validate_config


def cmd_doctor(ws):
    from .agents.credentials import check_claude
    cfg = ws.config()
    rows = [("Python 3.9+", sys.version_info >= (3, 9), sys.version.split()[0])]
    try:
        import PIL
        rows.append(("Pillow (posters)", True, PIL.__version__))
    except ImportError:
        rows.append(("Pillow (posters)", False, "pip install Pillow"))
    rows.append(("ffmpeg (algorithm videos)", bool(shutil.which("ffmpeg")),
                 "found" if shutil.which("ffmpeg") else "brew install ffmpeg / sudo apt install ffmpeg"))
    cl = check_claude(cfg)
    rows.append(("Claude Code CLI", cl["state"] == "ok", cl["message"]))
    errs = validate_config(cfg)
    rows.append(("Settings", not errs, "valid" if not errs else "; ".join(errs[:3])))
    s = ws.secrets()
    rows.append(("LinkedIn app", bool(s.get("linkedin_client_id") and s.get("linkedin_client_secret")),
                 "set" if s.get("linkedin_client_id") else "add it in Studio > Credentials"))
    rows.append(("LinkedIn connected", bool(s.get("linkedin_access_token")),
                 s.get("linkedin_name") or "click Connect LinkedIn in Studio > Credentials"))
    rows.append(("Publishing mode", True, "DRY RUN (nothing is sent)" if cfg["publishing"]["dry_run"] else
                 f"LIVE, approval: {cfg['publishing']['approval']}"))
    for name, ok, detail in rows:
        print(f"  {'OK ' if ok else 'NO '} {name:<28} {detail}")
    return 0 if all(ok for _, ok, _ in rows[:5]) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="postcrew", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", help="workspace folder (default: $POSTCREW_HOME or ./workspace)")
    ap.add_argument("--version", action="version", version=f"postcrew {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--no-scheduler", action="store_true", help="Studio only; use cron/systemd for the schedule")
    r = sub.add_parser("run")
    r.add_argument("--date", help="post date YYYY-MM-DD (default: per schedule.lead_days)")
    r.add_argument("--category")
    r.add_argument("--dry-run", action="store_true", help="run every agent but do not queue the post")
    sub.add_parser("publish")
    sub.add_parser("check")
    sub.add_parser("doctor")
    sub.add_parser("status")
    a = ap.parse_args(argv)

    ws = Workspace(a.workspace).init()
    if a.cmd == "init":
        print(f"Workspace ready: {ws.root}\nNext: python3 -m postcrew serve, then open http://localhost:8765")
        return 0
    if a.cmd == "serve":
        from .studio.server import serve
        serve(ws, a.port, scheduler=not a.no_scheduler)
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
        res = run_crew(ws, a.date, a.category, dry_run=a.dry_run, echo=True)
        print(json.dumps({k: res.get(k) for k in ("ok", "run_id", "reason", "failed_step", "cost_usd")}, indent=2))
        return 0 if res.get("ok") else 1
    if a.cmd == "status":
        from .crew import list_runs
        for p in ws.queue():
            print(f"  queue  {p['date']}  {p['status']:<18} {p['topic'][:60]}")
        for r_ in list_runs(ws, 8):
            print(f"  run    {r_['run_id']:<20} {r_['state']:<10} {str(r_.get('result'))[:70]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
