"""Run log: every step of a crew run is recorded so it can be replayed, audited and visualized.

runs/<run_id>/events.jsonl  one JSON event per line (append-only, the full story)
runs/<run_id>/status.json   current snapshot: each step's state, attempts, cost (what the Studio graph draws)
runs/<run_id>/<step>.json   each agent's accepted output (artifact)
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .workspace import write_json

# The order steps appear in the workflow graph.
STEPS = ["credentials", "topic", "research", "writer", "media", "editor", "formatter", "publisher"]
STATES = ["pending", "running", "passed", "failed", "retrying", "skipped", "blocked", "waiting"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLog:
    def __init__(self, run_dir, run_id=None, meta=None, echo=False):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self._lock = threading.Lock()
        existing = self.dir / "status.json"
        if existing.exists():
            self.status = json.loads(existing.read_text())
        else:
            self.status = {"run_id": run_id or self.dir.name, "state": "running", "started_at": now_iso(),
                           "finished_at": None, "result": None, "cost_usd": 0.0, "meta": meta or {},
                           "steps": {s: {"state": "pending", "attempts": 0, "started_at": None, "finished_at": None,
                                         "summary": "", "errors": [], "cost_usd": 0.0} for s in STEPS},
                           "interventions": 0}
            self._flush()

    # ---------- writing ----------
    def _flush(self):
        write_json(self.dir / "status.json", self.status)

    def event(self, step, kind, message, data=None, level="info"):
        ev = {"ts": now_iso(), "t": round(time.time(), 3), "step": step, "kind": kind, "level": level,
              "message": message}
        if data is not None:
            ev["data"] = data
        with self._lock:
            with open(self.dir / "events.jsonl", "a") as f:
                f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
        if self.echo:
            print(f"[{ev['ts'][11:19]}] {step:<11} {kind:<12} {message}", flush=True)
        return ev

    def step(self, step, state=None, **fields):
        with self._lock:
            s = self.status["steps"].setdefault(step, {"state": "pending", "attempts": 0, "errors": [],
                                                       "cost_usd": 0.0, "summary": ""})
            if state:
                assert state in STATES, state
                s["state"] = state
                if state == "running" and not s.get("started_at"):
                    s["started_at"] = now_iso()
                if state in ("passed", "failed", "skipped", "blocked"):
                    s["finished_at"] = now_iso()
            s.update(fields)
            self._flush()

    def add_cost(self, step, usd):
        if not usd:
            return
        with self._lock:
            self.status["cost_usd"] = round(self.status["cost_usd"] + usd, 6)
            st = self.status["steps"].setdefault(step, {})
            st["cost_usd"] = round(st.get("cost_usd", 0.0) + usd, 6)
            self._flush()

    def artifact(self, name, data):
        write_json(self.dir / f"{name}.json", data)

    def finish(self, state, result):
        with self._lock:
            self.status.update(state=state, result=result, finished_at=now_iso())
            self._flush()
        self.event("run", "finished", result, level="info" if state == "succeeded" else "error")

    def note_intervention(self):
        with self._lock:
            self.status["interventions"] += 1
            self._flush()

    @property
    def cost(self):
        return self.status["cost_usd"]


def read_events(run_dir, after=0.0):
    p = Path(run_dir) / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("t", 0) > after:
            out.append(ev)
    return out
