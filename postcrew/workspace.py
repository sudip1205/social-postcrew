"""The workspace: one folder that holds a user's settings, secrets, queue, history and run logs.

    workspace/
      config.json      settings (safe to share; no secrets)
      secrets.json     LinkedIn app + token, Telegram (chmod 600, never commit)
      queue.json       posts that passed review and wait to be published
      history.json     everything published (used to avoid repeats)
      runs/<run_id>/   one folder per crew run: events.jsonl, status.json, artifacts, media
      state/           scheduler + credential monitor state, notifications

Location: $POSTCREW_HOME, else ./workspace in a source checkout, or ~/.postcrew when installed with pip.
"""
import copy
import json
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path

from .defaults import AGENT_IDS, DEFAULT_CONFIG, SECRET_KEYS
from .platforms import FREQUENCIES, LINKEDIN, PLATFORM_IDS, view

CODE_ROOT = Path(__file__).resolve().parent.parent


def default_root(name="workspace"):
    """./workspace in a source checkout; ~/.postcrew when installed with pip (never inside site-packages).
    name: "workspace-demo" gives the demo's folder (./workspace-demo or ~/.postcrew-demo)."""
    if (CODE_ROOT / "pyproject.toml").exists():
        return CODE_ROOT / name
    return Path.home() / (".postcrew" + name[len("workspace"):])
_lock = threading.RLock()
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
APPROVAL_MODES = ["auto_with_veto", "manual", "immediate"]
MEDIA_KINDS = ["auto", "poster", "video", "sysflow", "animation", "none"]
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


VIDEO_FORMATS = ["short", "long"]
_SECONDS_HINT = "15-180 for a short, 60-1800 for a long video"


def _seconds_ok(fmt, v):
    return isinstance(v, int) and not isinstance(v, bool) and ((15 <= v <= 180) if fmt == "short" else (60 <= v <= 1800))


RENDERERS = ("ffmpeg", "explainer", "explainroo", "blackboard", "mcp")


def _validate_video(v, pre):
    errs = []
    if v.get("format") not in VIDEO_FORMATS:
        errs.append(f"{pre}video.format must be one of {VIDEO_FORMATS}")
    elif not _seconds_ok(v.get("format"), v.get("target_seconds")):
        errs.append(f"{pre}video.target_seconds must be {_SECONDS_HINT}")
    if v.get("pace", "normal") not in ("slow", "normal"):
        errs.append(f"{pre}video.pace must be slow or normal")
    if v.get("renderer") not in RENDERERS:
        errs.append(f"{pre}video.renderer must be one of {RENDERERS}")
    voice = v.get("voice") or {}
    if voice.get("provider", "elevenlabs") != "elevenlabs":
        errs.append(f"{pre}video.voice.provider must be elevenlabs")
    if not (isinstance(voice.get("speed", 1.0), (int, float)) and 0.7 <= voice.get("speed", 1.0) <= 1.2):
        errs.append(f"{pre}video.voice.speed must be between 0.7 and 1.2")
    mcp = v.get("mcp") or {}
    if v.get("renderer") == "mcp":
        if not str(mcp.get("command", "")).strip() or not str(mcp.get("tool", "")).strip():
            errs.append(f"{pre}video.mcp: name the command and the tool of the animation MCP server")
    if not isinstance(mcp.get("args", []), list) or not all(isinstance(a, str) for a in mcp.get("args", [])):
        errs.append(f"{pre}video.mcp.args must be a list of strings")
    if not (isinstance(mcp.get("timeout_s", 600), int) and 30 <= mcp.get("timeout_s", 600) <= 3600):
        errs.append(f"{pre}video.mcp.timeout_s must be 30-3600 seconds")
    return errs


