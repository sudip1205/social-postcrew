"""Motion Studio: the Reference Library, the house style and approved feedback. All of it is files in the workspace:

    motion/references/<id>/meta.json       title, creator, rights, status, measured facts
    motion/references/<id>/source.<ext>    the video you added (a copy; delete removes it)
    motion/references/<id>/frames/*.png    one frame per shot, and the contact sheets the vision model reads
    motion/references/<id>/analysis.json   scenes (purpose, picture, motion, on-screen text), the style profile and the patterns
    motion/styles/house-v<N>.json          every version of the house style; house.json says which one is current
    motion/feedback.jsonl                  your ratings and notes on finished videos
    motion/preferences.json                the notes you approved: the only feedback the crew learns from

What it is for: the crew makes its own scripts and pictures; references teach it HOW good explainers look and move (pacing, layout,
colour, motion, how a scene is built), never WHAT they say. Nothing is copied: a style profile and a pattern are abstract (\"a big number
counts up, then a label explains it\"), never a reference's script, frames, voice, music or brand.

Rights: a reference is only accepted with a rights declaration (own, licensed or permission). Postcrew never downloads videos from
YouTube or any other site: you add a file you are allowed to use.
"""
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import frames as fr

RIGHTS = ("own", "licensed", "permission", "public-domain")
STATUSES = ("analyzing", "profile_review", "ready", "rejected", "failed")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
MAX_SECONDS = 600            # a reference longer than 10 minutes is refused (a Short or one explainer is what is needed)
MAX_MB = 1024
ANALYZER_VERSION = 1
PURPOSES = ["hook", "setup", "explanation", "example", "reveal", "summary", "cta"]
FEEDBACK_KINDS = ["hook_weak", "narration_fast", "too_much_text", "too_few_changes", "animation_slow", "animation_busy",
                  "wrong_palette", "poor_metaphor", "wrong_fact", "captions_hard", "audio_mismatch", "transition_awkward",
                  "text_too_small", "empty_screen", "other"]
# what an approved note of each kind teaches the crew, when the note itself says nothing more
KIND_RULE = {
    "hook_weak": "Open with the problem shown as a picture in the first 2 seconds, not a title card.",
    "narration_fast": "Give each idea its own scene; never more than about 2.5 spoken words per second.",
    "too_much_text": "At most 6 words on screen at a time besides code; show, do not write.",
    "too_few_changes": "Something new must appear on screen at least every 3 seconds.",
    "animation_slow": "Things appear when they are said; nothing waits more than a second after its word.",
    "animation_busy": "One moving thing at a time; the rest stays still.",
    "wrong_palette": "Use only the look's own colours; colour marks what to look at.",
    "poor_metaphor": "Every scene shows the thing the voice explains as a concrete picture (an object, a diagram, real data).",
    "wrong_fact": "Every number and claim on screen must match the script and the research.",
    "captions_hard": "Captions sit in the bottom band and nothing important is drawn behind them.",
    "audio_mismatch": "What appears on screen follows the order the voice names it.",
    "transition_awkward": "Consecutive scenes share an element so the picture grows instead of cutting away.",
    "text_too_small": "No text smaller than 40 px in a 1080x1920 frame; diagrams have at most 5 boxes so labels stay big.",
    "empty_screen": "The picture fills the area between the heading and the captions; no scene is ever empty.",
}

