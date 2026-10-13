"""Crew memory.

Working memory (one run) lives in runs/<run_id>/memory.json and is written while the run is going: every time an
agent's work is sent back, the reasons and the Supervisor's instructions are kept. An agent that is sent back again
sees everything that went wrong with its work earlier in the run, not only the latest round, so a revision does not
bring back a mistake that was already fixed.

Long-term memory (across runs) lives in state/memory.json. When a run's post passes the Editor, every problem fixed in
that run is kept with the instructions that fixed it, and the next run's agents start with the most recent ones for their step.
"""
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .workspace import write_json

KEEP_PER_STEP = 10
RECALL = 3
SCORE_LINE = re.compile(r"(overall score|scored) \d+ \(needs \d+\)")  # says nothing about what to change


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunMemory:
    """kind: sent_back (why + instructions for the step that must redo its work) or passed."""

    def __init__(self, run_dir):
        self.path = Path(run_dir) / "memory.json"
        self._lock = threading.Lock()
        self.entries = json.loads(self.path.read_text()) if self.path.exists() else []

    def add(self, step, kind, by="", why=(), instructions=(), attempt=None):
        with self._lock:
            self.entries.append({"at": _now(), "step": step, "kind": kind, "by": by, "attempt": attempt,
                                 "why": list(why)[:12], "instructions": list(instructions)[:6]})
            write_json(self.path, self.entries)

    def reasons(self, step):
        """Every reason this step's work was sent back so far in this run, oldest first, without repeats."""
        seen = []
        for e in self.entries:
            if e["step"] == step and e["kind"] == "sent_back":
                seen += [w for w in e["why"] if w not in seen]
        return seen

    def fixes(self):
        """(step, problem, instructions) for every sending-back that the step later got past."""
        out = []
        for i, e in enumerate(self.entries):
            if e["kind"] == "sent_back" and e["why"] and any(
                    x["step"] == e["step"] and x["kind"] == "passed" for x in self.entries[i + 1:]):
                specific = [w for w in e["why"] if not SCORE_LINE.search(w)] or e["why"]
                out.append((e["step"], specific[0], e["instructions"] or specific[1:3]))
        return out


def load(ws):
    return ws.state("memory", {})


def remember(ws, mem, run_id):
    """Keep this run's fixed problems for future runs. Returns how many were added."""
    data, n = load(ws), 0
    for step, problem, instructions in mem.fixes():
        rows = data.setdefault(step, [])
        key = problem[:80]
        rows[:] = [r for r in rows if r["problem"][:80] != key]
        rows.append({"problem": problem[:300], "fix": [x[:240] for x in instructions[:3]], "run": run_id, "at": _now()})
        rows[:] = rows[-KEEP_PER_STEP:]
        n += 1
    if n:
        ws.save_state("memory", data)
    return n


def recall(ws, step, n=RECALL):
    return load(ws).get(step, [])[-n:]


def forget(ws, step, index):
    data = load(ws)
    rows = data.get(step, [])
    if not 0 <= index < len(rows):
        raise KeyError(index)
    rows.pop(index)
    ws.save_state("memory", data)
    return data
