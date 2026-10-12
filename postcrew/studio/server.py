"""Postcrew Studio: local web UI + JSON API. Standard library only.

Binds to 127.0.0.1. Secrets are write-only from the browser (it only learns whether each one is set).
Every state-changing request must carry the X-Postcrew header and a localhost Origin/Host, which blocks
other web sites from driving the Studio through your browser (CSRF / DNS rebinding).
"""
import json
import mimetypes
import re
import secrets as pysecrets
import threading
import traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__, crew, linkedin, notify as notify_mod
from ..agents import planner as planner_mod
from ..agents import team as team_mod
from ..agents.credentials import run_check
from ..agents.publisher import publish_one, scheduled_at
from ..agents.supervisor import CREW, Supervisor
from ..llm import LLMError, agent_settings, make_backend
from ..runlog import STEPS, read_events
from ..workspace import validate_config

STATIC = Path(__file__).resolve().parent / "static"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class Studio:
    def __init__(self, ws, port=8765):
        self.ws, self.port = ws, port
        self.oauth_states = {}

    @property
    def redirect_uri(self):
        return f"http://localhost:{self.port}/oauth/callback"

    # ---------- api ----------
    def overview(self):
        cfg = self.ws.config()
        q = self.ws.queue()
        now = crew.local_now(cfg)
        target = crew.target_date(cfg, now)
        return {"version": __version__, "workspace": str(self.ws.root), "running": crew.is_running(),
                "paused": self.ws.paused(), "config_errors": validate_config(cfg),
                "credentials": self.ws.state("credentials", {}), "notifications": notify_mod.unread(self.ws)[-20:],
                "queue": {s: sum(1 for p in q if p["status"] == s) for s in
                          ("queued", "awaiting_approval", "approved", "failed", "dry_run")},
                "next": {"generate_for": target.isoformat(), "category": crew.category_for(cfg, target),
                         "generate_time": cfg["schedule"]["generate_time"], "post_time": cfg["schedule"]["post_time"],
                         "timezone": cfg["schedule"]["timezone"]},
                "dry_run": cfg["publishing"]["dry_run"], "approval": cfg["publishing"]["approval"],
                "published": len(self.ws.history())}

    def agents(self):
        cfg = self.ws.config()
        rows = []
        for a in [planner_mod.PlannerAgent()] + CREW + [Supervisor()]:
            rows.append({"id": a.id, "title": a.title, "role": a.role, "uses_llm": getattr(a, "uses_llm", True),
                         "llm": agent_settings(cfg, a.id) if getattr(a, "uses_llm", True) else None})
            if a.id == "writer":
                rows.append({"id": "reviewer", "title": "Pre-reviewer", "uses_llm": True,
                             "role": "Scores every draft the way the Editor will, so the best one goes on.",
                             "llm": agent_settings(cfg, "reviewer")})
        return {"agents": rows, "steps": STEPS}

    def run_detail(self, run_id, after):
        d = self.ws.runs_dir / run_id
        if not SAFE_ID.match(run_id) or not (d / "status.json").exists():
            return None
        files = sorted(p.name for p in d.iterdir() if p.is_file() and p.name not in ("events.jsonl",))
        return {"status": json.loads((d / "status.json").read_text()), "events": read_events(d, after),
                "files": files}

    def start_run(self, body):
        if crew.is_running():
            raise ValueError("a crew run is already in progress")
        cfg = self.ws.config()
        errs = validate_config(cfg)
        if errs:
            raise ValueError("fix the settings first: " + "; ".join(errs[:3]))
        day = body.get("date") or crew.target_date(cfg).isoformat()
        datetime.strptime(day, "%Y-%m-%d")
        category = body.get("category") or None
        run_id = self.ws.new_run_id(day)

        def go():
            try:
                crew.run_crew(self.ws, day, category, dry_run=bool(body.get("dry_run")), run_id=run_id)
            except Exception as e:
                traceback.print_exc()
                notify_mod.notify(self.ws, "Crew run crashed", str(e)[:300], level="error")
        threading.Thread(target=go, daemon=True).start()
        return {"run_id": run_id}

    # ---------- week plan ----------
    def plan(self):
        """Monday-Sunday of the current week: category, planned topic, and whether it is written or past."""
        cfg = self.ws.config()
        today = crew.local_now(cfg).date()
        week = planner_mod.this_week(today)
        entries = planner_mod.load_plan(self.ws)
        queue = {p["date"]: p for p in self.ws.queue() if p.get("status") != "vetoed"}
        hist = {p.get("date"): p for p in self.ws.history() if not p.get("imported")}
        rows = []
        for d in week:
            iso, cat = d.isoformat(), cfg["schedule"]["days"].get(planner_mod.WEEKDAYS[d.weekday()]) or ""
            c = cfg["categories"].get(cat, {})
            done = hist.get(iso) or queue.get(iso)
            rows.append({"date": iso, "weekday": d.strftime("%A"), "category": cat, "label": c.get("label", ""),
                         "plan_ahead": c.get("plan_ahead", True), "fixed": c.get("media") == "animation" or cat == "week-recap",
                         "entry": entries.get(iso) if (entries.get(iso) or {}).get("category") == cat else None,
                         "written": ({"status": "published" if iso in hist else done.get("status"),
                                      "topic": done.get("topic", "")} if done else None),
                         "past": d <= today})
        return {"days": rows, "planning": cfg["planning"], "ideas": planner_mod.idea_status(self.ws, cfg),
                "week": [week[0].isoformat(), week[-1].isoformat()], "today": today.isoformat()}

    def _plan_day(self, day):
        datetime.strptime(day, "%Y-%m-%d")
        row = next((r for r in self.plan()["days"] if r["date"] == day), None)
        if not row or not row["category"]:
            raise ValueError(f"{day} has no post scheduled (or is outside this week)")
        if row["past"]:
            raise ValueError(f"{day} is today or already past; its post is already being written")
        if row["written"]:
            raise ValueError(f"the {day} post is already written ({row['written']['status']}); edit it in the Queue")
        return row

    def plan_save(self, body):
        """Save several days at once: {"days": {date: {"topic", "angle"}}}. Checked first, then all saved."""
        days = body.get("days")
        if not isinstance(days, dict) or not days:
            raise ValueError("nothing to save")
        checked = []
        for day, v in days.items():
            row = self._plan_day(day)
            topic, angle = (v.get("topic") or "").strip(), (v.get("angle") or "").strip()
            if topic and (not 5 <= len(topic) <= 90 or len(angle) > 400):
                raise ValueError(f"{row['weekday']}: the topic must be 5-90 characters and the angle under 400")
            checked.append((day, row, topic, angle))
        for day, row, topic, angle in checked:
            self._set_topic(day, row, topic, angle)
        return self.plan()

    def plan_edit(self, day, body):
        return self.plan_save({"days": {day: body}})

    def _set_topic(self, day, row, topic, angle):
        old = row["entry"] or {}
        if not topic:
            planner_mod.set_entry(self.ws, day, None)
            return
        if topic == old.get("topic") and angle == old.get("angle", ""):
            return  # unchanged: keep who chose it
        planner_mod.set_entry(self.ws, day, {"category": row["category"], "topic": topic, "angle": angle,
                                             "search_queries": [] if topic != old.get("topic") else
                                             old.get("search_queries", []),
                                             "source": "manual", "rejected": old.get("rejected", [])})

    def plan_suggest(self, day, body):
        self._plan_day(day)
        out = planner_mod.PlannerAgent().plan(self.ws, [datetime.strptime(day, "%Y-%m-%d").date()],
                                              hint=(body.get("hint") or "").strip()[:300], force=True)
        if out.get(day, {}).get("error"):
            raise ValueError(f"the planner could not find a new topic: {out[day]['error']}")
        return self.plan()

    def plan_fill(self, body=None):
        """Plan the open days; replan=True also replaces the planner's own topics (yours are kept)."""
        if (body or {}).get("replan"):
            today = crew.local_now(self.ws.config()).date()
            out = planner_mod.PlannerAgent().plan(self.ws, planner_mod.days_left(today), replan=True)
            bad = [e["error"] for e in out.values() if "error" in e]
            if bad:
                raise ValueError(f"{len(bad)} day(s) could not be re-planned: {bad[0]}")
        else:
            planner_mod.plan_week(self.ws, crew.local_now(self.ws.config()).date())
        return self.plan()

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
        cat = body.get("category") or ""
        if cat and cat not in self.ws.config()["categories"]:
            raise ValueError(f"unknown topic type {cat!r}")
        self.ws.add_history({"id": "manual-" + pysecrets.token_hex(4), "date": day, "topic": topic, "category": cat,
                             "text": text, "imported": True, "added_by_hand": True})
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
            post["status"] = "awaiting_approval" if self.ws.config()["publishing"]["approval"] == "manual" else "queued"
        elif action == "publish_now":
            post = publish_one(self.ws, dict(post))
            if post["status"] == "published":
                self.ws.save_queue([p for p in self.ws.queue() if p["id"] != pid])
                return post
        elif action == "edit":
            text = body.get("text", post["text"])
            if not text.strip() or len(text) > 3000:
                raise ValueError("text must be 1-3000 characters")
            post["text"], post["first_comment"] = text, body.get("first_comment", post.get("first_comment", ""))
            if body.get("date"):
                d = datetime.strptime(body["date"], "%Y-%m-%d").date()
                post["date"], post["scheduled_at"] = d.isoformat(), scheduled_at(self.ws.config(), d)
            post["edited"] = True
        elif action == "delete":
            self.ws.save_queue([p for p in posts if p["id"] != pid])
            return {"deleted": pid}
        else:
            raise ValueError(f"unknown action {action}")
        self.ws.save_queue([post if p["id"] == pid else p for p in self.ws.queue()])
        return post

    def credentials(self):
        return {"secrets": self.ws.masked_secrets(), "status": self.ws.state("credentials", {}),
                "redirect_uri": self.redirect_uri, "scopes": linkedin.SCOPE}

    def save_credentials(self, body):
        allowed = {"linkedin_client_id", "linkedin_client_secret", "gmail_address", "gmail_app_password", "email_to",
                   "telegram_bot_token", "telegram_chat_id"}
        changes = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.items() if k in allowed}
        if any(k not in allowed for k in body):
            raise ValueError(f"only these can be set here: {sorted(allowed)}")
        for k, v in changes.items():
            if v is not None and (not isinstance(v, str) or len(v) > 400 or "\n" in v):
                raise ValueError(f"{k} looks wrong")
        cid = changes.get("linkedin_client_id")
        if cid and not re.fullmatch(r"[A-Za-z0-9]{8,40}", cid):
            raise ValueError("linkedin_client_id should be the 8-40 letter/digit Client ID from the app's Auth tab")
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
        err = notify_mod._gmail(s["gmail_address"], s["gmail_app_password"], s.get("email_to"), "Postcrew: test email",
                                "If you can read this, Postcrew can email you notifications.")
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

    def test_claude(self):
        try:
            res = make_backend(self.ws.config()).call(
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
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in LOCAL_HOSTS

        def mutation_ok(self):
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1", "::1"):
                return False
            return self.headers.get("X-Postcrew") == "1"

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("request too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def file(self, path, root):
            path = Path(path).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                return self.send(404, {"error": "not found"})
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return self.send(200, body=path.read_bytes(), ctype=ctype)

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
                    return self.file(ws.root / "media" / p[len("/media/"):], ws.root / "media")
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
                m = re.match(r"^/api/team/(fire|hire|lesson-remove)$", p)
                if m and method == "POST":
                    return self.send(200, studio.team_action(m.group(1), self.body()))
                m = re.match(r"^/api/plan/(\d{4}-\d{2}-\d{2})(?:/(suggest))?$", p)
                if m and method in ("PUT", "POST"):
                    fn = studio.plan_suggest if m.group(2) else studio.plan_edit
                    return self.send(200, fn(m.group(1), self.body()))
                m = re.match(r"^/api/queue/([^/]+)/(approve|veto|restore|publish_now|edit|delete)$", p)
                if method == "POST" and m:
                    return self.send(200, studio.queue_action(m.group(1), m.group(2), self.body()))
                routes = {
                    ("GET", "/api/overview"): lambda: studio.overview(),
                    ("GET", "/api/plan"): lambda: studio.plan(),
                    ("GET", "/api/team"): lambda: studio.team(),
                    ("PUT", "/api/plan"): lambda: studio.plan_save(self.body()),
                    ("POST", "/api/plan/fill"): lambda: studio.plan_fill(self.body()),
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
                    ("POST", "/api/credentials/disconnect"): lambda: self.disconnect(),
                    ("POST", "/api/credentials/test-claude"): lambda: studio.test_claude(),
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

        def disconnect(self):
            studio.ws.update_secrets(linkedin_access_token=None, linkedin_token_expires_at=None,
                                     linkedin_person_urn=None, linkedin_name=None)
            return run_check(studio.ws, notify_user=False)

        def pause(self):
            flag = studio.ws.root / "PAUSE"
            if self.body().get("paused"):
                flag.write_text("paused from the Studio\n")
            elif flag.exists():
                flag.unlink()
            return {"paused": studio.ws.paused()}

    return Handler


def serve(ws, port=8765, scheduler=True):
    from ..scheduler import Scheduler
    studio = Studio(ws, port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(studio))
    if scheduler:
        Scheduler(ws).start()
    print(f"Postcrew Studio {__version__}: http://localhost:{port}  (workspace: {ws.root})", flush=True)
    if scheduler:
        print("Scheduler is on: it writes, reviews and publishes on the times in Settings.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