def validate_platform(cfg, pre="", primary=True):
    """Problems in one platform's schedule, topics, planning and publishing. `cfg` is that platform's view of the config
    (see platforms.view); `pre` prefixes the setting names in messages; `primary` = LinkedIn's own settings."""
    errs = []
    s = cfg.get("schedule", {})
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(s["timezone"])
    except Exception:
        errs.append(f"{pre}schedule.timezone {s.get('timezone')!r} is not a valid IANA time zone "
                    f"(example: America/Chicago)")
    for key in ("generate_time", "post_time") + (("credential_check_time",) if primary else ()):
        if not TIME_RE.match(str(s.get(key, ""))):
            errs.append(f"{pre}schedule.{key} must be HH:MM (24h)")
    if not isinstance(s.get("lead_days"), int) or not 0 <= s["lead_days"] <= 7:
        errs.append(f"{pre}schedule.lead_days must be a whole number 0-7")
    cats = cfg.get("categories", {})
    days = s.get("days", {})
    for d in WEEKDAYS:
        v = days.get(d, "")
        if v and v not in cats:
            errs.append(f"{pre}schedule.days.{d} uses unknown category {v!r}")
    freq = s.get("frequency", "weekly")
    if freq not in FREQUENCIES:
        errs.append(f"{pre}schedule.frequency must be one of {FREQUENCIES}")
    if freq == "weekly" and not any(days.get(d) for d in WEEKDAYS):
        errs.append(f"{pre}schedule.days: " + ("pick a topic for at least one day" if cfg.get("categories")
                    else "add a topic under Topics first, then pick it for a day"))
    if freq == "every_n_days":
        if not (isinstance(s.get("every_n"), int) and 1 <= s["every_n"] <= 60):
            errs.append(f"{pre}schedule.every_n must be a whole number 1-60")
        try:
            date.fromisoformat(str(s.get("start_date", "")))
        except ValueError:
            errs.append(f"{pre}schedule.start_date must be a date, YYYY-MM-DD")
        rot = s.get("rotation") or []
        if any(c not in cats for c in rot):
            errs.append(f"{pre}schedule.rotation uses an unknown category")
        if not (rot or any(days.get(d) for d in WEEKDAYS)):
            errs.append(f"{pre}schedule.rotation: list the categories to cycle through")
    for t in (s.get("day_times") or {}).items():
        if t[0] not in WEEKDAYS or not TIME_RE.match(str(t[1])):
            errs.append(f"{pre}schedule.day_times: use a weekday (mon-sun) and HH:MM, not {t[0]!r}: {t[1]!r}")
    ds = s.get("dates") or []
    if not isinstance(ds, list) or len(ds) > 400:
        errs.append(f"{pre}schedule.dates must be a list of at most 400 dates")
    else:
        for e in ds:
            try:
                date.fromisoformat(str(e.get("date", "")))
            except (ValueError, AttributeError):
                errs.append(f"{pre}schedule.dates: {e!r} needs a date, YYYY-MM-DD")
                continue
            if e.get("category") and e["category"] not in cats:
                errs.append(f"{pre}schedule.dates {e['date']} uses unknown category {e['category']!r}")
            if e.get("time") and not TIME_RE.match(str(e["time"])):
                errs.append(f"{pre}schedule.dates {e['date']}: time must be HH:MM (24h)")
        if freq == "dates" and not ds:
            errs.append(f"{pre}schedule.dates: add at least one date")
    for cid, c in cats.items():
        where = f"{pre}categories.{cid}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", cid):
            errs.append(f"{where}: id must be lowercase letters, digits and dashes")
        if not str(c.get("label", "")).strip():
            errs.append(f"{where}.label is required")
        if c.get("media") not in MEDIA_KINDS:
            errs.append(f"{where}.media must be one of {MEDIA_KINDS}")
        if any(x not in POSTER_LAYOUTS for x in c.get("layouts") or []):
            errs.append(f"{where}.layouts must be a subset of {POSTER_LAYOUTS}")
        if c.get("research", "optional") not in RESEARCH_MODES:
            errs.append(f"{where}.research must be one of {RESEARCH_MODES}")
        if not str(c.get("brief", "")).strip():
            errs.append(f"{where}.brief: describe what this kind of post should contain")
        if c.get("renderer") not in (None, "ffmpeg", "explainer", "blackboard"):
            errs.append(f"{where}.renderer must be ffmpeg, explainer or blackboard")
        if "format" in c and c["format"] not in VIDEO_FORMATS:
            errs.append(f"{where}.format must be one of {VIDEO_FORMATS}")
        elif "target_seconds" in c and not _seconds_ok(c.get("format") or (cfg.get("video") or {}).get("format"), c["target_seconds"]):
            errs.append(f"{where}.target_seconds must be {_SECONDS_HINT}")
        ideas = c.get("ideas", [])
        if not (isinstance(ideas, list) and len(ideas) <= 60 and all(
                isinstance(i, str) and 3 <= len(i) <= 600 and len(i.split("::")[0].strip()) <= 150 for i in ideas)):
            errs.append(f"{where}.ideas: up to 60 topic ideas, each 3-600 characters ('Title :: context'; the title up to 150)")
    pn = cfg.get("planning", {})
    if pn.get("weekday") not in WEEKDAYS:
        errs.append(f"{pre}planning.weekday must be one of {WEEKDAYS}")
    if not TIME_RE.match(str(pn.get("time", ""))):
        errs.append(f"{pre}planning.time must be HH:MM (24h)")
    if len(str(pn.get("focus", ""))) > 600:
        errs.append(f"{pre}planning.focus: keep it under 600 characters")
    p = cfg.get("publishing", {})
    if p.get("approval") not in APPROVAL_MODES:
        errs.append(f"{pre}publishing.approval must be one of {APPROVAL_MODES}")
    if "visibility" in p and p["visibility"] not in ("public", "unlisted", "private"):
        errs.append(f"{pre}publishing.visibility must be public, unlisted or private")
    if "video" in cfg:
        errs += _validate_video(cfg["video"], pre)
    if primary and not re.fullmatch(r"\d{6}", str(p.get("linkedin_api_version", ""))):
        errs.append("publishing.linkedin_api_version must be YYYYMM, e.g. 202601")
    return errs


