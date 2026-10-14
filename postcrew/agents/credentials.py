"""Credential Monitor agent: keeps the LinkedIn token and the AI provider healthy.

LinkedIn: token present? days until expiry? does LinkedIn still accept it (GET /v2/userinfo, free)?
AI provider: Claude Code installed and logged in (`claude auth status --json`, no tokens spent), or the API key
accepted / the OpenAI-compatible server reachable (GET <base>/models, free).
Runs daily, at Studio start, before every crew run and before every publish. Problems become
notifications with a "Reconnect" button that opens the Credentials tab.
"""
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..linkedin import LinkedIn, LinkedInError
from ..llm import BACKENDS, KEY_ENV, LLMError
from ..notify import notify
from .base import Agent, AgentError

GOOD = ("ok", "expiring")


def check_linkedin(ws, cfg, live=True, client_factory=LinkedIn):
    s = ws.secrets()
    token, exp = s.get("linkedin_access_token"), s.get("linkedin_token_expires_at")
    if not (s.get("linkedin_client_id") and s.get("linkedin_client_secret")):
        if not token:
            return {"state": "missing", "message": "LinkedIn app not configured: add the Client ID and Secret, "
                                                   "then click Connect LinkedIn."}
    if not token:
        return {"state": "missing", "message": "Not connected to LinkedIn yet: click Connect LinkedIn."}
    out = {"expires_at": exp, "name": s.get("linkedin_name", "")}
    if exp:
        days = (datetime.fromisoformat(exp).replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        out["days_left"] = days
        if days < 0:
            return {**out, "state": "expired", "message": f"LinkedIn token expired on {exp[:10]}. Reconnect."}
    if live:
        try:
            info = client_factory(token, cfg["publishing"]["linkedin_api_version"]).userinfo()
            out["name"] = info.get("name") or out["name"]
        except LinkedInError as e:
            if e.unauthorized:
                return {**out, "state": "invalid", "message": "LinkedIn rejected the token (revoked or expired). "
                                                              "Reconnect."}
            return {**out, "state": "unreachable", "message": f"Could not reach LinkedIn to check the token: {e}"}
    warn = cfg["notifications"].get("warn_days_before_expiry", 7)
    if out.get("days_left") is not None and out["days_left"] <= warn:
        return {**out, "state": "expiring", "message": f"LinkedIn token expires in {out['days_left']} day(s) "
                                                       f"({exp[:10]}). Reconnect to renew it."}
    return {**out, "state": "ok", "message": "LinkedIn token is valid" +
            (f" for {out['days_left']} more days." if out.get("days_left") is not None else ".")}


def check_claude(cfg, runner=subprocess.run):
    binary = cfg["llm"].get("claude_path") or "claude"
    if not shutil.which(binary):
        return {"state": "missing", "message": f"Claude Code CLI '{binary}' is not installed or not on PATH."}
    try:
        r = runner([binary, "auth", "status", "--json"], capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"state": "unknown", "message": f"Could not read Claude Code login status: {str(e)[:120]}"}
    if not info.get("loggedIn"):
        return {"state": "logged_out", "message": "Claude Code is not logged in. Run `claude` once and log in."}
    return {"state": "ok", "message": f"Claude Code logged in ({info.get('authMethod', 'account')}).",
            "plan": info.get("subscriptionType", "")}


PROVIDER = {"claude-code": "Claude Code", "anthropic": "Claude API", "openai": "OpenAI API",
            "openai-compatible": "OpenAI-compatible server"}


def check_api(cfg, secrets, opener=urllib.request.urlopen):
    """Is the API key accepted (or the compatible server up)? Lists the models: free, no tokens spent."""
    name = cfg["llm"]["backend"]
    b = BACKENDS[name](cfg, secrets, opener=opener)
    if not b.available():
        return {"state": "missing", "message": f"No {PROVIDER[name]} key: add it in Credentials (or set {KEY_ENV[name]})."}
    req = urllib.request.Request(f"{b.base}/models", headers=b.headers())
    try:
        with opener(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"state": "invalid", "message": f"{PROVIDER[name]} rejected the API key (HTTP {e.code})."}
        if name != "openai-compatible" or e.code not in (404, 405):  # some servers have no /models
            return {"state": "unreachable", "message": f"{PROVIDER[name]} answered HTTP {e.code}."}
    except (OSError, LLMError) as e:
        return {"state": "unreachable", "message": f"Could not reach {b.base}: {str(e)[:120]}"}
    return {"state": "ok", "message": f"{PROVIDER[name]} is ready ({b.base}).", "provider": PROVIDER[name]}


def check_ai(ws, cfg, runner=subprocess.run, opener=urllib.request.urlopen):
    name = cfg["llm"]["backend"]
    out = check_claude(cfg, runner) if name == "claude-code" else check_api(cfg, ws.secrets(), opener)
    return {**out, "backend": name, "provider": PROVIDER[name]}


def run_check(ws, live=True, notify_user=True, client_factory=LinkedIn, runner=subprocess.run,
              opener=urllib.request.urlopen):
    cfg = ws.config()
    status = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "linkedin": check_linkedin(ws, cfg, live, client_factory), "ai": check_ai(ws, cfg, runner, opener)}
    status["ok"] = status["linkedin"]["state"] in GOOD and status["ai"]["state"] == "ok"
    ws.save_state("credentials", status)
    if notify_user:
        li, cl = status["linkedin"], status["ai"]
        if li["state"] not in ("ok", "unreachable"):
            notify(ws, "LinkedIn connection needs attention", li["message"],
                   level="warning" if li["state"] == "expiring" else "error", key=f"linkedin-{li['state']}",
                   action={"label": "Reconnect LinkedIn", "tab": "credentials"},
                   details={"rows": [("State", li["state"]), ("Token expires", (li.get("expires_at") or "unknown")[:10]),
                                     ("Days left", li.get("days_left", "unknown")),
                                     ("What to do", "Open Credentials and click Reconnect LinkedIn (10 seconds). "
                                                    "Queued posts wait until then.")]})
        if cl["state"] != "ok":
            notify(ws, f"{cl['provider']} needs attention", cl["message"], level="error", key=f"ai-{cl['state']}",
                   details={"rows": [("AI provider", cl["provider"]), ("State", cl["state"]), ("Problem", cl["message"])]},
                   action={"label": "Open Credentials", "tab": "credentials"})
    return status


class CredentialsAgent(Agent):
    id = "credentials"
    title = "Credential Monitor"
    name = "Aegis"
    role = "Checks the LinkedIn token and the AI provider are ready before any work starts."
    uses_llm = False

    def run(self, ctx, guidance):
        return run_check(ctx.ws, live=not ctx.dry_run)

    def validate(self, ctx, out):
        if out["ai"]["state"] != "ok":
            raise AgentError(out["ai"]["message"], fatal=True)
        li = out["linkedin"]
        if li["state"] not in GOOD and not ctx.cfg["publishing"]["dry_run"]:
            ctx.run.event(self.id, "warning", f"{li['message']} The post will be written and queued, but cannot "
                                              f"be published until you reconnect.", level="warning")
        return []

    def summary(self, out):
        return f"LinkedIn: {out['linkedin']['state']} · {out['ai']['provider']}: {out['ai']['state']}"