# The house style before any reference is analysed: the rules a strong Short follows, in the profile shape the analyser produces.
DEFAULT_HOUSE = {
    "profile_name": "Postcrew house style",
    "version": 0,
    "source": "built-in",
    "format": {"aspect_ratio": "9:16", "target_fps": 30},
    "visual_system": {"background": "the video look's page (paper, ink or neon)", "typography": "bold sans headlines, mono for code and numbers",
                      "composition": "one subject per scene, large, filling the area between the heading and the captions",
                      "min_text_px": 40, "max_words_on_screen": 6},
    "motion_language": {"preferred": ["build up piece by piece as named", "count up", "draw arrows", "highlight the active part"],
                        "transitions": ["the picture grows (shared elements stay)", "cut on a new idea"],
                        "motion_intensity": "medium", "max_still_seconds": 3.5},
    "storytelling": {"hook_type": "the problem shown as a picture in the first 2 seconds", "scene_rhythm": "a new visual beat every 2-4 seconds",
                     "ending": "the takeaway in one picture, then the closing card"},
    "pacing": {"shot_seconds": 3.0, "cuts_per_minute": 20},
    "constraints": {"avoid": ["small unreadable text", "an empty or half-empty screen", "a picture that does not change for long",
                              "walls of text", "the same layout three times in a row", "decoration that explains nothing"],
                    "original_assets_required": True},
    "patterns": [
        {"name": "question then reveal", "purpose": "hook", "recipe": "the question as a few big words, then the answer appears as a picture or number"},
        {"name": "build the diagram as it is named", "purpose": "explanation", "recipe": "each box appears when the voice names it; arrows draw in spoken order"},
        {"name": "worked example with real data", "purpose": "example", "recipe": "real values move through the picture step by step, the result is highlighted"},
        {"name": "wrong then right", "purpose": "reveal", "recipe": "the wrong path fails visibly (red, dropped), then the fix on the same picture"},
        {"name": "big number", "purpose": "setup", "recipe": "the figure counts up large, a short label explains it"},
        {"name": "one-picture summary", "purpose": "summary", "recipe": "the whole idea as one finished diagram with the key part highlighted"},
    ],
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Library:
    def __init__(self, ws):
        self.ws = ws
        self.root = Path(ws.root) / "motion"
        self.refs = self.root / "references"
        self.styles = self.root / "styles"

    # ---------- references ----------
    def _dir(self, rid):
        if not re.fullmatch(r"[a-z0-9-]{4,64}", str(rid or "")):
            raise ValueError(f"not a reference id: {rid!r}")
        d = self.refs / rid
        if not d.is_dir():
            raise KeyError(f"no reference {rid}")
        return d

    def meta(self, rid):
        return json.loads((self._dir(rid) / "meta.json").read_text())

    def _save_meta(self, rid, meta):
        meta["updated_at"] = now()
        (self.refs / rid / "meta.json").write_text(json.dumps(meta, indent=1))
        return meta

    def analysis(self, rid):
        p = self._dir(rid) / "analysis.json"
        return json.loads(p.read_text()) if p.exists() else None

    def references(self):
        out = []
        for m in sorted(self.refs.glob("*/meta.json")):
            try:
                out.append(json.loads(m.read_text()))
            except ValueError:
                continue
        return sorted(out, key=lambda m: m.get("created_at", ""), reverse=True)

    def add(self, path, rights, title="", creator="", notes="", tags=()):
        """Copy an authorised video file into the library. Returns its meta. Does not analyse it yet."""
        src = Path(path).expanduser()
        if rights not in RIGHTS:
            raise ValueError(f"say what rights you have to this video: one of {', '.join(RIGHTS)}. Postcrew only learns from videos "
                             f"you made, licensed, have permission for, or that are public domain.")
        if not src.is_file():
            raise ValueError(f"{src} is not a file. Postcrew does not download videos from sites: add a file you are allowed to use.")
        if src.suffix.lower() not in VIDEO_EXT:
            raise ValueError(f"{src.name}: not a video file ({', '.join(VIDEO_EXT)})")
        if src.stat().st_size > MAX_MB * 1024 * 1024:
            raise ValueError(f"{src.name} is larger than {MAX_MB} MB")
        info = fr.probe(src)
        if info["seconds"] > MAX_SECONDS:
            raise ValueError(f"{src.name} is {info['seconds']:.0f}s long: references are at most {MAX_SECONDS}s (a Short or one explainer)")
        rid = time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
        d = self.refs / rid
        d.mkdir(parents=True)
        shutil.copy2(src, d / f"source{src.suffix.lower()}")
        meta = {"id": rid, "title": title or src.stem, "creator": creator, "rights": rights, "notes": notes, "tags": list(tags),
                "file": f"source{src.suffix.lower()}", "original_name": src.name, "status": "analyzing", "created_at": now(),
                "analyzer_version": None, **{k: info[k] for k in ("seconds", "width", "height", "fps", "has_audio")}}
        return self._save_meta(rid, meta)

    def set_status(self, rid, status, reason=""):
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        meta = self.meta(rid)
        meta["status"] = status
        if reason:
            meta["status_reason"] = reason
        return self._save_meta(rid, meta)

    def delete(self, rid):
        shutil.rmtree(self._dir(rid))

    def measure_reference(self, rid, log=print):
        """The no-AI half of an analysis: shots, one frame per shot, measured facts and contact sheets."""
        d = self._dir(rid)
        meta = self.meta(rid)
        video = d / meta["file"]
        log(f"finding the cuts in {meta['title']}")
        shot_list = fr.shots(video, meta["seconds"], max_shots=36)
        fdir = d / "frames"
        shutil.rmtree(fdir, ignore_errors=True)
        cells, measured = [], []
        for i, (a, b) in enumerate(shot_list, 1):
            mid = a + (b - a) * 0.6
            p = fr.grab(video, mid, fdir / f"shot-{i:02d}.png", 360)
            m = fr.measure(p)
            measured.append({"shot": i, "start": round(a, 2), "end": round(b, 2), **m})
            cells.append((f"S{i}  {a:.1f}-{b:.1f}s", p))
        sheets = [fr.sheet(cells[k:k + 12], fdir / f"sheet-{k // 12 + 1}.png", cols=4, cell_width=300)
                  for k in range(0, len(cells), 12)]
        lens = [s["end"] - s["start"] for s in measured]
        facts = {"shots": len(measured), "shot_seconds": round(sum(lens) / len(lens), 2) if lens else None,
                 "cuts_per_minute": round(len(measured) / max(meta["seconds"], 1) * 60, 1),
                 "fill": round(sum(s["fill"] for s in measured) / len(measured), 3) if measured else None,
                 "height": round(sum(s["height"] for s in measured) / len(measured), 3) if measured else None,
                 "palette": _common_palette([s["palette"] for s in measured])}
        transcript = transcribe(video, log)
        if transcript and transcript.get("words"):
            facts["words_per_second"] = round(transcript["words"] / max(meta["seconds"], 1), 2)
        meta.update(measured=facts, transcript=bool(transcript))
        self._save_meta(rid, meta)
        (d / "shots.json").write_text(json.dumps({"shots": measured, "transcript": transcript}, indent=1))
        return {"shots": measured, "facts": facts, "sheets": [str(s) for s in sheets], "transcript": transcript}

    def save_analysis(self, rid, analysis):
        meta = self.meta(rid)
        analysis["analyzer_version"] = ANALYZER_VERSION
        analysis["analyzed_at"] = now()
        (self._dir(rid) / "analysis.json").write_text(json.dumps(analysis, indent=1))
        meta.update(status="profile_review", analyzer_version=ANALYZER_VERSION)
        return self._save_meta(rid, meta)

    def approved(self):
        """(meta, analysis) of every reference you approved."""
        out = []
        for m in self.references():
            if m.get("status") == "ready":
                a = self.analysis(m["id"])
                if a:
                    out.append((m, a))
        return out

    # ---------- house style ----------
    def house(self):
        """The current house style (the built-in one until you build your own)."""
        cur = self.styles / "house.json"
        if cur.exists():
            try:
                v = json.loads(cur.read_text()).get("version")
                p = self.styles / f"house-v{v}.json"
                if p.exists():
                    return json.loads(p.read_text())
            except ValueError:
                pass
        return json.loads(json.dumps(DEFAULT_HOUSE))

    def versions(self):
        out = []
        for p in self.styles.glob("house-v*.json"):
            try:
                d = json.loads(p.read_text())
                out.append({"version": d.get("version"), "created_at": d.get("created_at"), "from": d.get("from_references", [])})
            except ValueError:
                continue
        return sorted(out, key=lambda v: v["version"] or 0)

    def save_house(self, style, references=()):
        self.styles.mkdir(parents=True, exist_ok=True)
        v = max([x["version"] or 0 for x in self.versions()] + [0]) + 1
        style = dict(style, version=v, created_at=now(), from_references=list(references), source="references" if references else style.get("source", "edited"))
        (self.styles / f"house-v{v}.json").write_text(json.dumps(style, indent=1))
        (self.styles / "house.json").write_text(json.dumps({"version": v}))
        return style

    def use_version(self, v):
        if not (self.styles / f"house-v{int(v)}.json").exists():
            raise KeyError(f"no house style version {v}")
        (self.styles / "house.json").write_text(json.dumps({"version": int(v)}))
        return self.house()

    def reset_house(self):
        p = self.styles / "house.json"
        if p.exists():
            p.unlink()
        return self.house()

    # ---------- feedback ----------
    def _feedback_file(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / "feedback.jsonl"

    def feedback(self):
        p = self.root / "feedback.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def add_feedback(self, video, rating=None, kind="other", comment="", scene=None):
        if kind not in FEEDBACK_KINDS:
            raise ValueError(f"kind must be one of {', '.join(FEEDBACK_KINDS)}")
        if rating is not None and not 1 <= int(rating) <= 5:
            raise ValueError("rating is 1 (poor) to 5 (great)")
        if kind == "other" and not comment.strip() and rating is None:
            raise ValueError("say what was wrong: a kind, a comment or a rating")
        item = {"id": uuid.uuid4().hex[:8], "video": str(video), "scene": int(scene) if scene else None,
                "rating": int(rating) if rating is not None else None, "kind": kind, "comment": comment.strip()[:500],
                "approved": False, "created_at": now()}
        with self._feedback_file().open("a") as f:
            f.write(json.dumps(item) + "\n")
        return item

    def approve_feedback(self, fid, rule=""):
        """Approve one note: it becomes a preference the Creative Director and the Quality Director follow from the next video on."""
        items = self.feedback()
        hit = next((x for x in items if x["id"] == fid), None)
        if not hit:
            raise KeyError(f"no feedback {fid}")
        hit["approved"] = True
        self._feedback_file().write_text("".join(json.dumps(x) + "\n" for x in items))
        text = rule.strip() or KIND_RULE.get(hit["kind"]) or hit["comment"]
        if not text:
            raise ValueError("this note has nothing to learn: give the rule with --rule")
        prefs = self.preferences()
        if text not in [p["rule"] for p in prefs]:
            prefs.append({"rule": text, "from": fid, "kind": hit["kind"], "approved_at": now()})
            (self.root / "preferences.json").write_text(json.dumps(prefs, indent=1))
        return prefs

    def preferences(self):
        p = self.root / "preferences.json"
        try:
            return json.loads(p.read_text()) if p.exists() else []
        except ValueError:
            return []

    def forget_preference(self, n):
        prefs = self.preferences()
        if not 1 <= int(n) <= len(prefs):
            raise KeyError(f"no preference {n}")
        prefs.pop(int(n) - 1)
        (self.root / "preferences.json").write_text(json.dumps(prefs, indent=1))
        return prefs

    # ---------- what the crew reads ----------
    def patterns(self):
        """Every abstract pattern: the house style's own, then the approved references'."""
        out = [dict(p, source="house") for p in self.house().get("patterns", [])]
        for m, a in self.approved():
            for p in a.get("patterns") or []:
                out.append(dict(p, source=m["id"]))
        return out

    def relevant_patterns(self, purpose, text, n=3):
        """The patterns that fit one scene best: same purpose first, then shared words."""
        words = set(re.findall(r"[a-z]{4,}", (text or "").lower()))
        scored = []
        for p in self.patterns():
            s = (3 if p.get("purpose") == purpose else 0) + len(words & set(re.findall(r"[a-z]{4,}", (p.get("recipe", "") + " " + p.get("name", "")).lower())))
            if s:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for _s, p in scored:
            if p["name"] not in seen:
                seen.add(p["name"])
                out.append(p)
            if len(out) >= n:
                break
        return out

    def brief(self):
        """The house style and approved preferences as text for an agent's prompt."""
        h = self.house()
        prefs = self.preferences()
        lines = [f"HOUSE STYLE ({h.get('profile_name', 'house')}, v{h.get('version', 0)}):",
                 f"- composition: {h['visual_system'].get('composition', '')}",
                 f"- text: at least {h['visual_system'].get('min_text_px', 40)} px; at most {h['visual_system'].get('max_words_on_screen', 6)} words on screen besides code",
                 f"- motion: {', '.join(h['motion_language'].get('preferred', []))}; intensity {h['motion_language'].get('motion_intensity', 'medium')}; "
                 f"nothing stays still longer than {h['motion_language'].get('max_still_seconds', 3.5)}s",
                 f"- transitions: {', '.join(h['motion_language'].get('transitions', []))}",
                 f"- story: hook = {h['storytelling'].get('hook_type', '')}; rhythm = {h['storytelling'].get('scene_rhythm', '')}; ending = {h['storytelling'].get('ending', '')}",
                 f"- pacing: about {h.get('pacing', {}).get('shot_seconds', 3)}s per visual beat",
                 f"- avoid: {'; '.join(h['constraints'].get('avoid', []))}"]
        if prefs:
            lines.append("THE OWNER'S APPROVED PREFERENCES (follow every one):")
            lines += [f"- {p['rule']}" for p in prefs]
        return "\n".join(lines)


def _common_palette(palettes, n=5):
    count = {}
    for pal in palettes:
        for c in pal:
            count[c] = count.get(c, 0) + 1
    return [c for c, _ in sorted(count.items(), key=lambda x: -x[1])][:n]


def transcribe(video, log=print):
    """{"text", "segments", "words"} with faster-whisper when it is installed (pip install faster-whisper), else None."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("no transcript: install faster-whisper (pip install faster-whisper) to measure narration pace")
        return None
    try:
        log("transcribing the narration (faster-whisper, small model)")
        model = WhisperModel("small", device="auto", compute_type="int8")
        segs, _info = model.transcribe(str(video), vad_filter=True)
        segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
        text = " ".join(s["text"] for s in segments)
        return {"text": text, "segments": segments, "words": len(text.split())}
    except Exception as e:   # a missing model download or GPU problem must not stop the analysis
        log(f"no transcript: {str(e)[:160]}")
        return None
