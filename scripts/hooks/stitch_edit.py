#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write|MultiEdit): after a Studio UI file is edited, check it still follows the Stitch design
(scripts/stitch_check.py --fix rebuilds tailwind.css when a new class was used). Problems go back to Claude (exit 2)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STATIC = ROOT / "postcrew" / "studio" / "static"


def main():
    try:
        path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    except ValueError:
        return 0
    p = Path(path).resolve()
    if not (p.is_relative_to(STATIC) and p.suffix in (".js", ".html")):
        return 0
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "stitch_check.py"), "--fix", str(p)], capture_output=True, text=True,
                       timeout=120)
    if r.returncode:
        print(r.stderr.strip() or r.stdout.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
