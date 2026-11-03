"""`postcrew motion ...`: the Reference Library, the house style, feedback, and a quality check of any finished video.

    postcrew motion add VIDEO --rights own|licensed|permission|public-domain [--title T] [--creator C] [--notes N] [--no-analyze]
    postcrew motion list
    postcrew motion show ID
    postcrew motion analyze ID            # measure + describe again (a newer analyser, or after a failure)
    postcrew motion approve ID | reject ID | delete ID
    postcrew motion style                 # the current house style
    postcrew motion style --build         # merge the approved references into a new version
    postcrew motion style --use N | --reset
    postcrew motion check RUN_ID|VIDEO    # the Quality Director's look at a finished video, without a crew run
    postcrew motion feedback RUN_ID|POST_ID --kind K [--rating 1-5] [--scene N] [--comment TEXT]
    postcrew motion feedback --list
    postcrew motion feedback --approve ID [--rule TEXT]   # only approved notes change how the crew works
    postcrew motion prefs [--forget N]
"""
import json
from pathlib import Path

from . import library as lib


def add_parser(sub):
    m = sub.add_parser("motion", help="Motion Studio: reference videos, house style, feedback, quality check")
    ms = m.add_subparsers(dest="mcmd", required=True)
    a = ms.add_parser("add", help="add a video you are allowed to learn from")
    a.add_argument("file")
    a.add_argument("--rights", required=True, choices=lib.RIGHTS, help="your right to use it: own, licensed, permission, public-domain")
    a.add_argument("--title", default="")
    a.add_argument("--creator", default="")
    a.add_argument("--notes", default="", help="what you like about it (the analyser reads this)")
    a.add_argument("--no-analyze", action="store_true")
    ms.add_parser("list")
    for name in ("show", "analyze", "approve", "reject", "delete"):
        ms.add_parser(name).add_argument("id")
    st = ms.add_parser("style", help="the house style")
    st.add_argument("--build", action="store_true", help="merge the approved references into a new version")
    st.add_argument("--use", type=int, help="make version N current again")
    st.add_argument("--reset", action="store_true", help="go back to the built-in house style")
    ck = ms.add_parser("check", help="the Quality Director's look at a finished video")
    ck.add_argument("target", help="a run id (workspace/runs/<id>) or a video file")
    ck.add_argument("--no-ai", action="store_true", help="measure only, no vision model")
    fb = ms.add_parser("feedback", help="rate a finished video, list or approve notes")
    fb.add_argument("video", nargs="?")
    fb.add_argument("--kind", default="other", choices=lib.FEEDBACK_KINDS)
    fb.add_argument("--rating", type=int)
    fb.add_argument("--scene", type=int)
    fb.add_argument("--comment", default="")
    fb.add_argument("--list", action="store_true")
    fb.add_argument("--approve")
    fb.add_argument("--rule", default="", help="with --approve: the rule to learn, in your words")
    pr = ms.add_parser("prefs", help="the approved preferences the crew follows")
    pr.add_argument("--forget", type=int)
    return m


def run(ws, a):
    L = lib.Library(ws)
    c = a.mcmd
    try:
        if c == "add":
            meta = L.add(a.file, a.rights, a.title, a.creator, a.notes)
            print(f"added {meta['id']}: {meta['title']} ({meta['seconds']:.0f}s, {meta['width']}x{meta['height']}, rights: {meta['rights']})")
            if a.no_analyze:
                return 0
            from .analyze import analyze
            analyze(ws, meta["id"])
            return 0
        if c == "list":
            refs = L.references()
            if not refs:
                print("no reference videos yet: postcrew motion add VIDEO --rights own")
            for m in refs:
                f = m.get("measured") or {}
                print(f"{m['id']}  {m['status']:<15} {m['seconds']:>5.0f}s  {f.get('cuts_per_minute', '-'):>5} cuts/min  {m['title'][:50]}")
            h = L.house()
            print(f"\nhouse style: {h.get('profile_name')} v{h.get('version', 0)} ({h.get('source')}); "
                  f"{len(L.preferences())} approved preference(s)")
            return 0
        if c == "show":
            print(json.dumps({"meta": L.meta(a.id), "analysis": L.analysis(a.id)}, indent=1))
            return 0
        if c == "analyze":
            from .analyze import analyze
            L.set_status(a.id, "analyzing")
            analyze(ws, a.id)
            return 0
        if c in ("approve", "reject"):
            if c == "approve" and not L.analysis(a.id):
                print("analyse it first: postcrew motion analyze " + a.id)
                return 2
            m = L.set_status(a.id, "ready" if c == "approve" else "rejected")
            print(f"{m['id']}: {m['status']}" + (". Build the house style with: postcrew motion style --build" if c == "approve" else ""))
            return 0
        if c == "delete":
            L.delete(a.id)
            print(f"deleted {a.id} and its files")
            return 0
        if c == "style":
            if a.build:
                from .analyze import build_house
                build_house(ws)
            elif a.use:
                L.use_version(a.use)
            elif a.reset:
                L.reset_house()
            print(L.brief())
            v = L.versions()
            if v:
                print("\nversions: " + ", ".join(f"v{x['version']} ({x['created_at'][:10]}, {len(x['from'])} ref)" for x in v))
            return 0
        if c == "check":
            return check(ws, a.target, ai=not a.no_ai)
        if c == "feedback":
            if a.list:
                for f in L.feedback():
                    print(f"{f['id']}  {'approved' if f['approved'] else 'pending ':<8} {f['video']}  scene {f['scene'] or '-'}  "
                          f"{f['kind']}  {f['rating'] or ''}  {f['comment'][:60]}")
                return 0
            if a.approve:
                prefs = L.approve_feedback(a.approve, a.rule)
                print(f"approved: the crew now follows {len(prefs)} preference(s):\n" + "\n".join(f"  {i}. {p['rule']}" for i, p in enumerate(prefs, 1)))
                return 0
            if not a.video:
                print("name the video: a run id or a post id")
                return 2
            f = L.add_feedback(a.video, a.rating, a.kind, a.comment, a.scene)
            print(f"noted {f['id']}. It changes nothing until you approve it: postcrew motion feedback --approve {f['id']}")
            return 0
        if c == "prefs":
            prefs = L.forget_preference(a.forget) if a.forget else L.preferences()
            print("\n".join(f"{i}. {p['rule']}" for i, p in enumerate(prefs, 1)) or "no approved preferences yet")
            return 0
    except (ValueError, KeyError) as e:
        print(f"motion {c}: {str(e).strip(chr(39))}")
        return 2
    return 1


