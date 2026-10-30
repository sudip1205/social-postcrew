"""Tidying the workspace: delete what is old so the disk does not fill up with finished videos, frames and run files.

Every day (when `postcrew serve` runs; time and age in the `cleanup` settings) everything older than `keep_days` (30) is deleted:
the run folders (logs, scripts, frames, videos), the planner's logs, the voice cache, the day briefs, the videos and pictures kept in
media/ and old config backups. A run, a video or a picture that a post still in the Queue uses is never deleted, whatever its age.

What is NEVER deleted: config.json, secrets.json, the access token, history.json and queue.json (the history is how Postcrew knows what it
has already published), and state/ (the plan, the lessons the crew has learned, the scheduler's memory).

`python3 -m postcrew clean --dry-run` shows what would go; `--videos` also clears every finished video, frames and voice recording at
once (the one-off "delete my old videos"), whatever their age.
"""
import json
import shutil
import time
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aiff", ".aif", ".ogg"}
KEEP_FILES = {"config.json", "secrets.json", "history.json", "queue.json", "studio-token"}
KEEP_DIRS = {"state"}
DAY = 86400


def _size(path):
    path = Path(path)
    if path.is_symlink() or path.is_file():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def _newest(path):
    """When a file, or anything inside a folder, last changed."""
    path = Path(path)
    try:
        if path.is_dir() and not path.is_symlink():   # the files inside say how old a folder is, not the folder's own date
            times = [f.lstat().st_mtime for f in path.rglob("*") if f.is_file()]
            return max(times) if times else path.lstat().st_mtime
        return path.lstat().st_mtime
    except OSError:
        return time.time()


def _protected(ws):
    """Names (files and run ids) that a post still in the Queue uses."""
    files, runs = set(), set()
    for p in ws.queue():
        for key in ("media", "poster_image"):
            if p.get(key):
                files.add(str((ws.root / p[key]).resolve()))
        if p.get("run_id"):
            runs.add(p["run_id"])
    return files, runs


def _remove(path, root, dry_run):
    """Delete a file or folder (never outside the workspace, never through a link). Returns the bytes freed."""
    path = Path(path)
    if root.resolve() not in path.resolve().parents and not path.is_symlink():
        return 0
    freed = _size(path)
    if dry_run:
        return freed
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    except OSError:
        return 0
    return freed


def clean(ws, keep_days=30, dry_run=False, now=None, videos=False):
    """Delete what is older than keep_days (and, with videos=True, every finished video, frames folder and voice recording).
    Returns {"removed": files and folders, "freed_mb", "areas": {name: count}, "dry_run", "videos"}."""
    root = ws.root.resolve()
    cutoff = (now or time.time()) - keep_days * DAY
    keep_files, keep_runs = _protected(ws)
    removed, freed, areas = [], 0, {}

    def drop(path, area):
        nonlocal freed
        if str(Path(path).resolve()) in keep_files:
            return
        n = _remove(path, root, dry_run)
        if n or dry_run:
            freed += n
            removed.append(str(Path(path).relative_to(root)))
            areas[area] = areas.get(area, 0) + 1

    # old things, whatever they are: run folders, planner logs, caches, briefs, pictures and videos kept in media/, config backups
    for name, kind in (("runs", "runs"), ("plans", "plans")):
        for d in sorted((root / name).glob("*")) if (root / name).is_dir() else []:
            if d.is_dir() and d.name not in keep_runs and _newest(d) < cutoff:
                drop(d, kind)
    for name in ("media", "cache", "briefs"):
        base = root / name
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file() and f.lstat().st_mtime < cutoff:
                    drop(f, name)
    for f in sorted(root.glob("config.backup-*.json")):
        if f.lstat().st_mtime < cutoff:
            drop(f, "backups")
    for f in sorted(root.glob("*")):   # a video left in the workspace folder itself
        if f.is_file() and f.suffix.lower() in VIDEO_EXT and f.lstat().st_mtime < cutoff:
            drop(f, "videos")

    if videos:   # the one-off: every finished video, frames folder and voice recording, whatever their age
        for f in sorted(root.rglob("*")):
            rel = f.relative_to(root).parts
            if rel[0] in KEEP_DIRS or f.name in KEEP_FILES or not f.exists():
                continue
            if f.is_file() and f.suffix.lower() in VIDEO_EXT | AUDIO_EXT and not (rel[0] == "cache" and f.suffix.lower() == ".mp3"):
                if rel[0] == "runs" and len(rel) > 1 and rel[1] in keep_runs:
                    continue
                drop(f, "videos")
        for d in sorted(root.glob("runs/*/frames*")) + sorted(root.glob("demo-*")):
            if d.is_dir() and not (d.parent.name in keep_runs):
                drop(d, "frames")

    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):   # folders left empty
        if not dry_run and len(d.relative_to(root).parts) >= 2 and d.relative_to(root).parts[0] not in KEEP_DIRS:   # never the top folders
            try:
                d.rmdir()
            except OSError:
                pass
    result = {"removed": len(removed), "freed_mb": round(freed / 1e6, 1), "areas": areas, "dry_run": dry_run, "videos": videos,
              "keep_days": keep_days, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not dry_run:
        ws.save_state("cleanup", result)
    if dry_run:
        result["examples"] = removed[:12]
    return result


def run_cleanup(ws):
    """The scheduler's daily job (settings: cleanup.enabled, cleanup.keep_days)."""
    cfg = ws.config().get("cleanup") or {}
    if not cfg.get("enabled", True):
        return None
    return clean(ws, keep_days=int(cfg.get("keep_days", 30)))