def validate_config(cfg):
    """Return a list of human-readable problems. Empty list = valid."""
    errs = validate_platform(cfg)
    for pid, own in (cfg.get("platforms") or {}).items():
        if pid == LINKEDIN:
            continue
        if pid not in PLATFORM_IDS:
            errs.append(f"platforms.{pid}: unknown platform (known: {PLATFORM_IDS})")
        elif own.get("enabled"):   # a platform that is switched off is not checked until you turn it on
            errs += validate_platform(view(cfg, pid), pre=f"platforms.{pid}.", primary=False)
    tm = cfg.get("team", {})
    for k, lo, hi in (("research", 1, 4), ("writer", 1, 4), ("fire_window", 3, 20), ("polish_rounds", 0, 3)):
        if not (isinstance(tm.get(k), int) and lo <= tm[k] <= hi):
            errs.append(f"team.{k} must be a whole number {lo}-{hi}")
    if not (isinstance(tm.get("fire_min_success"), (int, float)) and 0 <= tm["fire_min_success"] <= 1):
        errs.append("team.fire_min_success must be between 0 and 1")
    if not re.fullmatch(r"https?://[^\s]+", str(cfg.get("notifications", {}).get("studio_url", "http://localhost"))):
        errs.append("notifications.studio_url must start with http:// or https://")
    llm = cfg.get("llm", {})
    backends = ["claude-code", "anthropic", "openai", "openai-compatible", "demo"]
    if llm.get("backend") not in backends:
        errs.append(f"llm.backend must be one of {backends}")
    api = llm.get("api", {})
    url = str(api.get("base_url") or "")
    if url and not re.fullmatch(r"https?://[^\s]+", url):
        errs.append("llm.api.base_url must start with http:// or https://")
    if llm.get("backend") == "openai-compatible":
        if not url:
            errs.append("llm.api.base_url: set the server's address, e.g. http://localhost:11434/v1 for Ollama")
        tiers = api.get("models", {}).get("openai-compatible") or {}
        if not all(str(tiers.get(t) or "").strip() for t in ("opus", "sonnet", "haiku")):
            errs.append("llm.api.models.openai-compatible: name the model to use for each of opus, sonnet and haiku "
                        "(they may be the same)")
    mot = api.get("max_output_tokens", 16000)
    if not (isinstance(mot, int) and 1000 <= mot <= 200000):
        errs.append("llm.api.max_output_tokens must be a whole number 1000-200000")
    for aid, a in {"defaults": llm.get("defaults", {}), **llm.get("agents", {})}.items():
        if aid != "defaults" and aid not in AGENT_IDS:
            errs.append(f"llm.agents.{aid}: unknown agent")
        if "model" in a and not re.fullmatch(r"[A-Za-z0-9._:/@\-\[\]]{2,120}", str(a["model"])):
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


def normalize_categories(cfg):
    """Topics no longer carry a poster style, poster label, length limits or a research switch: the picture and its
    label come from the day's context, the length is whatever the post needs (LinkedIn's hard limit is 3000), and
    research always runs. Older configs are read through this, so nothing breaks."""
    for own in (p for p in (cfg.get("platforms") or {}).values() if p.get("categories")):
        normalize_categories(own)
    for cid, c in (cfg.get("categories") or {}).items():
        c["min_chars"], c["max_chars"] = 50, 3000
        if c.get("media") == "poster":
            c["media"] = "auto"
        if c.get("research") == "off" and c.get("media") != "animation" and cid != "week-recap":
            c["research"] = "optional"
        c.setdefault("context", "")
        c.setdefault("plan_context", "")
    return cfg


class Workspace:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("POSTCREW_HOME") or default_root()).resolve()
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
        return normalize_categories(deep_merge(DEFAULT_CONFIG, read_json(self.root / "config.json", {})))

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
        visible = {"linkedin_client_id", "linkedin_token_expires_at", "linkedin_name", "gmail_address", "email_to",
                   "telegram_chat_id", "youtube_client_id", "youtube_channel_title"}
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

    def remove_history(self, match):
        """Remove the first entry for which match(entry) is true. Returns it, or None."""
        with _lock:
            h = self.history()
            i = next((i for i, p in enumerate(h) if match(p)), None)
            if i is None:
                return None
            gone = h.pop(i)
            write_json(self.root / "history.json", {"posts": h})
            return gone

    def recent_posts(self, n=30, platform=None):
        """Published + queued posts, oldest first: what the crew must not repeat. platform: only that app's."""
        items = [dict(p, status="published") for p in self.history()] + [p for p in self.queue()
                                                                           if p.get("status") != "vetoed"]
        if platform:
            items = [p for p in items if (p.get("platform") or LINKEDIN) == platform]
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
