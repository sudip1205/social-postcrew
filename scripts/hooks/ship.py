#!/usr/bin/env python3
"""Stop hook: after each finished change, test it, commit it, push it and update the AI lab.

    python3 scripts/hooks/ship.py            # what the hook runs (reads the hook's JSON on stdin, if any)
    python3 scripts/hooks/ship.py --dry-run  # say what it would do, change nothing

Steps (each one stops the chain if it fails; nothing is committed on a failure):
  1. nothing changed and the lab is already on this commit -> do nothing.
  2. refuse to commit anything that looks like a secret or a big media file.
  3. run the tests (python3 -m unittest discover -s tests) and the UI style check. A failure is sent back to Claude (exit 2) with the last lines.
  4. commit (the message comes from the first new CHANGELOG line), push origin main.
  5. update the lab (`postcrew-lab update`), unless a crew run is in progress there: the update restarts the server and would kill a video
     that is being made. That deploy is simply done after the next change instead (step 1 notices the lab is behind).

The lab address is $POSTCREW_LAB (default sudip@192.168.1.174). Output: a JSON {"systemMessage": ...} on stdout so the summary is shown.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
LAB = os.environ.get("POSTCREW_LAB", "sudip@192.168.1.174")
TRAILER = "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
SECRETISH = re.compile(r"(^|/)(secrets[^/]*\.json|\.env[^/]*|studio-token|[^/]*\.pem|[^/]*\.key|id_rsa[^/]*)$")
BIG = 5_000_000   # bytes: no videos or large binaries in git


def run(cmd, timeout=120, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, **kw)


def git(*args, timeout=120):
    return run(["git", *args], timeout)


def say(msg, code=0):
    print(json.dumps({"systemMessage": msg}))
    sys.exit(code)


def block(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def ssh(script, timeout=60):
    return run(["ssh", "-n", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", LAB, script], timeout)


def lab_head():
    r = ssh("cd ~/postcrew && git rev-parse HEAD", 30)
    return r.stdout.strip() if r.returncode == 0 else None


def lab_busy():
    """True while a crew run or a plan generation is in progress on the lab (the update restarts the server: it would kill it)."""
    r = ssh('T=$(cat ~/postcrew/workspace/studio-token 2>/dev/null); curl -s -m 8 -H "Cookie: postcrew_token=$T" -H "X-Postcrew: 1" '
            'localhost:8765/api/overview', 30)
    try:
        d = json.loads(r.stdout)
        if d.get("running") or d.get("planning"):
            return True
    except ValueError:
        pass   # the server does not answer (stopped): nothing to protect
    # a server that is older than the "planning" flag: the planner's own log shows a generation that started and has not finished
    p = ssh('f=$(ls -dt ~/postcrew/workspace/plans/*/ 2>/dev/null | head -1); [ -n "$f" ] && find "$f" -name events.jsonl -mmin -3 | grep -q . '
            '&& ! grep -q "\\"kind\\": \\"finished\\"" "$f/events.jsonl" && echo PLANNING', 30)
    return "PLANNING" in p.stdout


def subject(files):
    """The commit subject: the first new bullet of CHANGELOG.md (its bold lead-in), else the areas that changed."""
    d = git("diff", "HEAD", "--", "CHANGELOG.md").stdout
    for line in d.splitlines():
        m = re.match(r"^\+- \*\*(.+?)\*\*", line)
        if m:
            return m.group(1).rstrip(".")[:72]
    areas = sorted({f.split("/")[0] if "/" in f else f for f in files})
    return f"Update {', '.join(areas[:4])}"[:72]


def main():
    dry = "--dry-run" in sys.argv
    try:
        hook = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
    except ValueError:
        hook = {}
    lock = open("/tmp/postcrew-ship.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        say("ship: another ship is running; skipped")
    if git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "main":
        say("ship: not on main; nothing shipped")
    status = [l for l in git("status", "--porcelain").stdout.splitlines() if l.strip()]
    files = [l[3:].split(" -> ")[-1].strip('"') for l in status]
    notes, committed = [], False
    if files:
        bad = [f for f in files if SECRETISH.search(f) or ((ROOT / f).is_file() and (ROOT / f).stat().st_size > BIG)]
        if bad:
            block("ship: NOT committed. These look like secrets or large files: " + ", ".join(bad) + ". Add them to .gitignore or remove them.")
        if dry:
            say(f"ship (dry run): would test, commit {len(files)} file(s), push and update the lab")
        t = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 1100)
        tail = "\n".join((t.stdout + t.stderr).strip().splitlines()[-25:])
        if t.returncode != 0:
            msg = "ship: the tests FAIL, so nothing was committed or deployed. Fix them:\n" + tail
            if hook.get("stop_hook_active"):   # already sent back once: do not trap the session in a loop
                say(msg, 0)
            block(msg)
        s = run([sys.executable, "scripts/stitch_check.py"], 120)
        if s.returncode != 0:
            msg = "ship: the UI style check fails, so nothing was committed:\n" + (s.stdout + s.stderr).strip()[-1500:]
            if hook.get("stop_hook_active"):
                say(msg, 0)
            block(msg)
        git("add", "-A")
        subj = subject(files)
        body = "\n".join(f"- {f}" for f in files[:25]) + ("\n- ..." if len(files) > 25 else "")
        c = git("commit", "-m", f"{subj}\n\n{body}\n\n{TRAILER}")
        if c.returncode != 0:
            block("ship: git commit failed:\n" + (c.stdout + c.stderr)[-1500:])
        committed = True
        notes.append(f"committed '{subj}' ({len(files)} files; tests passed)")
    ahead = git("rev-list", "--count", "origin/main..HEAD").stdout.strip()
    if ahead not in ("", "0"):
        p = git("push", "origin", "main", timeout=180)
        if p.returncode != 0:
            block("ship: the commit is saved but git push failed:\n" + (p.stdout + p.stderr)[-1500:])
        notes.append("pushed to GitHub")
    head = git("rev-parse", "HEAD").stdout.strip()
    if not committed and ahead in ("", "0") and not files:
        if lab_head() in (None, head):
            sys.exit(0)   # nothing changed and the lab is current (or unreachable): stay quiet
    if lab_head() == head:
        say("ship: " + "; ".join(notes + ["the lab is already up to date"]))
    if lab_busy():
        say("ship: " + "; ".join(notes + ["the lab was NOT updated: a crew run or a plan generation is in progress there (the update restarts the server). It updates after the next change"]))
    u = ssh("~/.local/bin/postcrew-lab update 2>&1 | tail -4", 400)
    if "updated" not in u.stdout and "up to date" not in u.stdout:
        say("ship: " + "; ".join(notes) + f"; the lab update FAILED: {(u.stdout + u.stderr).strip()[-400:]}", 0)
    ok = ssh("cd ~/postcrew && POSTCREW_HOME=$PWD/workspace .venv/bin/python -m postcrew doctor 2>&1 | grep -i 'Settings'", 60).stdout.strip()
    say("ship: " + "; ".join(notes + [f"lab updated to {head[:7]} ({ok or 'settings not checked'})"]))


if __name__ == "__main__":
    main()
