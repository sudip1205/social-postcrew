#!/usr/bin/env python3
"""Pull the Postcrew Studio design from Stitch into design/stitch/ (the source of truth for the Studio UI).

    python3 scripts/stitch_sync.py            # download every visible screen (HTML + screenshot) and the design system
    python3 scripts/stitch_sync.py --check    # exit 1 if Stitch differs from the saved copy (used by the hook)

Needs a Stitch API key: $STITCH_API_KEY, or the `stitch` MCP server's X-Goog-Api-Key in ~/.claude.json.
Writes design/stitch/<slug>.html, <slug>.png, design.md and manifest.json (screen id, title, update hash).
"""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

PROJECT = "12643280043223938531"
API = "https://stitch.googleapis.com/v1"
OUT = Path(__file__).resolve().parent.parent / "design" / "stitch"


def api_key():
    key = os.environ.get("STITCH_API_KEY")
    if key:
        return key
    try:
        cfg = json.loads((Path.home() / ".claude.json").read_text())
        return cfg["mcpServers"]["stitch"]["headers"]["X-Goog-Api-Key"]
    except (OSError, KeyError, ValueError):
        sys.exit("No Stitch API key: set STITCH_API_KEY or add the stitch MCP server (claude mcp add stitch ...).")


def get(path, key):
    req = urllib.request.Request(f"{API}/{path}", headers={"X-Goog-Api-Key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def file_bytes(ref, key):
    """A file entry's content: Stitch wraps it as {dataString} (text; base64 for images) or {data} (base64)."""
    path = ref["downloadUrl"].split("/v1/", 1)[1]
    w = get(path, key)
    if "dataString" in w:
        if ref.get("mimeType", "").startswith("image/"):
            return base64.b64decode(w["dataString"])
        return w["dataString"].encode()
    for k in ("data", "bytes", "content"):
        if k in w:
            return base64.b64decode(w[k])
    raise SystemExit(f"unexpected file format for {ref.get('name')}: {list(w)}")


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def main():
    check = "--check" in sys.argv
    key = api_key()
    project = get(f"projects/{PROJECT}", key)
    visible = {s["id"] for s in project.get("screenInstances", []) if not s.get("hidden")}
    screens = [s for s in get(f"projects/{PROJECT}/screens", key).get("screens", [])
               if s["name"].rsplit("/", 1)[1] in visible]
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, changed = {}, []
    for s in screens:
        sid, name = s["name"].rsplit("/", 1)[1], slug(s["title"])
        html = file_bytes(s["htmlCode"], key)
        digest = hashlib.sha256(html).hexdigest()[:16]
        manifest[name] = {"id": sid, "title": s["title"], "sha": digest}
        old = OUT / f"{name}.html"
        if not old.exists() or hashlib.sha256(old.read_bytes()).hexdigest()[:16] != digest:
            changed.append(name)
        if not check:
            old.write_bytes(html)
            if s.get("screenshot"):
                (OUT / f"{name}.png").write_bytes(file_bytes(s["screenshot"], key))
    if not check:
        (OUT / "design.md").write_text((project.get("designTheme") or {}).get("designMd", ""))
        (OUT / "manifest.json").write_text(json.dumps({"project": PROJECT, "screens": manifest}, indent=2) + "\n")
        print(f"synced {len(screens)} screen(s) to {OUT}" + (f"; changed: {', '.join(changed)}" if changed else ""))
        return 0
    if changed:
        print("Stitch design changed since the saved copy: " + ", ".join(changed))
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
