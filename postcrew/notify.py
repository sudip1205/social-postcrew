"""Notifications: always shown in the Studio, optionally as a desktop notification and/or Telegram message.

`key` de-duplicates: the same key is not re-sent within `quiet_hours` (e.g. one expiry warning per day).
"""
import json
import platform
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone


def _desktop(title, message):
    try:
        if platform.system() == "Darwin" and shutil.which("osascript"):
            script = f"display notification {json.dumps(message[:200])} with title {json.dumps(title[:80])}"
            subprocess.run(["osascript", "-e", script], timeout=10, capture_output=True)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title[:80], message[:200]], timeout=10, capture_output=True)
    except Exception:
        pass


def _telegram(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15).read()
        return None
    except Exception as e:
        return str(e)[:200]


def notify(ws, title, message, level="info", key=None, action=None, quiet_hours=20):
    """level: info | success | warning | error. action: {"label", "tab"} shown as a button in the Studio."""
    items = ws.state("notifications", {"items": []})["items"]
    now = datetime.now(timezone.utc)
    if key:
        for n in items:
            if n.get("key") == key and now - datetime.fromisoformat(n["ts"]) < timedelta(hours=quiet_hours):
                return n
    n = {"id": uuid.uuid4().hex[:10], "ts": now.isoformat(timespec="seconds"), "level": level, "title": title,
         "message": message, "key": key, "action": action, "read": False}
    items = (items + [n])[-200:]
    ws.save_state("notifications", {"items": items})
    print(f"[notify:{level}] {title}: {message}", flush=True)
    cfg = ws.config()["notifications"]
    if cfg.get("desktop"):
        _desktop(f"Postcrew: {title}", message)
    s = ws.secrets()
    if cfg.get("telegram") and s.get("telegram_bot_token") and s.get("telegram_chat_id"):
        err = _telegram(s["telegram_bot_token"], s["telegram_chat_id"], f"Postcrew - {title}\n{message}")
        if err:
            n["telegram_error"] = err
    return n


def unread(ws):
    return [n for n in ws.state("notifications", {"items": []})["items"] if not n.get("read")]


def mark_read(ws, ids=None):
    data = ws.state("notifications", {"items": []})
    for n in data["items"]:
        if ids is None or n["id"] in ids:
            n["read"] = True
    ws.save_state("notifications", data)
