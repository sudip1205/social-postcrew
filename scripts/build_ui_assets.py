#!/usr/bin/env python3
"""Build the Studio's look from the Stitch screens, so it runs offline with no CDN:

    python3 scripts/build_ui_assets.py

  postcrew/studio/static/tailwind.css   Tailwind compiled for the classes used in design/stitch/*.html and the Studio JS
  postcrew/studio/static/fonts/         Inter, Plus Jakarta Sans and only the Material Symbols icons the screens use
  postcrew/studio/static/fonts.css      @font-face rules pointing at those files

Run it after `scripts/stitch_sync.py` or after adding a class or icon to the Studio. Needs node/npm and internet (the
build only; the Studio itself never goes online). Extra icons the JS uses beyond the Stitch screens: design/icons-extra.txt.
"""
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "postcrew" / "studio" / "static"
BUILD = ROOT / "design" / ".build"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode()


def icons():
    names = set()
    for f in (ROOT / "design" / "stitch").glob("*.html"):
        names |= set(re.findall(r'material-symbols-outlined[^>]*>\s*([a-z][a-z_0-9]+)\s*<', f.read_text()))
        names |= set(re.findall(r'data-icon="([a-z][a-z_0-9]+)"', f.read_text()))
    extra = ROOT / "design" / "icons-extra.txt"
    if extra.exists():
        names |= {l.strip() for l in extra.read_text().splitlines() if l.strip() and not l.startswith("#")}
    for f in list(STATIC.glob("*.js")) + list((STATIC / "views").glob("*.js")):   # icon("name") calls in the Studio JS
        names |= set(re.findall(r'\bicon\(\s*["\']([a-z][a-z_0-9]+)["\']', f.read_text()))
    return sorted(names)


def fonts():
    (STATIC / "fonts").mkdir(parents=True, exist_ok=True)
    names = icons()
    (ROOT / "design" / "icons.txt").write_text("\n".join(names) + "\n")   # what the font contains (checked by stitch_check.py)
    families = [
        "family=Inter:wght@400;500;600;700",
        "family=Plus+Jakarta+Sans:wght@500;600;700;800",
        "family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-25..200&icon_names=" + ",".join(names),
    ]
    css_out = []
    for fam in families:
        css = fetch("https://fonts.googleapis.com/css2?" + fam + "&display=block")
        for url in sorted(set(re.findall(r"url\((https://[^)]+)\)", css))):
            name = re.sub(r"[^a-z0-9]+", "-", urllib.parse.urlparse(url).path.lower()).strip("-")[-40:] + ".woff2"
            (STATIC / "fonts" / name).write_bytes(fetch(url, binary=True))
            css = css.replace(url, f"/static/fonts/{name}")
        css_out.append(re.sub(r"/\*.*?\*/", "", css, flags=re.S).strip())
    (STATIC / "fonts.css").write_text("\n".join(css_out) + "\n")
    print(f"fonts: {len(names)} icons")


def tailwind():
    BUILD.mkdir(parents=True, exist_ok=True)
    if not (BUILD / "node_modules" / ".bin" / "tailwindcss").exists():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--prefix", str(BUILD), "tailwindcss@3.4.17",
                        "@tailwindcss/forms@0.5.9", "@tailwindcss/container-queries@0.1.1"], check=True)
    env = {"NODE_PATH": str(BUILD / "node_modules"), "PATH": __import__("os").environ["PATH"]}
    subprocess.run([str(BUILD / "node_modules" / ".bin" / "tailwindcss"), "-c", "design/tailwind.config.js",
                    "-i", "design/tailwind.input.css", "-o", str(STATIC / "tailwind.css"), "--minify"],
                   cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["fonts", "tailwind"]
    if "fonts" in steps:
        fonts()
    if "tailwind" in steps:
        tailwind()
