#!/usr/bin/env python3
"""PreToolUse hook (Edit|Write): the design files and the compiled UI assets are generated, never edited by hand."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GENERATED = {
    "postcrew/studio/static/tailwind.css": "run python3 scripts/build_ui_assets.py tailwind",
    "postcrew/studio/static/fonts.css": "run python3 scripts/build_ui_assets.py fonts",
}


def main():
    try:
        path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    except ValueError:
        return 0
    try:
        rel = str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return 0
    why = GENERATED.get(rel) or ("it is saved from Stitch: change the design in Stitch, then run /stitch-sync"
                                 if rel.startswith("design/stitch/") else None)
    if rel.startswith("postcrew/studio/static/fonts/"):
        why = "run python3 scripts/build_ui_assets.py fonts"
    if why:
        print(f"{rel} is generated: don't edit it by hand ({why}).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
