"""Postcrew Studio: local web UI + JSON API. Standard library only.

Binds to 127.0.0.1. Secrets are write-only from the browser (it only learns whether each one is set).
Every state-changing request must carry the X-Postcrew header and a localhost Origin/Host, which blocks
other web sites from driving the Studio through your browser (CSRF / DNS rebinding).

On another interface (`serve --lan` / `--host`) the Studio can be opened from other computers, and then every request must carry
the access token (a cookie set by the link `http://<address>:<port>/?token=...` the server prints, or `Authorization: Bearer`).
A page on another site cannot read that cookie, and a write must come from the same site as the page that sent it.
"""
import json
import mimetypes
import re
import secrets as pysecrets
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__, assets as assets_mod, crew, linkedin, notify as notify_mod, platforms, voice as voice_mod, youtube
from .. import monthly
from ..agents import team as team_mod
from .. import memory as memory_mod
from ..agents.credentials import run_check
from ..agents.publisher import publish_post, scheduled_at
from ..agents.supervisor import CREW, Supervisor
from ..agents.blackboard import BlackboardAgent, ExplainerAgent
from ..agents.explainroo import ExplainrooAgent
from ..agents.frames import HyperFramesAgent, RemotionAgent, RemotionFramesAgent
from ..agents.hooks import HooksAgent
from ..agents.video_review import VideoReviewAgent
from ..agents.voice import VoiceAgent
from ..llm import LLMError, agent_settings, make_backend
from ..runlog import STEPS, read_events
from ..workspace import validate_config

