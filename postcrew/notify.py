"""Notifications: always shown in the Studio, optionally as a desktop notification, Gmail email and/or Telegram
message.

`key` de-duplicates: the same key is not re-sent within `quiet_hours` (e.g. one expiry warning per day).
`details` adds structure for email and Telegram: {"rows": [(label, value), ...], "text": the post, "image": a path}.
Emails are HTML (a coloured header, a table of the details, the post and its poster) with a plain-text part.
"""
import html
import json
import mimetypes
import platform
import shutil
import smtplib
import ssl
import subprocess
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

SMTP = smtplib.SMTP_SSL  # replaced in tests
LEVELS = {  # colour, soft background, label
    "info": ("#4f46e5", "#eef2ff", "Update"), "success": ("#059669", "#ecfdf5", "Done"),
    "warning": ("#d97706", "#fffbeb", "Needs attention"), "error": ("#e11d48", "#fff1f2", "Problem")}


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


def _plain(title, message, rows=(), text="", link=""):
    out = [title, "=" * len(title), "", message]
    if rows:
        w = max(len(str(k)) for k, _ in rows)
        out += [""] + [f"{str(k):<{w}}  {v}" for k, v in rows]
    if text:
        out += ["", "The post", "--------", text]
    if link:
        out += ["", f"Open Postcrew Studio: {link}"]
    return "\n".join(out) + "\n"


def _html(title, message, level="info", rows=(), text="", image_cid=None, link="", button="Open Postcrew Studio"):
    """A self-contained HTML email: inline styles and tables only, so it renders the same in Gmail, Outlook and
    Apple Mail, in light and dark mode."""
    color, soft, label = LEVELS.get(level, LEVELS["info"])
    e = lambda v: html.escape(str(v))
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    table = "".join(
        f'<tr><td style="padding:10px 14px;border-top:1px solid #e2e8f0;color:#64748b;font-size:13px;'
        f'white-space:nowrap;vertical-align:top;width:34%">{e(k)}</td>'
        f'<td style="padding:10px 14px;border-top:1px solid #e2e8f0;color:#0f172a;font-size:14px;font-weight:600;'
        f'word-break:break-word">{e(v)}</td></tr>' for k, v in rows)
    table = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;'
             f'border-radius:10px;border-collapse:separate;overflow:hidden;margin:20px 0 4px">{table}</table>') if rows else ""
    post = (f'<div style="margin:22px 0 6px;font-size:12px;font-weight:700;letter-spacing:.08em;color:{color};'
            f'text-transform:uppercase">The post</div><div style="border:1px solid #e2e8f0;border-left:4px solid {color};'
            f'border-radius:8px;padding:14px 16px;background:#f8fafc;color:#0f172a;font-size:14px;line-height:1.55">'
            + e(text).replace("\n", "<br>") + "</div>") if text else ""
    img = (f'<img src="cid:{image_cid}" alt="Poster" width="100%" style="display:block;max-width:100%;'
           f'border-radius:10px;margin:16px 0 0;border:1px solid #e2e8f0">') if image_cid else ""
    btn = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0 4px"><tr><td '
           f'style="background:{color};border-radius:8px"><a href="{e(link)}" style="display:inline-block;'
           f'padding:11px 20px;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px">{e(button)} &rarr;'
           f'</a></td></tr></table>') if link else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light"><title>{e(title)}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:{font}">
