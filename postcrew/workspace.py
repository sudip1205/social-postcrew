"""The workspace: one folder that holds a user's settings, secrets, queue, history and run logs.

    workspace/
      config.json      settings (safe to share; no secrets)
      secrets.json     LinkedIn app + token, Telegram (chmod 600, never commit)
      queue.json       posts that passed review and wait to be published
      history.json     everything published (used to avoid repeats)
      runs/<run_id>/   one folder per crew run: events.jsonl, status.json, artifacts, media
      state/           scheduler + credential monitor state, notifications

Location: $POSTCREW_HOME, else ./workspace next to the code.
"""
import copy
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from .defaults import AGENT_IDS, DEFAULT_CONFIG, SECRET_KEYS

CODE_ROOT = Path(__file__).resolve().parent.parent
_lock = threading.RLock()
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
APPROVAL_MODES = ["auto_with_veto", "manual", "immediate"]
MEDIA_KINDS = ["poster", "animation", "none"]
POSTER_LAYOUTS = ["points", "steps", "code", "flow"]
RESEARCH_MODES = ["required", "optional", "off"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)


def write_json(path, data, private=False):
    """Atomic write. `private` files are created owner-read/write only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with _lock:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        if private:
            os.chmod(path, 0o600)


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def validate_config(cfg):
    """Return a list of human-readable problems. Empty list = valid."""
    errs = []
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(cfg["schedule"]["timezone"])
    except Exception:
        errs.append(f"schedule.timezone {cfg.get('schedule', {}).get('timezone')!r} is not a valid IANA time zone "
                    f"(example: America/Chicago)")
    s = cfg.get("schedule", {})
    for key in ("generate_time", "post_time", "credential_check_time"):
        if not TIME_RE.match(str(s.get(key, ""))):
            errs.append(f"schedule.{key} must be HH:MM (24h)")
    if not isinstance(s.get("lead_days"), int) or not 0 <= s["lead_days"] <= 7:
        errs.append("schedule.lead_days must be a whole number 0-7")
    cats = cfg.get("categories", {})
    days = s.get("days", {})
    for d in WEEKDAYS:
        v = days.get(d, "")
        if v and v not in cats:
            errs.append(f"schedule.days.{d} uses unknown category {v!r}")
    if not any(days.get(d) for d in WEEKDAYS):
        errs.append("schedule.days: pick a category for at least one day")
    for cid, c in cats.items():
        where = f"categories.{cid}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", cid):
            errs.append(f"{where}: id must be lowercase letters, digits and dashes")
        if not str(c.get("label", "")).strip():
            errs.append(f"{where}.label is required")
        if c.get("media") not in MEDIA_KINDS:
            errs.append(f"{where}.media must be one of {MEDIA_KINDS}")
        if c.get("media") == "poster":
            lay = c.get("layouts") or []
            if not lay or any(x not in POSTER_LAYOUTS for x in lay):
                errs.append(f"{where}.layouts must be a non-empty subset of {POSTER_LAYOUTS}")
        if c.get("research", "optional") not in RESEARCH_MODES:
            errs.append(f"{where}.research must be one of {RESEARCH_MODES}")
        lo, hi = c.get("min_chars"), c.get("max_chars")
        if not (isinstance(lo, int) and isinstance(hi, int) and 50 <= lo < hi <= 3000):
            errs.append(f"{where}: need 50 <= min_chars < max_chars <= 3000 (LinkedIn's limit)")
        if not str(c.get("brief", "")).strip():
            errs.append(f"{where}.brief: describe what this kind of post should contain")
    p = cfg.get("publishing", {})
    if p.get("approval") not in APPROVAL_MODES:
        errs.append(f"publishing.approval must be one of {APPROVAL_MODES}")
    if not re.fullmatch(r"\d{6}", str(p.get("linkedin_api_version", ""))):
        errs.append("publishing.linkedin_api_version must be YYYYMM, e.g. 202601")
    llm = cfg.get("llm", {})
    if llm.get("backend") != "claude-code":
        errs.append("llm.backend: only 'claude-code' is supported in this version")
    for aid, a in {"defaults": llm.get("defaults", {}), **llm.get("agents", {})}.items():
        if aid != "defaults" and aid not in AGENT_IDS:
            errs.append(f"llm.agents.{aid}: unknown agent")
        if "model" in a and not re.fullmatch(r"[A-Za-z0-9._\-\[\]]{2,80}", str(a["model"])):
            errs.append(f"llm.agents.{aid}.model looks wrong (use sonnet, opus, haiku or a full model id)")
        if "timeout_s" in a and not (isinstance(a["timeout_s"], int) and 30 <= a["timeout_s"] <= 3600):
            errs.append(f"llm.agents.{aid}.timeout_s must be 30-3600 seconds")
        if "max_budget_usd" in a and not (isinstance(a["max_budget_usd"], (int, float)) and 0 < a["max_budget_usd"] <= 20):
            errs.append(f"llm.agents.{aid}.max_budget_usd must be between 0 and 20")
    pl = cfg.get("pipeline", {})
    for k, lo, hi in (("max_attempts_per_step", 1, 10), ("max_total_attempts", 1, 40), ("review_runs", 1, 5),
                      ("min_overall", 0, 100), ("min_subscore", 0, 100)):
        if not (isinstance(pl.get(k), int) and lo <= pl[k] <= hi):
            errs.append(f"pipeline.{k} must be a whole number {lo}-{hi}")
    if not (isinstance(pl.get("max_run_budget_usd"), (int, float)) and 0 < pl["max_run_budget_usd"] <= 100):
        errs.append("pipeline.max_run_budget_usd must be between 0 and 100")
    h = cfg.get("profile", {}).get("handle", "")
    if len(h) > 60:
        errs.append("profile.handle: keep it under 60 characters (it is printed on posters)")
    return errs


class Workspace:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("POSTCREW_HOME") or CODE_ROOT / "workspace").resolve()
        self.runs_dir = self.root / "runs"
        self.state_dir = self.root / "state"

    # ---------- setup ----------
    def init(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / "config.json").exists():
            write_json(self.root / "config.json", DEFAULT_CONFIG)
        if not (self.root / "secrets.json").exists():
            write_json(self.root / "secrets.json", {}, private=True)
        for name, empty in (("queue.json", {"posts": []}), ("history.json", {"posts": []})):
            if not (self.root / name).exists():
                write_json(self.root / name, empty)
        self.runs_dir.mkdir(exist_ok=True)
        self.state_dir.mkdir(exist_ok=True)
        return self

    # ---------- config ----------
    def config(self):
        return deep_merge(DEFAULT_CONFIG, read_json(self.root / "config.json", {}))

    def save_config(self, cfg):
        errs = validate_config(cfg)
        if errs:
            raise ValueError("; ".join(errs))
        write_json(self.root / "config.json", cfg)

    # ---------- secrets ----------
    def secrets(self):
        return read_json(self.root / "secrets.json", {}) or {}

    def update_secrets(self, **values):
        with _lock:
            s = self.secrets()
            for k, v in values.items():
                if k not in SECRET_KEYS:
                    raise ValueError(f"unknown secret {k}")
                if v is None or v == "":
                    s.pop(k, None)
                else:
                    s[k] = v
            write_json(self.root / "secrets.json", s, private=True)
        return s

    def masked_secrets(self):
        """What the browser may see: whether each secret is set, never its value (except harmless ids)."""
        s = self.secrets()
        visible = {"linkedin_client_id", "linkedin_token_expires_at", "linkedin_name", "telegram_chat_id"}
        return {k: (s[k] if k in visible else bool(s[k])) if k in s else None for k in SECRET_KEYS}

    # ---------- queue & history ----------
    def queue(self):
        return read_json(self.root / "queue.json", {"posts": []})["posts"]

    def save_queue(self, posts):
        write_json(self.root / "queue.json", {"posts": posts})

    def history(self):
        return read_json(self.root / "history.json", {"posts": []})["posts"]

    def add_history(self, post):
        with _lock:
            h = self.history()
            h.append(post)
            write_json(self.root / "history.json", {"posts": h})

    def recent_posts(self, n=30):
        """Published + queued posts, oldest first: what the crew must not repeat."""
        items = [dict(p, status="published") for p in self.history()] + [p for p in self.queue()
                                                                           if p.get("status") != "vetoed"]
        return sorted(items, key=lambda p: p.get("date", ""))[-n:]

    # ---------- state ----------
    def state(self, name, default=None):
        return read_json(self.state_dir / f"{name}.json", default if default is not None else {})

    def save_state(self, name, data):
        write_json(self.state_dir / f"{name}.json", data)

    def paused(self):
        return (self.root / "PAUSE").exists()

    def new_run_id(self, date_str):
        stamp = datetime.now().strftime("%H%M%S")
        return f"{date_str}-{stamp}"