STATIC = Path(__file__).resolve().parent / "static"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class Studio:
    def __init__(self, ws, port=8765, token=None):
        self.ws, self.port = ws, port
        self.token = token   # set when the Studio is reachable from other computers: every request must carry it
        self.oauth_states = {}

    @property
    def redirect_uri(self):
        return f"http://localhost:{self.port}/oauth/callback"

    @property
    def youtube_redirect_uri(self):
        return f"http://localhost:{self.port}/oauth/youtube/callback"

    # ---------- api ----------
    def _view(self, platform=None):
        """(platform id, config as that app sees it). Raises ValueError for an app that does not exist."""
        platform = platform or platforms.LINKEDIN
        try:
            return platform, platforms.view(self.ws.config(), platform)
        except KeyError:
            raise ValueError(f"unknown app {platform!r}")

    def overview(self, platform=None):
        platform, cfg = self._view(platform)
        full = self.ws.config()
        q = [p for p in self.ws.queue() if platforms.platform_of(p) == platform]
        now = crew.local_now(cfg)
        target = crew.target_date(cfg, now)
        return {"version": __version__, "workspace": str(self.ws.root), "running": crew.is_running(),
                "platform": platform,
                "platforms": [{"id": p, "label": platforms.label(p), "enabled": platforms.is_enabled(full, p)}
                              for p in platforms.PLATFORM_IDS],
                "upcoming": [{"date": d.isoformat(), "category": v["category"], "time": v["time"],
                              "label": cfg["categories"].get(v["category"], {}).get("label", v["category"])}
                             for d, v in platforms.upcoming(cfg["schedule"], now.date(), 21)][:7],
                "paused": self.ws.paused(), "config_errors": validate_config(full),
                "credentials": self.ws.state("credentials", {}), "notifications": notify_mod.unread(self.ws)[-20:],
                "queue": {s: sum(1 for p in q if p["status"] == s) for s in
                          ("queued", "awaiting_approval", "approved", "failed", "dry_run")},
                "next": {"generate_for": target.isoformat(), "category": crew.category_for(cfg, target),
                         # "Run now" defaults to a date that has a post: the target date, else the next scheduled one
                         "run_for": next((d.isoformat() for d, _s in platforms.upcoming(cfg["schedule"], target, 21)), target.isoformat()),
                         "generate_time": cfg["schedule"]["generate_time"], "post_time": cfg["schedule"]["post_time"],
                         "timezone": cfg["schedule"]["timezone"]},
                "dry_run": cfg["publishing"]["dry_run"], "approval": cfg["publishing"]["approval"],
                "published": sum(1 for p in self.ws.history() if platforms.platform_of(p) == platform)}

    def agents(self):
        cfg = self.ws.config()
        rows = []
        roster = team_mod.load(self.ws)["members"]
        for a in [monthly.MonthPlanner()] + CREW + [VoiceAgent(), BlackboardAgent(), ExplainerAgent(), ExplainrooAgent(), HyperFramesAgent(), RemotionFramesAgent(), RemotionAgent(), VideoReviewAgent(), HooksAgent(), Supervisor()]:
            role = {"research": "research", "writer": "writer"}.get(a.id)
            members = [m["name"] for m in roster if m["role"] == role][:cfg["team"][role]] if role else []
            rows.append({"id": a.id, "title": a.title, "name": a.name, "role": a.role, "members": members,
                         "uses_llm": getattr(a, "uses_llm", True),
                         "llm": agent_settings(cfg, a.id) if getattr(a, "uses_llm", True) else None})
            if a.id == "writer":
                rows.append({"id": "reviewer", "title": "Pre-reviewer", "name": "Iris", "members": [], "uses_llm": True,
                             "role": "Scores every draft the way the Editor will, so the best one goes on.",
                             "llm": agent_settings(cfg, "reviewer")})
        return {"agents": rows, "steps": STEPS}

    def run_detail(self, run_id, after):
        d = self.ws.runs_dir / run_id
        if not SAFE_ID.match(run_id) or not (d / "status.json").exists():
            return None
        files = sorted(p.name for p in d.iterdir() if p.is_file() and p.name not in ("events.jsonl",))
        mem = d / "memory.json"
        return {"status": json.loads((d / "status.json").read_text()), "events": read_events(d, after),
                "files": files, "memory": json.loads(mem.read_text()) if mem.exists() else []}

    def start_run(self, body):
        if crew.is_running():
            raise ValueError("a crew run is already in progress")
        platform, cfg = self._view(body.get("platform"))
        errs = validate_config(self.ws.config())
        if errs:
            raise ValueError("fix the settings first: " + "; ".join(errs[:3]))
        day = body.get("date") or crew.target_date(cfg).isoformat()
        datetime.strptime(day, "%Y-%m-%d")
        category = body.get("category") or None
        when = datetime.strptime(day, "%Y-%m-%d").date()
        if category and category not in cfg["categories"]:
            raise ValueError(f"{platforms.label(platform)} has no topic {category!r}: pick one from the Category list")
        if not category and not platforms.category_for(cfg["schedule"], when):
            nxt = platforms.upcoming(cfg["schedule"], crew.local_now(cfg).date(), 21)[:3]
            hint = "; ".join(f"{d.strftime('%a %Y-%m-%d')} ({cfg['categories'].get(s['category'], {}).get('label', s['category'])})"
                             for d, s in nxt)
            raise ValueError(f"nothing is scheduled for {platforms.label(platform)} on {when.strftime('%A %Y-%m-%d')}. Choose a topic "
                             f"in Category (it is written for that date), or pick a scheduled date" + (f": {hint}" if hint else ""))
        options = {}
        if body.get("format"):
            if body["format"] not in ("short", "long"):
                raise ValueError("format must be short or long")
            options["format"] = body["format"]
        if body.get("target_seconds"):
            options["target_seconds"] = int(body["target_seconds"])
        run_id = self.ws.new_run_id(day)
        outcome = {}

        def go():
            try:
                outcome["result"] = crew.run_crew(self.ws, day, category, dry_run=bool(body.get("dry_run")), run_id=run_id,
                                                  platform=platform, options=options)
            except Exception as e:
                traceback.print_exc()
                outcome["error"] = str(e)[:300]
                notify_mod.notify(self.ws, "Crew run crashed", str(e)[:300], level="error")
        threading.Thread(target=go, daemon=True).start()
        # Answer only once the run exists (the Workflow page opens it next), or say at once why it could not start.
        started = self.ws.runs_dir / run_id / "status.json"
        for _ in range(100):
            res = outcome.get("result")
            if started.exists():
                break
            if outcome.get("error"):
                raise ValueError(f"the crew could not start: {outcome['error']}")
            if res is not None and not res.get("run_id"):
                raise ValueError(f"the crew did not start: {res.get('reason', 'unknown reason')}")
            time.sleep(0.05)
        return {"run_id": run_id}

    # ---------- monthly plan ----------
    def plan(self, platform=None, month=None):
        """One month of the plan: the generated plans, the days they are assigned to, and the topics they came from."""
        platform, cfg = self._view(platform)
        today = crew.local_now(cfg).date()
        month = month or monthly.month_key(today)
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("month must look like 2026-11")
        return dict(monthly.view(self.ws, platform, month, today), today=today.isoformat(), this_month=monthly.month_key(today),
                    planning=cfg["planning"])

    def plan_generate(self, body):
        """Write the plans for the month's topics (the missing ones; never a plan twice)."""
        platform, cfg = self._view(body.get("platform"))
        today = crew.local_now(cfg).date()
        month = body.get("month") or monthly.month_key(today)
        if month < monthly.month_key(today):
            raise ValueError("that month is over: plans are written for this month or a coming one")
        out = monthly.generate(self.ws, platform, month, today=today)
        bad = [r["error"] for r in out["topics"].values() if isinstance(r, dict)]
        if bad and not out["added"]:
            raise ValueError(f"the Planner could not write the plans: {bad[0]}")
        return dict(self.plan(platform, month), added=out["added"], failed=len(bad))

    def plan_assign(self, body):
        platform, cfg = self._view(body.get("platform"))
        today = crew.local_now(cfg).date()
        item = monthly.assign(self.ws, platform, str(body.get("id") or ""), str(body.get("date") or ""), body.get("format"), today)
        return self.plan(platform, body.get("month") or item["assigned"]["date"][:7])

    def plan_unassign(self, body):
        platform = self._view(body.get("platform"))[0]
        monthly.unassign(self.ws, platform, str(body.get("id") or ""))
        return self.plan(platform, body.get("month"))

    # ---------- team ----------
    def team(self):
        cfg = self.ws.config()
        data = team_mod.load(self.ws)
        size = {r: cfg["team"][r] for r in team_mod.ROLES}
        rows = []
        for m in data["members"]:
            same = [x["id"] for x in data["members"] if x["role"] == m["role"]]
            v = team_mod.verdicts(m, cfg["team"]["fire_window"])
            rows.append(dict(m, working=same.index(m["id"]) < size[m["role"]], at_risk=len(v) >= 3 and
                             sum(v) / len(v) < cfg["team"]["fire_min_success"], window=v))
        return {"members": rows, "fired": data["fired"][::-1], "lessons": data["lessons"], "size": size,
                "rules": {k: cfg["team"][k] for k in ("fire_window", "fire_min_success", "pre_review")}}

    def memory(self):
        return {"memory": memory_mod.load(self.ws)}

    def memory_forget(self, body):
        memory_mod.forget(self.ws, body.get("step", ""), int(body.get("index", -1)))
        return self.memory()

    def team_action(self, action, body):
        role = body.get("role")
        if action == "fire":
            team_mod.fire(self.ws, body.get("id", ""), self.ws.config(),
                          reason=(body.get("reason") or "replaced from the Studio")[:200])
        elif action == "hire":
            if role not in team_mod.ROLES:
                raise ValueError("role must be research or writer")
            if sum(1 for m in team_mod.load(self.ws)["members"] if m["role"] == role) >= 4:
                raise ValueError("a team has at most 4 members; replace one instead")
            team_mod.hire(self.ws, role)
            cfg = self.ws.config()
            cfg["team"][role] = min(4, cfg["team"][role] + 1)
            self.ws.save_config(cfg)
        elif action == "lesson-remove":
            team_mod.remove_lesson(self.ws, role, int(body.get("index", -1)))
        else:
            raise ValueError(f"unknown action {action}")
        return self.team()

    # ---------- published list ----------
    def history_add(self, body):
        """Add a post you published yourself, so the crew never repeats its topic."""
        topic, text = (body.get("topic") or "").strip(), (body.get("text") or "").strip()
        day = (body.get("date") or "").strip()
        datetime.strptime(day, "%Y-%m-%d")
        if not 3 <= len(topic) <= 150 or len(text) > 3000:
            raise ValueError("the topic must be 3-150 characters (and the text under 3,000)")
        platform, cfg = self._view(body.get("platform"))
        cat = body.get("category") or ""
        if cat and cat not in cfg["categories"]:
            raise ValueError(f"unknown topic type {cat!r}")
        self.ws.add_history({"id": "manual-" + pysecrets.token_hex(4), "platform": platform, "date": day,
                             "topic": topic, "category": cat, "text": text, "imported": True, "added_by_hand": True})
        return {"history": self.ws.history()}

    def history_remove(self, body):
        """Forget a published entry (its topic may then be used again). Never touches LinkedIn."""
        key = (body.get("id"), body.get("date"), body.get("topic"))
        gone = self.ws.remove_history(lambda p: (p.get("id"), p.get("date"), p.get("topic")) == key)
        if not gone:
            raise KeyError("that entry is not in the published list")
        return {"history": self.ws.history()}

    def queue_action(self, pid, action, body):
        posts = self.ws.queue()
        post = next((p for p in posts if p["id"] == pid), None)
        if not post:
            raise KeyError(pid)
        if action == "approve":
            if post["status"] not in ("awaiting_approval", "queued", "failed", "dry_run"):
                raise ValueError(f"cannot approve a {post['status']} post")
            post["status"] = "approved"
        elif action == "veto":
            post["status"] = "vetoed"
        elif action == "restore":
            pcfg = platforms.view(self.ws.config(), platforms.platform_of(post))
            post["status"] = "awaiting_approval" if pcfg["publishing"]["approval"] == "manual" else "queued"
        elif action == "publish_now":
            post = publish_post(self.ws, dict(post))
            if post["status"] == "published":
                self.ws.save_queue([p for p in self.ws.queue() if p["id"] != pid])
                return post
        elif action == "edit" and platforms.platform_of(post) == "youtube":
            yt = post.setdefault("youtube", {})
            title = (body.get("title", yt.get("title")) or "").strip()
            desc = body.get("description", yt.get("description")) or ""
            tags = body.get("tags", yt.get("tags", []))
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not 5 <= len(title) <= 100 or len(desc) > 5000 or len(tags) > 15 or sum(len(t) + 1 for t in tags) > 500:
                raise ValueError("the title must be 5-100 characters, the description under 5,000, and at most 15 tags "
                                 "(500 characters in all)")
            yt.update(title=title, description=desc, tags=tags)
            post["topic"], post["text"], post["edited"] = title, desc, True
            if body.get("date"):
                d = datetime.strptime(body["date"], "%Y-%m-%d").date()
                post["date"], post["scheduled_at"] = d.isoformat(), scheduled_at(
                    platforms.view(self.ws.config(), "youtube"), d)
        elif action == "edit":
            text = body.get("text", post["text"])
            if not text.strip() or len(text) > 3000:
                raise ValueError("text must be 1-3000 characters")
            post["text"], post["first_comment"] = text, body.get("first_comment", post.get("first_comment", ""))
            if body.get("date"):
                d = datetime.strptime(body["date"], "%Y-%m-%d").date()
                post["date"], post["scheduled_at"] = d.isoformat(), scheduled_at(
                    platforms.view(self.ws.config(), platforms.platform_of(post)), d)
            post["edited"] = True
        elif action == "delete":
            self.ws.save_queue([p for p in posts if p["id"] != pid])
            return {"deleted": pid}
        else:
            raise ValueError(f"unknown action {action}")
        self.ws.save_queue([post if p["id"] == pid else p for p in self.ws.queue()])
        return post

    def credentials(self):
        llm = self.ws.config()["llm"]
        return {"secrets": self.ws.masked_secrets(), "status": self.ws.state("credentials", {}),
                "redirect_uri": self.redirect_uri, "scopes": linkedin.SCOPE,
                "youtube_redirect_uri": self.youtube_redirect_uri,
                "backend": llm["backend"], "base_url": llm.get("api", {}).get("base_url", "")}

    def save_credentials(self, body):
        allowed = {"linkedin_client_id", "linkedin_client_secret", "gmail_address", "gmail_app_password", "email_to",
                   "telegram_bot_token", "telegram_chat_id", "anthropic_api_key", "openai_api_key", "llm_api_key",
                   "youtube_client_id", "youtube_client_secret", "elevenlabs_api_key"}
        changes = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.items() if k in allowed}
        if any(k not in allowed for k in body):
            raise ValueError(f"only these can be set here: {sorted(allowed)}")
        for k, v in changes.items():
            if v is not None and (not isinstance(v, str) or len(v) > 400 or "\n" in v):
                raise ValueError(f"{k} looks wrong")
        cid = changes.get("linkedin_client_id")
        if cid and not re.fullmatch(r"[A-Za-z0-9]{8,40}", cid):
            raise ValueError("linkedin_client_id should be the 8-40 letter/digit Client ID from the app's Auth tab")
        if changes.get("youtube_client_id") and not re.fullmatch(r"[0-9]+-[A-Za-z0-9_]+\.apps\.googleusercontent\.com",
                                                                 changes["youtube_client_id"]):
            raise ValueError("youtube_client_id should look like 1234567890-abc123.apps.googleusercontent.com "
                             "(Google Cloud > APIs & Services > Credentials)")
        if "youtube_client_id" in changes or "youtube_client_secret" in changes:   # new app: the old connection is void
            changes.setdefault("youtube_refresh_token", None)
        for k in ("gmail_address", "email_to"):
            if changes.get(k) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", changes[k]):
                raise ValueError(f"{k} should be an email address")
        self.ws.update_secrets(**{k: v for k, v in changes.items()})
        return self.credentials()

    def test_email(self):
        """Send one email now, whether or not email notifications are switched on, and report the result."""
        s = self.ws.secrets()
        if not (s.get("gmail_address") and s.get("gmail_app_password")):
            return {"ok": False, "error": "save the Gmail address and App Password first"}
        cfg = self.ws.config()
        days = ", ".join(f"{d.title()} {cfg['categories'].get(c, {}).get('label', c)}"
                         for d, c in cfg["schedule"]["days"].items() if c)
        err = notify_mod.email(self.ws, "Test email", "If you can read this, Postcrew can email you notifications. "
                               "Real alerts look like this, with the post and its poster when there is one.",
                               details={"rows": [("Sent to", s.get("email_to") or s["gmail_address"]),
                                                 ("AI provider", cfg["llm"]["backend"]),
                                                 ("Publishing", "practice mode (nothing is sent)" if cfg["publishing"]["dry_run"]
                                                  else f"live, approval: {cfg['publishing']['approval']}"),
                                                 ("Posts go out at", f"{cfg['schedule']['post_time']} {cfg['schedule']['timezone']}"),
                                                 ("Weekly schedule", days)]},
                               action={"label": "Open Settings", "tab": "settings"}, subject="Postcrew: test email")
        return {"ok": not err, "error": err, "to": s.get("email_to") or s["gmail_address"]}

    def oauth_start(self):
        s = self.ws.secrets()
        if not (s.get("linkedin_client_id") and s.get("linkedin_client_secret")):
            raise ValueError("save the LinkedIn Client ID and Client Secret first")
        state = pysecrets.token_urlsafe(24)
        self.oauth_states = {k: v for k, v in self.oauth_states.items()
                             if v > datetime.now(timezone.utc) - timedelta(minutes=15)}
        self.oauth_states[state] = datetime.now(timezone.utc)
        return linkedin.authorize_url(s["linkedin_client_id"], self.redirect_uri, state)

    def oauth_callback(self, q):
        if q.get("error"):
            raise ValueError(f"LinkedIn said: {q['error']} - {q.get('error_description', '')}")
        state = q.get("state", "")
        if state not in self.oauth_states:
            raise ValueError("sign-in expired or did not start here; click Connect LinkedIn again")
        del self.oauth_states[state]
        s = self.ws.secrets()
        tok = linkedin.exchange_code(s["linkedin_client_id"], s["linkedin_client_secret"], q["code"], self.redirect_uri)
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 0)))
        li = linkedin.LinkedIn(tok["access_token"], self.ws.config()["publishing"]["linkedin_api_version"])
        info = li.userinfo()
        self.ws.update_secrets(linkedin_access_token=tok["access_token"],
                               linkedin_token_expires_at=expires.isoformat(timespec="seconds"),
                               linkedin_person_urn=f"urn:li:person:{info['sub']}", linkedin_name=info.get("name", ""))
        run_check(self.ws, notify_user=False)
        notify_mod.notify(self.ws, "LinkedIn connected", f"Signed in as {info.get('name', 'you')}; token valid "
                                                         f"until {expires.date().isoformat()}.", level="success")
        return info.get("name", "")

    # ---------- YouTube ----------
    def youtube_start(self):
        s = self.ws.secrets()
        if not (s.get("youtube_client_id") and s.get("youtube_client_secret")):
            raise ValueError("save the Google OAuth client ID and secret first")
        state = "yt-" + pysecrets.token_urlsafe(24)
        self.oauth_states = {k: v for k, v in self.oauth_states.items()
                             if v > datetime.now(timezone.utc) - timedelta(minutes=15)}
        self.oauth_states[state] = datetime.now(timezone.utc)
        return youtube.auth_url(s["youtube_client_id"], self.youtube_redirect_uri, state)

    def youtube_callback(self, q):
        if q.get("error"):
            raise ValueError(f"Google said: {q['error']}")
        state = q.get("state", "")
        if state not in self.oauth_states or not state.startswith("yt-"):
            raise ValueError("sign-in expired or did not start here; click Connect YouTube again")
        del self.oauth_states[state]
        s = self.ws.secrets()
        tok = youtube.exchange_code(s["youtube_client_id"], s["youtube_client_secret"], q["code"], self.youtube_redirect_uri)
        if not tok.get("refresh_token"):
            raise ValueError("Google did not return a refresh token: remove Postcrew from myaccount.google.com/permissions "
                             "and connect again")
        ch = youtube.YouTube(s["youtube_client_id"], s["youtube_client_secret"], tok["refresh_token"]).channel()
        self.ws.update_secrets(youtube_refresh_token=tok["refresh_token"], youtube_channel_title=ch.get("title", ""))
        run_check(self.ws, notify_user=False)
        notify_mod.notify(self.ws, "YouTube connected", f"Connected to the channel {ch.get('title', '')}.", level="success")
        return ch.get("title", "")

    def disconnect(self, app):
        if app == "youtube":
            self.ws.update_secrets(youtube_refresh_token=None, youtube_channel_title=None)
        elif app in ("linkedin", None):
            self.ws.update_secrets(linkedin_access_token=None, linkedin_token_expires_at=None,
                                   linkedin_person_urn=None, linkedin_name=None)
        else:
            raise ValueError(f"unknown app {app!r}")
        return run_check(self.ws, notify_user=False)

    # ---------- voice ----------
    def _voice_key(self):
        key = self.ws.secrets().get("elevenlabs_api_key")
        if not key:
            raise ValueError("add your ElevenLabs API key in Credentials first")
        return key

    def test_voice(self):
        try:
            r = voice_mod.check_key(self._voice_key())
        except voice_mod.VoiceError as e:
            return {"ok": False, "message": str(e), "characters_left": None}
        return {"ok": r["ok"], "message": r["message"], "characters_left": r.get("characters_left")}

    def voices(self):
        try:
            return {"voices": voice_mod.list_voices(self._voice_key())}
        except voice_mod.VoiceError as e:
            raise ValueError(str(e))

    def voice_sample(self, body):
        voice_id = str(body.get("voice_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{8,40}", voice_id):
            raise ValueError("pick a voice first")
        text = (body.get("text") or "This is how your videos will sound. Short sentences, clear words, one idea at a time.")[:300]
        vcfg = dict(self.ws.config()["platforms"]["youtube"]["video"]["voice"], voice_id=voice_id)
        try:
            r = voice_mod.cached_synthesize(self.ws.root, text, vcfg, self._voice_key())
        except voice_mod.VoiceError as e:
            raise ValueError(str(e))
        dest = self.ws.root / "media" / f"sample-{Path(r['path']).stem}.mp3"
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            dest.write_bytes(Path(r["path"]).read_bytes())
        return {"url": f"/media/{dest.name}"}

    # ---------- the owner's own script, voice and video ----------
    def assets_list(self, platform, day):
        return {"assets": assets_mod.describe(self.ws, platform, day, platforms.view(self.ws.config(), platform))}

    def asset_upload(self, platform, day, kind, name, rfile, length):
        try:
            assets_mod.save_stream(self.ws, platform, day, kind, name, rfile, length)
        except assets_mod.AssetError as e:
            raise ValueError(str(e))
        return self.assets_list(platform, day)

    def asset_remove(self, platform, day, kind):
        try:
            assets_mod.remove(self.ws, platform, day, kind)
        except assets_mod.AssetError as e:
            raise ValueError(str(e))
        return self.assets_list(platform, day)

    def test_ai(self):
        try:
            res = make_backend(self.ws.config(), self.ws.secrets()).call(
                "supervisor", "Reply only through the schema.", "Say ok.",
                {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})
            return {"ok": True, "model": res.model, "cost_usd": res.cost_usd, "seconds": res.duration_s}
        except LLMError as e:
            return {"ok": False, "error": str(e), "kind": e.kind}


def make_handler(studio):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PostcrewStudio"

        def log_message(self, fmt, *args):
            if not (self.path.startswith("/api/runs/") and self.command == "GET"):
                super().log_message(fmt, *args)

        # ---------- plumbing ----------
        def send(self, code, data=None, ctype="application/json", body=None, headers=None):
            if body is None:
                body = json.dumps(data, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def host_ok(self):
            if studio.token:   # reachable from the network: the access token is the guard, not the address
                return True
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in LOCAL_HOSTS

        def mutation_ok(self):
            origin = self.headers.get("Origin")
            if studio.token:   # a write must come from the very page the Studio served (same site as the Host it was reached on)
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
                if origin and (urlparse(origin).hostname or "") != host:
                    return False
            elif origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1", "::1"):
                return False
            return self.headers.get("X-Postcrew") == "1"

        def authorised(self, u):
            """(ok, redirect cookie header). Without a token (localhost only) everything is allowed."""
            if not studio.token:
                return True, None
            given = [self.headers.get("Authorization", "")[7:] if self.headers.get("Authorization", "").startswith("Bearer ") else ""]
            given += [c.split("=", 1)[1] for c in (self.headers.get("Cookie") or "").replace(" ", "").split(";") if c.startswith("postcrew_token=")]
            if any(g and pysecrets.compare_digest(g, studio.token) for g in given):
                return True, None
            link = parse_qs(u.query).get("token", [""])[0]
            if self.command == "GET" and link and pysecrets.compare_digest(link, studio.token):
                return True, f"postcrew_token={studio.token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
            return False, None

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def file(self, path, root):
            path = Path(path).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                return self.send(404, {"error": "not found"})
            ctype = ({".woff2": "font/woff2", ".js": "text/javascript", ".css": "text/css"}.get(path.suffix)
                     or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            return self.send(200, body=path.read_bytes(), ctype=ctype)

        def media(self, path, root):
            """Images, audio and video, streamed in pieces and with Range support so <video> can seek."""
            path = Path(path).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                return self.send(404, {"error": "not found"})
            size = path.stat().st_size
            ctype = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".png": "image/png"}.get(path.suffix) \
                or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end, code = 0, size - 1, 200
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                if start >= size or end < start:
                    return self.send(416, {"error": "range not satisfiable"}, headers={"Content-Range": f"bytes */{size}"})
                end, code = min(end, size - 1), 206
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command != "HEAD":
                with open(path, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)

        def page(self, title, message, ok=True):
            html = (f"<!doctype html><meta charset=utf-8><title>{title}</title><body style='font:16px system-ui;"
                    f"padding:40px;background:#f6f7f9'><h2 style='color:{'#0a7d43' if ok else '#b42318'}'>{title}</h2>"
                    f"<p>{message}</p><p><a href='/#credentials'>Back to Postcrew Studio</a></p>")
            return self.send(200, body=html.encode(), ctype="text/html; charset=utf-8")

        # ---------- routing ----------
        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def do_DELETE(self):
            self.route("DELETE")

        def route(self, method):
            if not self.host_ok():
                return self.send(403, {"error": "Studio only answers on localhost"})
            ok, cookie = self.authorised(urlparse(self.path))
            if not ok:
                page = (b"<!doctype html><meta charset=utf-8><title>Postcrew Studio</title><body style='font:16px system-ui;max-width:34rem;margin:15vh auto;padding:0 1rem'>"
                        b"<h2>Postcrew Studio is locked</h2><p>Open the link the server printed when it started: it ends with <code>/?token=...</code>. "
                        b"It also sits in <code>studio-token</code> in the workspace folder.</p>")
                return self.send(401, ctype="text/html; charset=utf-8", body=page)
            if cookie:   # the link with the token: keep it in a cookie, then show the Studio without the token in the address bar
                return self.send(302, {}, headers={"Set-Cookie": cookie, "Location": urlparse(self.path).path or "/"})
            if method != "GET" and not self.mutation_ok():
                return self.send(403, {"error": "missing X-Postcrew header or foreign origin"})
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path.rstrip("/") or "/"
            ws = studio.ws
            try:
                if method == "GET" and p in ("/", "/index.html"):
                    return self.file(STATIC / "index.html", STATIC)
                if method == "GET" and p.startswith("/static/"):
                    return self.file(STATIC / p[len("/static/"):], STATIC)
                if method == "GET" and p.startswith("/media/"):
                    return self.media(ws.root / "media" / p[len("/media/"):], ws.root / "media")
                if method == "GET" and p == "/oauth/start":
                    try:
                        return self.send(302, {}, headers={"Location": studio.oauth_start()})
                    except ValueError as e:
                        return self.page("Cannot connect yet", str(e), ok=False)
                if method == "GET" and p == "/oauth/callback":
                    try:
                        name = studio.oauth_callback(q)
                        return self.page("LinkedIn connected", f"Signed in as {name or 'you'}. You can close this tab.")
                    except (ValueError, linkedin.LinkedInError, KeyError) as e:
                        return self.page("LinkedIn sign-in failed", str(e), ok=False)
                m = re.match(r"^/api/runs/([^/]+)(?:/(artifact|file)/(.+))?$", p)
                if method == "GET" and m:
                    run_id, kind, name = m.groups()
                    if not SAFE_ID.match(run_id):
                        return self.send(400, {"error": "bad run id"})
                    if kind:
                        return self.file(ws.runs_dir / run_id / name, ws.runs_dir / run_id)
                    d = studio.run_detail(run_id, float(q.get("after", 0)))
                    return self.send(200, d) if d else self.send(404, {"error": "no such run"})
                if method == "GET" and p == "/oauth/youtube/start":
                    try:
                        return self.send(302, {}, headers={"Location": studio.youtube_start()})
                    except ValueError as e:
                        return self.page("Cannot connect yet", str(e), ok=False)
                if method == "GET" and p == "/oauth/youtube/callback":
                    try:
                        name = studio.youtube_callback(q)
                        return self.page("YouTube connected", f"Connected to {name or 'your channel'}. You can close this tab.")
                    except (ValueError, youtube.YouTubeError, KeyError) as e:
                        return self.page("YouTube sign-in failed", str(e), ok=False)
                m = re.match(r"^/api/assets/([a-z0-9-]+)/(\d{4}-\d{2}-\d{2})(?:/(remove))?$", p)
                if m:
                    platform, day, remove = m.groups()
                    if method == "GET" and not remove:
                        return self.send(200, studio.assets_list(platform, day))
                    if method == "POST" and remove:
                        return self.send(200, studio.asset_remove(platform, day, self.body().get("kind", "")))
                    if method == "POST":
                        n = int(self.headers.get("Content-Length") or 0)
                        return self.send(200, studio.asset_upload(platform, day, q.get("kind", ""), q.get("name", ""),
                                                                  self.rfile, n))
                m = re.match(r"^/api/team/(fire|hire|lesson-remove)$", p)
                if m and method == "POST":
                    return self.send(200, studio.team_action(m.group(1), self.body()))
                m = re.match(r"^/api/queue/([^/]+)/(approve|veto|restore|publish_now|edit|delete)$", p)
                if method == "POST" and m:
                    return self.send(200, studio.queue_action(m.group(1), m.group(2), self.body()))
                routes = {
                    ("GET", "/api/overview"): lambda: studio.overview(q.get("platform")),
                    ("GET", "/api/plan"): lambda: studio.plan(q.get("platform"), q.get("month")),
                    ("GET", "/api/team"): lambda: studio.team(),
                    ("GET", "/api/memory"): lambda: studio.memory(),
                    ("POST", "/api/memory/forget"): lambda: studio.memory_forget(self.body()),
                    ("POST", "/api/plan/generate"): lambda: studio.plan_generate(self.body()),
                    ("POST", "/api/plan/assign"): lambda: studio.plan_assign(self.body()),
                    ("POST", "/api/plan/unassign"): lambda: studio.plan_unassign(self.body()),
                    ("GET", "/api/agents"): lambda: studio.agents(),
                    ("GET", "/api/runs"): lambda: {"runs": crew.list_runs(ws)},
                    ("POST", "/api/runs"): lambda: studio.start_run(self.body()),
                    ("GET", "/api/queue"): lambda: {"queue": ws.queue(), "history": ws.history()},
                    ("POST", "/api/history"): lambda: studio.history_add(self.body()),
                    ("POST", "/api/history/remove"): lambda: studio.history_remove(self.body()),
                    ("GET", "/api/config"): lambda: {"config": ws.config()},
                    ("PUT", "/api/config"): lambda: self.save_config(),
                    ("POST", "/api/config/validate"): lambda: {"errors": validate_config(self.body().get("config", {}))},
                    ("GET", "/api/credentials"): lambda: studio.credentials(),
                    ("PUT", "/api/credentials"): lambda: studio.save_credentials(self.body()),
                    ("POST", "/api/credentials/check"): lambda: run_check(ws),
                    ("POST", "/api/credentials/disconnect"): lambda: studio.disconnect(self.body().get("app")),
                    ("POST", "/api/credentials/test-voice"): lambda: studio.test_voice(),
                    ("GET", "/api/voices"): lambda: studio.voices(),
                    ("POST", "/api/voices/sample"): lambda: studio.voice_sample(self.body()),
                    ("POST", "/api/credentials/test-ai"): lambda: studio.test_ai(),
                    ("GET", "/api/notifications"): lambda: ws.state("notifications", {"items": []}),
                    ("POST", "/api/notifications/read"): lambda: (notify_mod.mark_read(ws, self.body().get("ids")),
                                                                  {"ok": True})[1],
                    ("POST", "/api/notifications/test"): lambda: notify_mod.notify(
                        ws, "Test notification", "If you can read this, notifications work.", level="info"),
                    ("POST", "/api/notifications/test-email"): lambda: studio.test_email(),
                    ("POST", "/api/pause"): lambda: self.pause(),
                }
                fn = routes.get((method, p))
                if not fn:
                    return self.send(404, {"error": f"no route {method} {p}"})
                return self.send(200, fn())
            except KeyError as e:
                return self.send(404, {"error": f"not found: {e}"})
            except (ValueError, linkedin.LinkedInError) as e:
                return self.send(400, {"error": str(e)})
            except Exception as e:
                traceback.print_exc()
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})

        def save_config(self):
            cfg = self.body().get("config")
            if not isinstance(cfg, dict):
                raise ValueError("send {\"config\": {...}}")
            errs = validate_config(cfg)
            if errs:
                return {"ok": False, "errors": errs}
            studio.ws.save_config(cfg)
            return {"ok": True, "config": studio.ws.config()}

        def pause(self):
            flag = studio.ws.root / "PAUSE"
            if self.body().get("paused"):
                flag.write_text("paused from the Studio\n")
            elif flag.exists():
                flag.unlink()
            return {"paused": studio.ws.paused()}

    return Handler


