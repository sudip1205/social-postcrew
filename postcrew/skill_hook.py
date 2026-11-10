"""Claude Code hook that lets the Factory chat edit the skill the moment it is told to (run by `claude -p` on Edit/Write/MultiEdit).

Claude Code never lets a session write inside .claude/, even with edits allowed, so the chat's edits to
<root>/.claude/skills/<name>/<file> were refused and the owner's rules got lost. This hook redirects such a write to the
working copy <root>/skill-edit/<name>/<file> (pre), then copies the finished file into the skill straight away (post), so
the skill on disk changes in real time and the next step of the same turn already reads the new rule.

    python3 skill_hook.py pre|post <root>      (hook JSON on stdin; root = the folder that holds .claude/ and shorts-factory/)
"""
import json
import os
import shutil
import sys
from pathlib import Path

EDIT_DIR = "skill-edit"
TOOLS = ("Edit", "Write", "MultiEdit")


def locate(path, root):
    """(real file, working-copy file) for a path inside a skill or its working copy; None for anything else."""
    root = Path(os.path.realpath(root))
    skills, work = root / ".claude" / "skills", root / EDIT_DIR
    p = Path(os.path.realpath(path))
    for base in (skills, work):
        try:
            rel = p.relative_to(base)
        except ValueError:
            continue
        if len(rel.parts) < 2 or ".." in rel.parts or any(x.startswith(".") for x in rel.parts):
            return None
        return skills / rel, work / rel
    return None


def pre(event, root):
    inp = event.get("tool_input") or {}
    path = inp.get("file_path")
    if event.get("tool_name") not in TOOLS or not path:
        return None
    hit = locate(Path(event.get("cwd") or root, path), root)
    if not hit:
        return None
    real, work = hit
    if work == Path(os.path.realpath(Path(event.get("cwd") or root, path))):
        return None   # already the working copy: nothing to redirect (post still copies it)
    work.parent.mkdir(parents=True, exist_ok=True)
    if real.is_file() and (not work.exists() or work.read_bytes() != real.read_bytes()):
        shutil.copyfile(real, work)   # edit the skill's current text, never a stale copy
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "permissionDecisionReason": "skill edit (saved into the skill by the Studio)",
                                   "updatedInput": dict(inp, file_path=str(work))}}


def post(event, root):
    inp = event.get("tool_input") or {}
    path = inp.get("file_path")
    if event.get("tool_name") not in TOOLS or not path:
        return None
    hit = locate(Path(event.get("cwd") or root, path), root)
    if not hit:
        return None
    real, work = hit
    if work.is_file() and not work.is_symlink():
        real.parent.mkdir(parents=True, exist_ok=True)
        if not real.exists() or real.read_bytes() != work.read_bytes():
            shutil.copyfile(work, real)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                       "additionalContext": f"Saved into the skill: {real}"}}
    return None


def main():
    mode, root = sys.argv[1], sys.argv[2]
    try:
        event = json.load(sys.stdin)
        out = (pre if mode == "pre" else post)(event, root)
    except Exception as e:   # a broken hook must never block the chat: fall back to Claude Code's own rules
        print(f"skill hook: {type(e).__name__}: {e}", file=sys.stderr)
        return
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
