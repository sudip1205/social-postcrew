"""Platforms (apps) Postcrew posts to, and each one's own schedule.

LinkedIn's settings live at the top of config.json, as they always have. Every other platform keeps its own
`schedule`, `planning`, `categories` and `publishing` under `platforms.<id>`. `view(cfg, id)` returns the config as that
platform sees it, so an agent that reads `cfg["schedule"]` or `cfg["categories"]` works for any platform unchanged.

How often a platform posts (schedule.frequency):
  weekly         the weekdays set in schedule.days, each with its own category (the original behaviour)
  every_n_days   every `every_n` days from `start_date`, cycling through `rotation` (or the categories used in `days`)
  dates          only the dates listed in schedule.dates
Whatever the frequency, schedule.dates adds one-off days (each with an optional category and time), and
schedule.day_times gives a weekday its own post time.
"""
from datetime import date, datetime

LINKEDIN = "linkedin"
PLATFORM_IDS = [LINKEDIN, "youtube"]
SECTIONS = ("schedule", "planning", "categories", "publishing", "video")
FREQUENCIES = ["weekly", "every_n_days", "dates"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LABELS = {LINKEDIN: "LinkedIn", "youtube": "YouTube"}


def label(platform):
    return LABELS.get(platform, platform.title())


def is_enabled(cfg, platform):
    if platform == LINKEDIN:
        return cfg.get("platforms", {}).get(LINKEDIN, {}).get("enabled", True)
    return bool(cfg.get("platforms", {}).get(platform, {}).get("enabled"))


def enabled(cfg):
    """Ids of the platforms switched on, LinkedIn first."""
    return [p for p in PLATFORM_IDS if is_enabled(cfg, p)]


def view(cfg, platform=LINKEDIN):
    """The config as one platform sees it (LinkedIn's is the config itself)."""
    if not platform or platform == LINKEDIN:
        return cfg
    own = cfg.get("platforms", {}).get(platform)
    if own is None:
        raise KeyError(f"unknown platform {platform!r}")
    return {**cfg, **{k: own[k] for k in SECTIONS if k in own}, "platform": platform, "platform_cfg": own}


def platform_of(item):
    """The platform of a queue, history or plan entry (entries from before platforms existed are LinkedIn's)."""
    return (item or {}).get("platform") or LINKEDIN


def state_name(base, platform=LINKEDIN):
    """Name of a state file: LinkedIn keeps the original names, other platforms get a suffix."""
    return base if not platform or platform == LINKEDIN else f"{base}-{platform}"


# ---------- the schedule ----------
def _entry(sched, iso):
    return next((e for e in sched.get("dates") or [] if isinstance(e, dict) and e.get("date") == iso), None)


def _cycle(sched):
    rot = [c for c in sched.get("rotation") or [] if c]
    if rot:
        return rot
    seen = []
    for d in WEEKDAYS:
        c = (sched.get("days") or {}).get(d)
        if c and c not in seen:
            seen.append(c)
    return seen


def slot(sched, day):
    """What the schedule says for `day`: {"category", "time"} or None when nothing is due that day."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    wd = WEEKDAYS[day.weekday()]
    freq = sched.get("frequency") or "weekly"
    category = None
    if freq == "weekly":
        category = (sched.get("days") or {}).get(wd) or None
    elif freq == "every_n_days":
        try:
            gap = (day - date.fromisoformat(sched.get("start_date") or "")).days
        except ValueError:
            gap = -1
        n = max(1, int(sched.get("every_n") or 1))
        cycle = _cycle(sched)
        if gap >= 0 and gap % n == 0 and cycle:
            category = cycle[(gap // n) % len(cycle)]
    one = _entry(sched, day.isoformat())
    if one:
        category = one.get("category") or category or (sched.get("days") or {}).get(wd) or next(iter(_cycle(sched)), None)
    if not category:
        return None
    return {"category": category, "time": (one or {}).get("time") or (sched.get("day_times") or {}).get(wd)
            or sched["post_time"]}


def category_for(sched, day):
    s = slot(sched, day)
    return s["category"] if s else None


def post_time_for(sched, day):
    s = slot(sched, day)
    return s["time"] if s else sched["post_time"]


def upcoming(sched, today, n=14):
    """The next `n` days (from `today`) that have a post due: [(date, slot)]."""
    from datetime import timedelta
    out = []
    for i in range(n):
        d = today + timedelta(days=i)
        s = slot(sched, d)
        if s:
            out.append((d, s))
    return out


def parse_day(value):
    return value if isinstance(value, date) else datetime.strptime(value, "%Y-%m-%d").date()


# ---------- video ----------
WORDS_PER_SECOND = 2.5   # how fast a voice-over is read: the script's word budget and every scene's timing
PACE_WPS = {"normal": 2.5, "slow": 2.0}   # a teacher's pace leaves room for pauses and for the picture to build up
SHORT_MAX_S = 180        # YouTube allows Shorts of up to three minutes


def renderer_for(cfg, category=None):
    """How a video is drawn: the topic's own renderer, else the app's (ffmpeg slides, blackboard or an animation MCP server)."""
    return ((cfg.get("categories") or {}).get(category) or {}).get("renderer") or (cfg.get("video") or {}).get("renderer")


def video_spec(cfg, category=None, entry=None, options=None):
    """The kind of video to make: {"format", "target_seconds", "max_words"}. Later wins: the platform's default video
    settings, the topic's own, the plan day's, then a one-off override from the run."""
    base = (cfg.get("video") or {})
    spec = {"format": base.get("format", "short"), "target_seconds": base.get("target_seconds", 45)}
    for src in (category or {}, entry or {}, options or {}):
        if src.get("format"):
            if src["format"] != spec["format"] and not src.get("target_seconds"):
                spec["target_seconds"] = 45 if src["format"] == "short" else 480   # a new kind without a length of its own
            spec["format"] = src["format"]
        if src.get("target_seconds"):
            spec["target_seconds"] = int(src["target_seconds"])
    if spec["format"] == "short":
        spec["target_seconds"] = max(15, min(SHORT_MAX_S, spec["target_seconds"]))
    else:
        spec["target_seconds"] = max(60, min(1800, spec["target_seconds"]))
    spec["pace"] = base.get("pace") if base.get("pace") in PACE_WPS else "normal"
    spec["wps"] = PACE_WPS[spec["pace"]]
    spec["max_words"] = int(spec["target_seconds"] * spec["wps"])
    spec["renderer"] = renderer_for(cfg, None) if not category else (category.get("renderer") or renderer_for(cfg, None))
    return spec
