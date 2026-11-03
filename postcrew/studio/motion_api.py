"""The Studio's side of Motion Studio (the Style page): references from a file or a URL, analysed for their screens, their script or both,
one at a time in the background; approving them, building the house style, approving feedback.

Analyses run in one worker thread, in the order they were asked for, so two never compete for the AI or ffmpeg. A Studio restart stops a
running analysis: on start, references left half-done are marked failed with the reason, and can be analysed again.
"""
import queue
import shutil
import threading
import traceback
import uuid
from pathlib import Path

from ..motion import fetch as fetch_mod
from ..motion import library as lib

UPLOAD_EXT = lib.VIDEO_EXT


class MotionAPI:
    def __init__(self, ws):
        self.ws = ws
        self.jobs = queue.Queue()
        self.current = None          # the reference being analysed now
        self.logs = {}               # reference id -> its last progress lines
        self.style_job = {}          # the house-style build running or last finished: {state, message}
        self.worker = None
        self.recover()

    @property
    def L(self):
        return lib.Library(self.ws)

    def recover(self):
        for m in self.L.references():
            if m.get("status") in lib.BUSY:
                self.L.set_status(m["id"], "failed", "interrupted: the Studio restarted while it was working. Analyse it again.")

    @property
    def busy(self):
        return bool(self.current) or not self.jobs.empty() or self.style_job.get("state") == "running"

    # ---------- reading ----------
    def state(self):
        L = self.L
        refs = []
        for m in L.references():
            a = L.analysis(m["id"]) or {}
            refs.append({**m, "screen": _screen_view(a.get("screen")), "script": _script_view(a.get("script")),
                         "sheets": [f"/motion-media/{m['id']}/frames/{p.name}" for p in L.sheets(m["id"])] if a.get("screen") else [],
                         "video_url": f"/motion-media/{m['id']}/{m['file']}" if m.get("file") else "",
                         "log": self.logs.get(m["id"], [])[-4:], "working": self.current == m["id"]})
        h = L.house()
        return {"references": refs, "rights": list(lib.RIGHTS), "modes": list(lib.MODES), "max_seconds": lib.MAX_SECONDS,
                "max_mb": lib.MAX_MB, "house": {"name": h.get("profile_name"), "version": h.get("version", 0), "source": h.get("source"),
                                                "brief": L.brief(), "script": L.script_brief(), "why": h.get("why", "")},
                "versions": L.versions(), "preferences": L.preferences(),
                "feedback": [f for f in L.feedback() if not f.get("approved")][-30:], "kinds": lib.FEEDBACK_KINDS,
                "tools": {"url": fetch_mod.available(), "whisper": _has_whisper()}, "busy": self.busy,
                "style_job": self.style_job}

    # ---------- adding ----------
    def upload(self, q, rfile, length):
        name = Path(str(q.get("name") or "video.mp4")).name
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXT:
            raise ValueError(f"{name}: not a video file ({', '.join(UPLOAD_EXT)})")
        if length <= 0:
            raise ValueError("the file is empty")
        if length > lib.MAX_MB * 1024 * 1024:
            raise ValueError(f"the file is larger than {lib.MAX_MB} MB")
        if q.get("rights") not in lib.RIGHTS:
            raise ValueError("say what rights you have to this video")
        tmp_dir = self.L.root / "incoming"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"{uuid.uuid4().hex}{ext}"
        try:
            left = length
            with tmp.open("wb") as f:
                while left > 0:
                    chunk = rfile.read(min(1 << 20, left))
                    if not chunk:
                        raise ValueError("the upload stopped before the end of the file")
                    f.write(chunk)
                    left -= len(chunk)
            meta = self.L.add(tmp, q["rights"], q.get("title", "")[:200], q.get("creator", "")[:120], q.get("notes", "")[:1000],
                              move=True)
        finally:
            if tmp.exists():
                tmp.unlink()
        return {"reference": meta}

    def add_url(self, body):
        modes = _modes(body.get("modes"))
        if not fetch_mod.available():
            raise ValueError("adding by URL needs yt-dlp on the computer running Postcrew (pip install yt-dlp); upload the file instead")
        meta = self.L.add_url(body.get("url"), body.get("rights"), str(body.get("title") or "")[:200], "",
                              str(body.get("notes") or "")[:1000])
        self._enqueue(meta["id"], modes, str(body.get("transcript") or ""))
        return {"reference": self.L.meta(meta["id"])}

    def analyze(self, rid, body):
        m = self.L.meta(rid)
        if m.get("status") in lib.BUSY:
            raise ValueError("it is already being analysed")
        self._enqueue(rid, _modes(body.get("modes")), str(body.get("transcript") or ""))
        return {"reference": self.L.meta(rid)}

    def _enqueue(self, rid, modes, transcript):
        self.L.update(rid, status="queued", modes=modes, status_reason="")
        self.logs[rid] = ["waiting for its turn"]
        self.jobs.put((rid, modes, transcript))
        if not self.worker or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._work, daemon=True, name="motion")
            self.worker.start()

    def _work(self):
        from ..motion.analyze import process
        while True:
            try:
                rid, modes, transcript = self.jobs.get(timeout=2)
            except queue.Empty:
                return
            self.current = rid
            log = lambda msg, rid=rid: self.logs.setdefault(rid, []).append(str(msg)[:300])
            try:
                process(self.ws, rid, modes, transcript, log=log)
            except Exception as e:   # recorded on the reference by process(); anything else is recorded here
                log(f"failed: {str(e)[:250]}")
                try:
                    if self.L.meta(rid).get("status") in lib.BUSY:
                        self.L.set_status(rid, "failed", str(e)[:400])
                except Exception:
                    traceback.print_exc()
            finally:
                self.current = None
                try:   # a job always ends in a state you can act on
                    if self.L.meta(rid).get("status") in lib.BUSY:
                        self.L.set_status(rid, "failed", "the analysis stopped without a result: analyse it again")
                except Exception:
                    pass

    # ---------- deciding ----------
    def action(self, rid, action):
        m = self.L.meta(rid)
        if m.get("status") in lib.BUSY:
            raise ValueError("wait until the analysis has finished")
        if action == "approve":
            if not m.get("analyzed"):
                raise ValueError("analyse it first")
            self.L.set_status(rid, "ready")
        elif action == "reject":
            self.L.set_status(rid, "rejected")
        elif action == "delete":
            self.L.delete(rid)
            self.logs.pop(rid, None)
        else:
            raise ValueError(f"unknown action {action}")
        return self.state()

    def style(self, body):
        what = body.get("action")
        if what == "build":
            if self.style_job.get("state") == "running":
                raise ValueError("the house style is already being built")
            self.style_job = {"state": "running", "message": "merging the approved references"}

            def go():
                from ..motion.analyze import build_house
                try:
                    s = build_house(self.ws, log=lambda m: self.style_job.update(message=str(m)[:300]))
                    self.style_job = {"state": "done", "message": f"house style v{s['version']} saved: {s['profile_name']}"}
                except Exception as e:
                    self.style_job = {"state": "failed", "message": str(e)[:300]}
            threading.Thread(target=go, daemon=True, name="motion-style").start()
        elif what == "use":
            self.L.use_version(int(body.get("version") or 0))
        elif what == "reset":
            self.L.reset_house()
        else:
            raise ValueError("action must be build, use or reset")
        return self.state()

    def feedback(self, body):
        what = body.get("action")
        if what == "approve":
            self.L.approve_feedback(str(body.get("id") or ""), str(body.get("rule") or ""))
        elif what == "forget":
            self.L.forget_preference(int(body.get("index") or 0))
        elif what == "add":
            self.L.add_feedback(str(body.get("video") or ""), body.get("rating") or None, body.get("kind") or "other",
                                str(body.get("comment") or ""), body.get("scene") or None)
        else:
            raise ValueError("action must be approve, forget or add")
        return self.state()


