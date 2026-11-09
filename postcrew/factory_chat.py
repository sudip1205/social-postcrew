"""Factory chat: talk to Claude Code inside the Shorts factory's workspace (~/Youtube), like the desktop Claude Code app.

Give it a topic ("make a Short about Python's GIL") and it writes the episode and renders it; give it an instruction for every video
("captions one line higher", "slower voice") and it changes the skill, as the factory's CLAUDE.md tells it to. The conversation carries
on from message to message (claude --resume) until you start a new one. One message at a time; the answer streams into
state/factory-chat.json, which the Studio's Factory page polls.
"""
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import factory_refs
from .agents.shorts import SKILL_RULE, factory_dir, skill_version

STATE = "factory-chat"
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "Skill",
         "Bash(npm run make:*)", "Bash(npm run tts:*)", "Bash(npm run voices:*)", "Bash(ls:*)", "Bash(ffprobe:*)", "Bash(ffmpeg:*)", "Bash(cat:*)"]
SYSTEM = ("You are working for the channel owner through the postcrew Studio's Factory page (a chat, like the Claude Code app). "
          "Follow CLAUDE.md and the explainer-short-style skill. A topic means: write the episode (script.json and youtube.json, privacyStatus "
          "\"private\") and render it with `npm run make -- episodes/<slug>` from shorts-factory/. An instruction about how videos should look, "
          "sound or be written from now on means: apply it and write it into the skill (CLAUDE.md's standing rule), then say which skill files "
          "changed. Never upload to YouTube yourself: the owner queues finished videos from the Studio. Keep replies short. "
          "When making a video: " + SKILL_RULE)
PLAN_SLUG = re.compile(r"^plan-([a-z0-9]{6,32})-")
MAX_MESSAGES = 200
_lock = threading.Lock()
_busy = threading.Event()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(ws):
    return ws.state(STATE, {"session_id": None, "messages": []})


def _save(ws, st):
    st["messages"] = st["messages"][-MAX_MESSAGES:]
    ws.save_state(STATE, st)


def _add(ws, msg):
    with _lock:
        st = load(ws)
        st["messages"].append(dict(msg, ts=_now()))
        _save(ws, st)


def _tool_line(block):
    """A short line for a tool the model used: 'Edit SKILL.md', 'npm run make -- episodes/x'."""
    name, inp = block.get("name", ""), block.get("input") or {}
    if name == "Bash":
        return f"$ {str(inp.get('command', ''))[:160]}"
    path = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("query") or inp.get("url") or ""
    return f"{name} {Path(str(path)).name if inp.get('file_path') else str(path)[:120]}".strip()


def busy():
    return _busy.is_set()


def view(ws):
    root = factory_dir(_cfg(ws))
    st = load(ws)
    return {"messages": st["messages"], "session": bool(st.get("session_id")), "busy": busy(), "factory": str(root),
            "found": (root / "package.json").exists(), "videos": videos(ws), "skill": skill_files(ws),
            "skill_version": skill_version(root) if (root / "package.json").exists() else {}, "plans": plans(ws),
            "references": factory_refs.listing(ws)}


def plans(ws):
    """Your own YouTube plans that are not made yet (Manual run), for the Use a plan list."""
    from . import monthly
    try:
        items = monthly.unassigned(ws, "youtube")
    except Exception:
        return []
    return [{"id": i["id"], "title": i.get("title") or "", "format": i.get("format") or "short", "files": len((i.get("source") or {}).get("files") or []),
             "read": (i.get("source") or {}).get("state") or ""} for i in items if i.get("manual")]


def plan_prompt(ws, item_id):
    """The message that asks for one of your plans: your words, how you want it made, the problem read from your files, and where those
    files are on this computer (Claude opens them itself)."""
    from . import monthly, attachments
    try:
        item = monthly._item(monthly.load(ws, "youtube"), str(item_id or ""))
    except ValueError:
        raise ValueError("that plan is gone")
    slug = f"plan-{item['id']}-" + (re.sub(r"[^a-z0-9]+", "-", (item.get("title") or "short").lower()).strip("-")[:40].strip("-") or "short")
    src = item.get("source") or {}
    lines = [f"Make a YouTube {item.get('format') or 'short'} from my plan below, as episode `episodes/{slug}/` (use exactly this folder name: "
             f"it ties the video to the plan). Write script.json and youtube.json, then render it.", "", f"Title: {item.get('title', '')}"]
    for key, label in (("context", "What it is about"), ("how", "How I want it made"), ("takeaway", "What the viewer should take away"),
                       ("tone", "Tone")):
        if item.get(key):
            lines.append(f"{label}: {item[key]}")
    if item.get("references"):
        lines.append("References: " + " ".join(item["references"]))
    if src.get("statement"):
        lines += ["", "The problem, as read from my files:", attachments.statement_text(src["statement"])]
    files = src.get("files") or []
    if files:
        d = attachments.plan_dir(ws, "youtube", item["id"])
        lines += ["", "My files for it (open them):"] + [f"- {d / f['file']}" for f in files if f.get("file")]
    return {"text": "\n".join(lines), "slug": slug, "plan_id": item["id"]}