<div style="display:none;max-height:0;overflow:hidden">{e(message[:140])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0">
<tr><td style="background:linear-gradient(135deg,#312e81,#4f46e5 55%,#06b6d4);background-color:#4f46e5;padding:18px 26px">
  <span style="color:#ffffff;font-size:13px;font-weight:800;letter-spacing:.18em">&#9670; POSTCREW</span></td></tr>
<tr><td style="padding:26px 26px 8px">
  <span style="display:inline-block;background:{soft};color:{color};font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;letter-spacing:.04em">{e(label)}</span>
  <h1 style="margin:12px 0 8px;font-size:22px;line-height:1.3;color:#0f172a">{e(title)}</h1>
  <p style="margin:0;color:#334155;font-size:15px;line-height:1.55">{e(message)}</p>
  {table}{post}{img}{btn}
</td></tr>
<tr><td style="padding:18px 26px 24px;color:#94a3b8;font-size:12px;line-height:1.5;border-top:1px solid #f1f5f9">
  Sent by Postcrew on your computer. Turn email alerts off in Studio &gt; Settings &gt; Publishing and alerts.</td></tr>
</table></td></tr></table></body></html>"""


def _gmail(address, app_password, to, subject, body, smtp=None, html_body=None, image=None):
    """Send through Gmail SMTP. Needs a Google App Password (2-Step Verification on), not the account password.
    html_body may contain "{cid}", replaced by the content id of `image` (a file shown inline)."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = f"Postcrew <{address}>", to or address, subject[:150]
    msg.set_content(body)
    if html_body:
        cid = make_msgid(domain="postcrew.local")[1:-1] if image else ""
        msg.add_alternative(html_body.replace("{cid}", cid), subtype="html")
        if image:
            kind = (mimetypes.guess_type(str(image))[0] or "image/png").split("/")
            msg.get_payload()[1].add_related(Path(image).read_bytes(), maintype=kind[0], subtype=kind[1],
                                             cid=f"<{cid}>", filename=Path(image).name)
    try:
        with (smtp or SMTP)("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as s:
            s.login(address, app_password.replace(" ", ""))
            s.send_message(msg)
        return None
    except Exception as e:
        return str(e)[:200]


def email(ws, title, message, level="info", details=None, action=None, subject=None):
    """Build and send one notification email. Returns an error message, or None."""
    s = ws.secrets()
    if not (s.get("gmail_address") and s.get("gmail_app_password")):
        return "save the Gmail address and App Password first"
    d = details or {}
    rows, text = [tuple(r) for r in d.get("rows", [])], d.get("text", "")
    image = d.get("image") if d.get("image") and Path(d["image"]).is_file() else None
    base = ws.config()["notifications"].get("studio_url", "http://localhost:8765").rstrip("/")
    link = f"{base}/#{action['tab']}" if action and action.get("tab") else f"{base}/"
    body = _html(title, message, level, rows, text, "{cid}" if image else None, link,
                 (action or {}).get("label") or "Open Postcrew Studio")
    return _gmail(s["gmail_address"], s["gmail_app_password"], s.get("email_to"), subject or f"Postcrew: {title}",
                  _plain(title, message, rows, text, link), html_body=body, image=image)


def notify(ws, title, message, level="info", key=None, action=None, quiet_hours=20, details=None):
    """level: info | success | warning | error. action: {"label", "tab"} shown as a button in the Studio and
    the email. details: see the module docstring."""
    items = ws.state("notifications", {"items": []})["items"]
    now = datetime.now(timezone.utc)
    if key:
        for n in items:
            if n.get("key") == key and now - datetime.fromisoformat(n["ts"]) < timedelta(hours=quiet_hours):
                return n
    n = {"id": uuid.uuid4().hex[:10], "ts": now.isoformat(timespec="seconds"), "level": level, "title": title,
         "message": message, "key": key, "action": action, "read": False,
         "rows": [list(r) for r in (details or {}).get("rows", [])]}
    items = (items + [n])[-200:]
    ws.save_state("notifications", {"items": items})
    print(f"[notify:{level}] {title}: {message}", flush=True)
    cfg = ws.config()["notifications"]
    if cfg.get("desktop"):
        _desktop(f"Postcrew: {title}", message)
    s = ws.secrets()
    if cfg.get("email") and s.get("gmail_address") and s.get("gmail_app_password"):
        err = email(ws, title, message, level, details, action)
        if err:
            n["email_error"] = err
    if cfg.get("telegram") and s.get("telegram_bot_token") and s.get("telegram_chat_id"):
        rows = "".join(f"\n{k}: {v}" for k, v in (details or {}).get("rows", []))
        err = _telegram(s["telegram_bot_token"], s["telegram_chat_id"], f"Postcrew - {title}\n{message}{rows}")
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
