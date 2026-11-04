"""Comment emails: LinkedIn emails you "X commented on your post", with the comment and a link to it. LinkedIn's API does not let an
app read the comments on a personal profile's posts (r_member_social is closed), so the Replier reads those emails instead.

Any mailbox with IMAP works. iCloud Mail: server imap.mail.me.com, your iCloud address, and an app-specific password
(account.apple.com > Sign-In and Security > App-Specific Passwords). Gmail: imap.gmail.com and an App Password.
The inbox is opened read-only: nothing is marked read, moved or deleted. Only mail from linkedin.com about comments is looked at.

Secrets (workspace/secrets.json): comments_mail_address, comments_mail_password, comments_mail_server (optional: worked out from the
address).
"""
import email
import email.policy
import html
import imaplib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

SERVERS = {"icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com",
           "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
           "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com",
           "yahoo.com": "imap.mail.yahoo.com"}
# what a LinkedIn notification about a comment says in its subject
COMMENT_SUBJECT = re.compile(r"(commented on|replied to|mentioned you in a comment|replied on|comment(?:ed)? on your)", re.I)
NOT_MINE = re.compile(r"commented on (?:a post|.{0,60}'s post|this post|a post you)", re.I)   # someone else's post you follow
COMMENT_URN = re.compile(r"urn:li:comment:\((?:urn:li:)?(activity|ugcPost|share):(\d+),(\d+)\)")
THREAD_URN = re.compile(r"urn:li:(activity|ugcPost|share):(\d+)")


class MailError(RuntimeError):
    pass


def settings(secrets):
    addr = (secrets.get("comments_mail_address") or "").strip()
    pw = (secrets.get("comments_mail_password") or "").strip()
    if not (addr and pw):
        return None
    server = (secrets.get("comments_mail_server") or "").strip() or SERVERS.get(addr.rsplit("@", 1)[-1].lower(), "")
    if not server:
        raise MailError(f"No IMAP server known for {addr}: set the mail server in Credentials (for a custom domain on iCloud: "
                        "imap.mail.me.com).")
    return {"address": addr, "password": pw, "server": server}


def connect(cfg, imap=imaplib.IMAP4_SSL):
    try:
        box = imap(cfg["server"], 993, timeout=60)
        box.login(cfg["address"], cfg["password"])
    except (imaplib.IMAP4.error, OSError) as e:
        hint = (" iCloud needs an app-specific password (account.apple.com > Sign-In and Security > App-Specific Passwords), not your "
                "Apple ID password." if "mail.me.com" in cfg["server"] else " Use an app password, not your normal password.")
        raise MailError(f"Could not sign in to {cfg['server']} as {cfg['address']}: {e}.{hint}")
    return box


def test(secrets, imap=imaplib.IMAP4_SSL):
    """Sign in and count the LinkedIn mails of the last 14 days. Reads nothing else."""
    cfg = settings(secrets)
    if not cfg:
        return {"ok": False, "message": "Add the email address and its app password first."}
    box = connect(cfg, imap)
    try:
        uids = _search(box, datetime.now(timezone.utc) - timedelta(days=14))
    finally:
        _close(box)
    return {"ok": True, "message": f"Signed in to {cfg['server']}: {len(uids)} email{'s' if len(uids) != 1 else ''} from LinkedIn in the "
                                   "last 14 days."}


def _search(box, since):
    typ, _ = box.select("INBOX", readonly=True)
    if typ != "OK":
        raise MailError("could not open the inbox")
    typ, data = box.uid("SEARCH", None, "SINCE", since.strftime("%d-%b-%Y"), "FROM", '"linkedin.com"')
    if typ != "OK":
        raise MailError("the mail server refused the search")
    return (data[0] or b"").split()


def _close(box):
    try:
        box.logout()
    except Exception:
        pass


def fetch(secrets, since, seen=(), imap=imaplib.IMAP4_SSL, limit=200):
    """The LinkedIn comment notifications since `since`, minus the message ids in `seen`: [parsed comment, ...] (see parse)."""
    cfg = settings(secrets)
    if not cfg:
        return []
    box = connect(cfg, imap)
    out = []
    try:
        for uid in _search(box, since)[-limit:]:
            typ, data = box.uid("FETCH", uid, "(BODY.PEEK[])")   # PEEK: never marks it read
            raw = next((part[1] for part in data or [] if isinstance(part, tuple)), None)
            if typ != "OK" or not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            mid = (msg.get("Message-ID") or f"uid-{uid.decode()}").strip()
            if mid in seen:
                continue
            c = parse(msg)
            if c:
                out.append({**c, "message_id": mid})
    finally:
        _close(box)
    return out


def _text(msg):
    """The mail's readable text (the plain part, else the HTML part without tags) and every link in it."""
    plain = htm = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain" and not plain:
            plain = part.get_content()
        elif ct == "text/html" and not htm:
            htm = part.get_content()
    links = re.findall(r"https?://[^\s\"'<>)]+", (plain or "") + " " + (htm or ""))
    if not plain and htm:
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", htm)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
        plain = html.unescape(re.sub(r"<[^>]+>", " ", t))
    plain = re.sub(r"[ \t ‌]+", " ", plain)
    plain = re.sub(r"\n\s*\n+", "\n\n", plain).strip()
    return plain, links


def _decode(link):
    for _ in range(3):   # LinkedIn's tracking links wrap the real one, encoded once or twice
        link = urllib.parse.unquote(html.unescape(link))
    return link


def parse(msg):
    """One LinkedIn email -> {"author", "subject", "thread_urn", "comment_urn", "body", "at"} for a comment on your post (or a reply to
    your comment); None for anything else."""
    if "linkedin.com" not in (msg.get("From") or "").lower():
        return None
    subject = str(msg.get("Subject") or "")
    if not COMMENT_SUBJECT.search(subject) or NOT_MINE.search(subject):
        return None
    body, links = _text(msg)
    comment = thread = None
    for link in map(_decode, links):
        m = COMMENT_URN.search(link)
        if m:
            kind, post_id, cid = m.groups()
            comment = f"urn:li:comment:(urn:li:{kind}:{post_id},{cid})"
            thread = f"urn:li:{kind}:{post_id}"
            break
        if not thread:
            t = THREAD_URN.search(link)
            if t:
                thread = t.group(0)
    try:
        at = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        at = datetime.now(timezone.utc)
    m = re.match(r"\s*(.+?)\s+(?:commented|replied|mentioned)", subject)
    return {"author": m.group(1).strip()[:80] if m else "", "subject": subject[:200], "thread_urn": thread, "comment_urn": comment,
            "body": _strip_footer(body)[:4000], "at": at.isoformat(timespec="seconds")}


def _strip_footer(text):
    """Cut LinkedIn's footer (unsubscribe, address, help) so the Replier reads the comment, not the boilerplate."""
    for marker in ("This email was intended for", "You are receiving LinkedIn notification emails", "Unsubscribe", "© 20",
                   "Learn why we included this"):
        i = text.find(marker)
        if i > 200:
            text = text[:i]
    return text.strip()