def check(ws, target, ai=True, llm=None, log=print):
    """Run the Quality Director's look on a finished video outside a crew run. Prints the verdict; returns 0 when it would pass."""
    from ..agents import quality as q
    from ..agents.direction import motion_cfg
    from . import frames as fr
    run_dir = Path(ws.root) / "runs" / target
    scenes, media = [], {}
    if run_dir.is_dir():
        media = json.loads((run_dir / "media.json").read_text())
        video = Path(media["path"]) if Path(media["path"]).exists() else run_dir / "video.mp4"
        media["path"] = str(video)
        for name in ("graphics.json", "writer.json"):   # graphics.json does not hold scenes; writer.json is the approved script
            p = run_dir / name
            if p.exists() and "scenes" in json.loads(p.read_text()):
                scenes = json.loads(p.read_text())["scenes"]
                break
        out_dir = run_dir
    else:
        video = Path(target).expanduser()
        if not video.is_file():
            print(f"no run and no file called {target}")
            return 2
        media = {"path": str(video), "seconds": fr.probe(video)["seconds"]}
        out_dir = video.parent
    if media.get("scene_seconds") and len(scenes) != len(media["scene_seconds"]):   # the script was split after it was saved
        scenes = [{"narration": "", "layout": "?", "seconds": s} for s in media["scene_seconds"]]
    if not scenes:
        sh = fr.shots(video, media.get("seconds"), max_shots=16)
        scenes = [{"narration": "", "layout": "?", "seconds": b - a} for a, b in sh]
        media["scene_seconds"] = [b - a for a, b in sh]

    class Ctx:   # just enough of a run for the agent's look
        pass
    ctx = Ctx()
    ctx.run = type("R", (), {"dir": out_dir})()
    agent = q.QualityDirectorAgent()
    measures, sheets = agent.look(ctx, media, scenes)
    L = lib.Library(ws)
    findings = q.picture_findings(measures, float(L.house()["motion_language"].get("max_still_seconds", 3.5)) * 1.5)
    for f in findings:
        log(f"  {f['severity']:<5} {f['message']}")
    score = max(0, 100 - 25 * sum(f["severity"] == "error" for f in findings) - 6 * sum(f["severity"] == "warn" for f in findings))
    if ai:
        from .analyze import backend
        cfg = ws.config()
        name = (cfg.get("profile") or {}).get("name") or "the channel"
        system = (Path(__file__).resolve().parent.parent / "prompts" / "youtube" / "quality.md").read_text() \
            .replace("{{house}}", L.brief()).replace("{{name}}", name)
        try:
            res = backend(ws, llm).call("quality", system, agent._report(scenes, measures, findings), q.SCHEMA,
                                        cwd=str(out_dir), images=[str(p) for p in sheets])
            r = res.data
            score = r["overall"] if not any(f["severity"] == "error" for f in findings) else min(r["overall"], 59)
            log(f"\nvision review (${res.cost_usd:.3f}): {r['summary']}")
            log("  " + ", ".join(f"{k} {v}" for k, v in r["scores"].items()))
            for s in r["scenes"]:
                log(f"  scene {s['scene']} [{s['severity']}] {s['problem']}" + (" -> redraw as " + str(s.get("layout")) if s.get("redraw") else ""))
        except Exception as e:
            log(f"\nno vision review: {str(e)[:200]}")
    min_score = 75
    try:
        from .. import platforms
        min_score = motion_cfg(type("C", (), {"cfg": platforms.view(ws.config(), "youtube")})())["min_score"]
    except Exception:
        pass
    log(f"\npicture quality {score}/100 ({'passes' if score >= min_score else 'would be redrawn'}; pass mark {min_score}). "
        f"Contact sheets: {', '.join(str(s) for s in sheets)}")
    return 0 if score >= min_score else 1
