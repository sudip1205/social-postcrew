#!/usr/bin/env python3
"""UserPromptSubmit hook: when a prompt is about the Studio's look, remind Claude that Stitch is the source of truth, and say
if the design in Stitch has changed since design/stitch was saved (checked at most every 10 minutes)."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STAMP = ROOT / "design" / ".build" / "last_stitch_check"
UI_WORDS = re.compile(r"\b(ui|ux|studio|screen|design|stitch|layout|style|styling|colou?r|icon|tab|page|dashboard|overview|queue|plan|workflow|"
                      r"settings|credentials|button|chip|badge|font|theme|tooltip|modal|dialog|tailwind)\b", re.I)


def stitch_changes():
    if STAMP.exists() and time.time() - STAMP.stat().st_mtime < 600:
        return ""
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.touch()
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "stitch_sync.py"), "--check"], capture_output=True, text=True,
                           timeout=12)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return r.stdout.strip() if r.returncode == 1 else ""


def main():
    try:
        prompt = json.load(sys.stdin).get("prompt", "")
    except ValueError:
        return 0
    if not UI_WORDS.search(prompt):
        return 0
    notes = ["The Postcrew Studio UI follows the Stitch design (project 12643280043223938531), saved in design/stitch/ "
             "(<screen>.html is the markup, <screen>.png the picture, design.md the rules). Do not diverge from it: load the "
             "stitch-ui skill before changing any screen, copy the markup and Tailwind classes from the matching screen, and "
             "build icons, chips and badges with the helpers in postcrew/studio/static/ui.js. If the design itself should change, "
             "change it in Stitch first, then run /stitch-sync."]
    changed = stitch_changes()
    if changed:
        notes.append(f"STITCH HAS CHANGED: {changed}. Run /stitch-sync, then update the matching Studio view to the new design "
                     "before doing anything else on that screen.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(notes)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
