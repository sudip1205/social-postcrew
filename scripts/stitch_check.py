#!/usr/bin/env python3
"""Does the Studio UI still follow the Stitch design? Static checks on the files in postcrew/studio/static.

    python3 scripts/stitch_check.py [--fix] [file ...]      # default: every Studio UI file

Exit 1 with a list of problems when a file strays from design/stitch:
  - an emoji used as an icon (icons are Material Symbols: icon("name"))
  - a class from the old pre-Stitch stylesheet (it is gone: use the Tailwind classes the Stitch screens use)
  - an icon("name") that is not in the vendored font (add it to design/icons-extra.txt, run scripts/build_ui_assets.py)
  - a Tailwind class the compiled tailwind.css does not contain (--fix rebuilds it, then re-checks)
  - a hard-coded hex colour in a view (use the Tailwind palette; brand colours live in ui.js)
Used by the PostToolUse hook in .claude/settings.json after every edit to a Studio UI file.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "postcrew" / "studio" / "static"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆⏰✅❌]")
LEGACY = {"panel", "stat", "chip", "btn", "row", "spacer", "cards", "savebar", "orb", "muted", "empty", "banner", "primary", "sub", "mono"}
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
HEX_OK = {"ui.js", "app.js"}    # brand colours (LinkedIn, YouTube) and the agent team gradients live here
ICON = re.compile(r'\bicon\(\s*["\']([a-z][a-z_0-9]+)["\']')


def ui_files(args):
    if args:
        return [Path(a).resolve() for a in args if Path(a).resolve().is_relative_to(STATIC)
                and Path(a).suffix in (".js", ".html") and "fonts" not in Path(a).parts]
    return sorted(STATIC.glob("*.js")) + sorted((STATIC / "views").glob("*.js")) + [STATIC / "index.html"]


def css_has(css, cls):
    esc = re.sub(r"([^a-zA-Z0-9_-])", r"\\\1", cls)
    if esc[:1].isdigit():   # CSS writes a leading digit as a hex escape: 2xl:grid-cols-7 -> .\32xl\:grid-cols-7
        esc = "\\3" + esc[0] + " " + esc[1:] if esc[1:2] in " ,{" else "\\3" + esc
    return "." + esc in css


def classes_in(text):
    """Class tokens written literally in class="..." (tokens with a ${...} part are built at run time: skipped)."""
    out = set()
    for m in re.finditer(r'class="([^"]*)"', text):
        value = re.sub(r"\$\{[^}]*\}", " ", m.group(1))
        out |= {t for t in value.split() if re.fullmatch(r"[a-z0-9:\[\]#/_.%()!-]+", t) and not t.endswith("-") and not t.startswith("-")}
    return out


def check(files):
    css = "".join((STATIC / n).read_text() for n in ("tailwind.css", "studio.css") if (STATIC / n).exists())
    icons = set((ROOT / "design" / "icons.txt").read_text().split()) if (ROOT / "design" / "icons.txt").exists() else None
    if icons is not None and (ROOT / "design" / "icons-extra.txt").exists():   # listed, font rebuilt by build_ui_assets.py
        icons |= {l.strip() for l in (ROOT / "design" / "icons-extra.txt").read_text().splitlines() if l.strip() and not l.startswith("#")}
    problems, missing_css = [], False
    for f in files:
        if not f.exists():
            continue
        text, rel = f.read_text(), f.relative_to(ROOT)
        for i, line in enumerate(text.splitlines(), 1):
            if EMOJI.search(line) and not line.lstrip().startswith(("//", "/*", "*")):
                problems.append(f"{rel}:{i}: emoji used as an icon: use icon(\"name\") (Material Symbols)")
            if any(t in LEGACY for t in classes_in(line)):
                problems.append(f"{rel}:{i}: class from the old stylesheet: use the Tailwind classes of the Stitch screen")
            if f.name not in HEX_OK and f.suffix == ".js" and HEX.search(line) and not line.lstrip().startswith("//"):
                problems.append(f"{rel}:{i}: hard-coded colour: use a Tailwind palette class (brand colours live in ui.js)")
        if icons is not None:
            for name in sorted(set(ICON.findall(text)) - icons):
                problems.append(f"{rel}: icon \"{name}\" is not in the vendored font: add it to design/icons-extra.txt and run "
                                f"python3 scripts/build_ui_assets.py fonts")
        for cls in sorted(c for c in classes_in(text) if not css_has(css, c)):
            missing_css = True
            problems.append(f"{rel}: class \"{cls}\" is not in tailwind.css: run python3 scripts/build_ui_assets.py tailwind")
    return problems, missing_css


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = ui_files(args)
    problems, missing_css = check(files)
    if "--fix" in sys.argv and missing_css:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_ui_assets.py"), "tailwind"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        problems, _ = check(files)
    if problems:
        print("Studio UI strays from the Stitch design (design/stitch, see the stitch-ui skill):\n  " + "\n  ".join(problems[:40]),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