def _cfg(ws):
    from . import platforms
    return platforms.view(ws.config(), "youtube")


def videos(ws, n=24):
    """The rendered videos in out/, newest first, with the episode they came from."""
    out = factory_dir(_cfg(ws)) / "out"
    if not out.exists():
        return []
    rows = []
    for f in sorted(out.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]:
        slug = re.sub(r"-(hyperframes|remotion)$", "", f.stem)
        meta = {}
        try:
            meta = json.loads((out.parent / "episodes" / slug / "youtube.json").read_text())
        except (OSError, ValueError):
            pass
        rows.append({"file": f.name, "slug": slug, "title": meta.get("title") or slug, "mb": round(f.stat().st_size / 1e6, 1),
                     "yt_title": meta.get("title") or "", "description": meta.get("description") or "", "tags": meta.get("tags") or [],
                     "made": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                     "has_meta": bool(meta), "thumb": f.with_suffix(".jpg").name if f.with_suffix(".jpg").exists() else None})
    return rows


def skill_files(ws):
    """The skill's files and when each last changed, so a change made from the chat can be seen."""
    root = factory_dir(_cfg(ws)).parent
    skill = root / ".claude" / "skills" / "explainer-short-style"
    files = [root / "CLAUDE.md"] + ([skill / "SKILL.md"] + sorted((skill / "references").glob("*.md")) if skill.exists() else [])
    return [{"path": str(p.relative_to(root)), "changed": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
            for p in files if p.exists()]


def send(ws, text, runner=subprocess.Popen):
    """Start one turn in the background. Raises ValueError when a turn is already going or the factory is missing."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("write a message first")
    if len(text) > 8000:
        raise ValueError("that message is too long (8,000 characters at most)")
    root = factory_dir(_cfg(ws))
    if not (root / "package.json").exists():
        raise ValueError(f"the Shorts factory is not at {root}")
    if _busy.is_set():
        raise ValueError("Claude is still working on the last message: wait for it, or stop it")
    _busy.set()
    _add(ws, {"role": "user", "text": text})
    threading.Thread(target=_turn, args=(ws, text, root, runner), daemon=True, name="factory-chat").start()
    return view(ws)


_proc = {"p": None}


def stop(ws):
    p = _proc.get("p")
    if p and p.poll() is None:
        p.terminate()
        _add(ws, {"role": "system", "text": "Stopped."})
    return view(ws)


def reset(ws):
    if _busy.is_set():
        raise ValueError("wait for the current message to finish, or stop it, before starting a new chat")
    ws.save_state(STATE, {"session_id": None, "messages": []})
    return view(ws)


def _turn(ws, text, root, runner):
    cfg = ws.config()
    st = load(ws)
    binary = cfg["llm"].get("claude_path") or "claude"
    cmd = [binary, "-p", "--output-format", "stream-json", "--verbose", "--model", "sonnet", "--max-budget-usd", "5",
           "--permission-mode", "acceptEdits", "--allowedTools", ",".join(TOOLS), "--append-system-prompt", SYSTEM]
    if st.get("session_id"):
        cmd += ["--resume", st["session_id"]]
    t0 = time.time()
    try:
        p = runner(cmd, cwd=str(root.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _proc["p"] = p
        p.stdin.write(text)
        p.stdin.close()
        steps = []
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "system" and ev.get("session_id"):
                _set_session(ws, ev["session_id"])
            elif kind == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        _add(ws, {"role": "assistant", "text": b["text"].strip()})
                    elif b.get("type") == "tool_use":
                        steps.append(_tool_line(b))
                        _add(ws, {"role": "tool", "text": steps[-1]})
            elif kind == "result":
                if ev.get("session_id"):
                    _set_session(ws, ev["session_id"])
                cost = float(ev.get("total_cost_usd") or 0)
                if ev.get("is_error") or ev.get("subtype") != "success":
                    _add(ws, {"role": "error", "text": str(ev.get("result") or ev.get("subtype") or "Claude stopped")[:600]})
                _add(ws, {"role": "system", "text": f"Done in {time.time() - t0:.0f}s · ${cost:.2f} · {len(steps)} steps", "cost": cost})
        err = p.stderr.read()
        if p.wait() not in (0, None) and not any(m["role"] in ("error",) for m in load(ws)["messages"][-3:]):
            if p.returncode not in (-15,):
                _add(ws, {"role": "error", "text": (err or f"claude exited {p.returncode}").strip()[-600:]})
    except FileNotFoundError:
        _add(ws, {"role": "error", "text": f"Claude Code CLI '{binary}' not found on this computer"})
    except Exception as e:   # never leave the chat stuck as busy
        _add(ws, {"role": "error", "text": f"{type(e).__name__}: {e}"[:600]})
    finally:
        _proc["p"] = None
        _busy.clear()


def _set_session(ws, sid):
    with _lock:
        st = load(ws)
        if st.get("session_id") != sid:
            st["session_id"] = sid
            _save(ws, st)


def _rendered(ws, slug):
    """An episode's rendered files in out/ (video, thumbnail, captions)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", str(slug or "")):
        raise ValueError("unknown episode")
    out = factory_dir(_cfg(ws)) / "out"
    return [f for f in out.glob(f"{slug}*") if re.fullmatch(re.escape(slug) + r"(-(hyperframes|remotion))?\.(mp4|jpg|srt)", f.name)]


def delete_video(ws, slug):
    """Delete an episode's rendered files from out/. The episode's script stays, so it can be made again."""
    gone = _rendered(ws, slug)
    if not gone:
        raise ValueError("that video is already gone")
    for f in gone:
        f.unlink()
    return view(ws)


def _move_out(ws, slug):
    """Once queued (the Queue keeps its own copy), the episode's files go to out/queued/, so it leaves the Factory's list."""
    files = _rendered(ws, slug)
    if files:
        dest = files[0].parent / "queued"
        dest.mkdir(exist_ok=True)
        for f in files:
            f.replace(dest / f.name)


def queue_video(ws, slug, date=None, title=None, description=None, tags=None):
    """Put a video made in the chat into the YouTube Queue for `date`, like a crew run's video (approval and schedule apply). title,
    description and tags: as you checked them on the Factory page (saved back to the episode's youtube.json); else youtube.json's own."""
    day = date
    from datetime import date as date_cls
    from .agents.yt_publish import enqueue_youtube
    from . import platforms
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", str(slug or "")):
        raise ValueError("unknown episode")
    cfg = _cfg(ws)
    root = factory_dir(cfg)
    ep = root / "episodes" / slug
    try:
        meta = json.loads((ep / "youtube.json").read_text())
    except (OSError, ValueError):
        raise ValueError("this episode has no youtube.json (title, description, tags): ask Claude in the chat to write it")
    if title is not None or description is not None or tags is not None:
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        edits = {k: v for k, v in (("title", str(title or "").strip() if title is not None else None),
                                   ("description", str(description or "").strip() if description is not None else None),
                                   ("tags", [str(t).strip() for t in tags if str(t).strip()] if tags is not None else None)) if v is not None}
        meta.update(edits)
        (ep / "youtube.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    problems = []
    if not meta.get("title") or len(meta["title"]) > 100:
        problems.append("a title of 1 to 100 characters")
    if len(meta.get("description") or "") > 5000:
        problems.append("a description under 5,000 characters")
    if re.search(r"[<>]", (meta.get("title") or "") + (meta.get("description") or "")):
        problems.append("no < or > in the title or description (YouTube refuses them)")
    if sum(len(t) + (2 if " " in t else 0) for t in meta.get("tags") or []) + max(0, len(meta.get("tags") or []) - 1) > 500:
        problems.append("tags of 500 characters in all")
    if problems:
        raise ValueError("YouTube needs " + "; ".join(problems))
    video = next((root / "out" / f"{slug}-{e}.mp4" for e in ("hyperframes", "remotion") if (root / "out" / f"{slug}-{e}.mp4").exists()), None)
    if not video:
        raise ValueError("this episode has no rendered video yet")
    try:
        day = date_cls.fromisoformat(str(day))
    except ValueError:
        raise ValueError("pick the date to publish it")
    secs = 0.0
    try:
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                    capture_output=True, text=True, timeout=60).stdout.strip())
    except (ValueError, OSError):
        pass
    category = platforms.category_for(cfg["schedule"], day) or next(iter(cfg["categories"]), "short")
    m = PLAN_SLUG.match(slug)
    plan_id = m.group(1) if m else None
    outputs = {"writer": {"slug": slug, "title": meta.get("title") or slug, "description": meta.get("description", ""), "tags": meta.get("tags") or []},
               "media": {"path": str(video), "thumbnail_path": str(video.with_suffix(".jpg")) if video.with_suffix(".jpg").exists() else "",
                         "seconds": round(secs, 1), "engine": video.stem.rsplit("-", 1)[-1]}}
    post = enqueue_youtube(ws, cfg, f"factory-chat-{slug}", day, category, outputs, {})
    if plan_id:   # made from one of your plans: the plan counts as made (it leaves Manual run) once its video is queued
        post["plan_id"] = plan_id
        ws.save_queue([post if p["id"] == post["id"] else p for p in ws.queue()])
    _move_out(ws, slug)
    return {"post": post, **view(ws)}


def teach(ws, ids, note="", runner=subprocess.Popen):
    """Send the chat one or more reference videos' lesson (frames and your comments), so Claude writes it (or their shared pattern)
    into the skill."""
    msg = factory_refs.lesson(ws, ids, note)
    out = send(ws, msg["text"], runner=runner)
    factory_refs.mark_learned(ws, msg["ids"])
    return dict(out, references=factory_refs.listing(ws))