def lan_addresses():
    """This computer's address(es) on the local network, for the link the server prints."""
    import socket
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # no packet is sent: it only picks the interface a LAN address would leave by
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        found += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return [a for a in dict.fromkeys(found) if not a.startswith("127.")]


def access_token(ws, given=None):
    """The token that unlocks a Studio opened to the network: --token / $POSTCREW_TOKEN, else one made once and kept in the workspace."""
    import os
    token = given or os.environ.get("POSTCREW_TOKEN")
    if token:
        return token
    path = ws.root / "studio-token"
    saved = path.read_text().strip() if path.exists() else ""
    if saved:
        return saved
    token = pysecrets.token_urlsafe(18)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def serve(ws, port=8765, scheduler=True, host="127.0.0.1", token=None):
    from ..scheduler import Scheduler
    local = host in ("127.0.0.1", "localhost", "::1")
    token = None if local else access_token(ws, token)
    studio = Studio(ws, port, token)
    httpd = ThreadingHTTPServer((host, port), make_handler(studio))
    if scheduler:
        Scheduler(ws).start()
    print(f"Postcrew Studio {__version__}: http://localhost:{port}  (workspace: {ws.root})", flush=True)
    if token:
        shown = lan_addresses() if host in ("0.0.0.0", "") else [host]
        print("Open to the network. Anyone with the link below can run the crew and publish, so share it only with people you trust:", flush=True)
        for a in shown or ["<this computer's address>"]:
            print(f"  http://{a}:{port}/?token={token}", flush=True)
        print("(LinkedIn and YouTube sign-in redirects to localhost: connect those accounts on this computer, or through an SSH tunnel.)", flush=True)
    if scheduler:
        print("Scheduler is on: it writes, reviews and publishes on the times in Settings.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