def _modes(value):
    modes = [m for m in (value if isinstance(value, list) else str(value or "").split(",")) if m in lib.MODES]
    if not modes:
        raise ValueError("choose what to analyse: the screens, the script or both")
    return modes


def _has_whisper():
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def _screen_view(a):
    if not a:
        return None
    p = a.get("profile") or {}
    return {"summary": a.get("summary", ""), "name": p.get("profile_name", ""), "scenes": len(a.get("scenes") or []),
            "composition": (p.get("visual_system") or {}).get("composition", ""),
            "motion": ", ".join((p.get("motion_language") or {}).get("preferred") or []),
            "rhythm": (p.get("storytelling") or {}).get("scene_rhythm", ""),
            "patterns": [f"{x['name']}: {x['recipe']}" for x in a.get("patterns") or []],
            "strengths": a.get("strengths") or [], "weaknesses": a.get("weaknesses") or [], "measured": a.get("measured") or {}}


def _script_view(a):
    if not a:
        return None
    p = a.get("profile") or {}
    return {"summary": a.get("summary", ""), "hook": p.get("hook_type", ""), "structure": p.get("structure", ""), "tone": p.get("tone", ""),
            "sentences": p.get("sentence_style", ""), "rules": p.get("rules") or [],
            "parts": [f"{x['part']} ({x['share']}%): {x['technique']}" for x in a.get("structure") or []],
            "patterns": [f"{x['name']}: {x['recipe']}" for x in a.get("patterns") or []],
            "strengths": a.get("strengths") or [], "weaknesses": a.get("weaknesses") or [], "measured": a.get("measured") or {}}
