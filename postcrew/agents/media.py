"""Media agent: designs and renders the visual. Posters are a JSON spec drawn by Pillow (1080x1350 PNG);
algorithm posts get an MP4 where the Java line being executed is highlighted as the data moves."""
import json
import shutil
from urllib.parse import urlparse

from .. import brief as briefmod
from ..checks import check_code, number_problems, poster_number_problems
from ..render import animate, poster, sysflow, tracers
from .base import Agent, AgentError, guidance_block

ITEM = {"type": "object", "properties": {k: {"type": "string"} for k in ("head", "body", "label", "sub", "tag", "via")},
        "additionalProperties": False}
SCHEMA = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": ["points", "steps", "code", "flow"]},
        "kicker": {"type": "string"}, "title": {"type": "string"}, "subtitle": {"type": "string"},
        "items": {"type": "array", "items": ITEM, "maxItems": 7},
        "result": {"type": "string"}, "language": {"type": "string"}, "code": {"type": "string"},
        "caption": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "highlight": {"type": "integer"},
    },
    "required": ["layout", "title"],
    "additionalProperties": False,
}


def source_footer(research, first_comment=""):
    """The source line on the poster: the first comment's link (the post's primary source) if it fits whole,
    otherwise its site name. Never a cut-off address: reviewers rightly flag a link that does not work."""
    urls = [first_comment] + [s.get("url", "") for s in (research or {}).get("verified", []) if s.get("verified")]
    for url in urls:
        u = urlparse((url or "").strip())
        if u.scheme == "https" and u.netloc:
            host = u.netloc[4:] if u.netloc.startswith("www.") else u.netloc
            full = f"Source: {host}{u.path.rstrip('/')}"
            return full if len(full) <= 52 else f"Source: {host} (link in the first comment)"[:70]
    return ""


KICKER_RULE = ("a short label for this post, 1-3 words, at most 24 characters, taken from its topic "
               "(for example 'TOKEN EXCHANGE' or 'PASSKEYS')")


def kicker_for(ctx, spec):
    """The label on the picture comes from the post's own context; the topic name is the fallback."""
    k = " ".join(str(spec.get("kicker") or "").split())
    if not k:
        k = (ctx.outputs.get("topic") or {}).get("topic") or ctx.cat.get("label", "")
    return k.upper()[:26].rstrip()


class MediaAgent(Agent):
    id = "media"
    title = "Visual Designer"
    name = "Pixel"
    role = "Designs the poster (or renders the algorithm animation) and checks it fits and matches the post."

    def applies(self, ctx):
        return ctx.cat["media"] != "none" and briefmod.media_mode(ctx.cat, briefmod.of(ctx)) != "none"

    def run(self, ctx, guidance):
        handle = ctx.profile.get("handle", "")
        if ctx.cat["media"] == "animation":
            algo = ctx.outputs["topic"].get("algo")
            if algo not in tracers.TRACERS:
                raise AgentError(f"unknown algorithm {algo!r}", fatal=True)
            if not shutil.which("ffmpeg"):
                raise AgentError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: "
                                 "sudo apt install ffmpeg)", fatal=True)
            path = ctx.run.dir / f"animation-{algo}.mp4"
            try:
                info = animate.render_animation(algo, path, handle)
            except animate.AnimationError as e:
                raise AgentError(str(e), fatal=True)
            return {"kind": "video", "path": str(path), "seconds": info.get("seconds"),
                    "shown_text": animate.animation_text(algo), "spec": {"algo": algo}}
        if briefmod.media_mode(ctx.cat, briefmod.of(ctx)) == "sysflow":
            return self._sysflow(ctx, guidance, handle)
        layouts = list(poster.LAYOUTS)   # the style is chosen from the post: code for code, steps for how-tos...
        system = self.prompt(ctx, layouts=", ".join(layouts), kicker=KICKER_RULE)
        prompt = (f"Allowed layouts: {layouts}\nKicker (pill text): {KICKER_RULE}\n\n"
                  f"THE POST (the poster must agree with it and add no new claims):\n{ctx.outputs['writer']['text']}"
                  + "\n\nEvery fact, name and number on the poster must appear in the post above, worded the same way "
                    "(same qualifiers, same figures). Leave out anything the post does not say."
                  + (f"\n\nYOUR PREVIOUS POSTER SPEC (revise it to match the post above):\n"
                     f"{json.dumps(ctx.previous['media'].get('spec', {}), ensure_ascii=False)}"
                     if ctx.previous.get("media") else "")
                  + guidance_block(guidance))
        spec = self.ask(ctx, system, prompt, SCHEMA)
        spec["kicker"] = kicker_for(ctx, spec)
        spec["footer_left"] = source_footer(ctx.outputs.get("research"), ctx.outputs["writer"].get("first_comment", ""))
        path = ctx.run.dir / "poster.png"
        try:
            poster.render_poster(spec, path, handle)
        except (poster.PosterError, ValueError, KeyError, TypeError) as e:
            return {"kind": "image", "path": None, "spec": spec, "shown_text": "", "render_error": str(e)}
        out = {"kind": "image", "path": str(path), "spec": spec, "shown_text": poster.poster_text(spec)}
        if ctx.cat["media"] == "video":   # the same poster, built up piece by piece
            if not shutil.which("ffmpeg"):
                ctx.run.event(self.id, "fallback", "ffmpeg is not installed, so this post gets the poster image "
                              "instead of the animated video (macOS: brew install ffmpeg; Debian/Ubuntu: "
                              "sudo apt install ffmpeg)", level="warning")
                return out
            video = ctx.run.dir / "poster.mp4"
            try:
                info = animate.render_poster_video(spec, video, handle)
            except (animate.AnimationError, poster.PosterError) as e:
                raise AgentError(str(e), fatal=True)
            out.update(kind="video", path=str(video), poster=str(path), seconds=info["seconds"])
        return out

    def _sysflow(self, ctx, guidance, handle):
        if not shutil.which("ffmpeg"):
            raise AgentError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: "
                             "sudo apt install ffmpeg)", fatal=True)
        ob = briefmod.of(ctx)
        system = self.prompt(ctx, "sysflow", kicker=KICKER_RULE)
        prompt = (f"THE POST (the animation must agree with it and add no new claims):\n{ctx.outputs['writer']['text']}\n\n"
                  f"Kicker (pill text): {KICKER_RULE}\n\n" + briefmod.media_block(ob)
                  + (f"\n\nYOUR PREVIOUS SPEC (revise it):\n{json.dumps(ctx.previous['media'].get('spec', {}).get('sysflow', {}), ensure_ascii=False)}"
                     if (ctx.previous.get("media") or {}).get("spec", {}).get("sysflow") else "")
                  + guidance_block(guidance))
        spec = self.ask(ctx, system, prompt, sysflow.SCHEMA)
        spec["kicker"] = kicker_for(ctx, spec)
        bad = sysflow.validate_spec(spec)
        shown = sysflow.shown_text(spec)
        if bad:
            return {"kind": "video", "path": None, "spec": {"sysflow": spec}, "shown_text": shown,
                    "render_error": "; ".join(bad)}
        path, still = ctx.run.dir / "system-flow.mp4", ctx.run.dir / "system-flow.png"
        try:
            info = sysflow.render_sysflow(spec, path, handle, still_path=still)
        except sysflow.SysflowError as e:
            raise AgentError(str(e), fatal=True)
        return {"kind": "video", "path": str(path), "poster": str(still), "seconds": info["seconds"],
                "spec": {"sysflow": spec}, "shown_text": shown}

    def validate(self, ctx, out):
        if "sysflow" in out.get("spec", {}):
            return self._validate_sysflow(ctx, out)
        if out.get("render_error"):
            return [f"the poster did not render: {out['render_error']}. Shorten the text or use fewer items"]
        problems = []
        spec = out.get("spec", {})
        if "algo" not in spec and spec.get("layout") not in poster.LAYOUTS:
            problems.append(f"layout must be one of {list(poster.LAYOUTS)}")
        if out["kind"] == "video" and not 15 <= (out.get("seconds") or 0) <= 60:
            problems.append(f"video is {out.get('seconds')}s; it must be 15-60s")
        if spec.get("code"):
            err = check_code(spec["code"], spec.get("language"))
            if err:
                problems.append(f"the poster code does not parse: {err}")
        if "algo" not in spec:   # a poster, still or animated
            problems += poster_number_problems(ctx.outputs["writer"]["text"], out.get("shown_text", ""))
        if ctx.cat.get("fact_check"):
            research = ctx.outputs.get("research") or {}
            verified = [dict(s, page=research.get("_pages", {}).get(s["url"], ""))
                        for s in research.get("verified", [])]
            problems += [p.replace("are not in", "on the poster are not in")
                         for p in number_problems("", out.get("shown_text", ""), verified)]
        return problems

    def _validate_sysflow(self, ctx, out):
        if out.get("render_error"):
            return [f"the animation spec is not valid: {out['render_error']}"]
        problems = []
        secs = out.get("seconds") or 0
        if not sysflow.MIN_SECONDS <= secs <= sysflow.MAX_SECONDS:
            problems.append(f"the animation is {secs:.0f}s; it must be {sysflow.MIN_SECONDS:.0f}-{sysflow.MAX_SECONDS:.0f}s")
        post = ctx.outputs["writer"]["text"].lower()
        names = [s["label"] for s in out["spec"]["sysflow"].get("systems", [])]
        absent = [n for n in names if n.lower() not in post and n.split()[0].lower() not in post]
        if len(absent) > max(1, len(names) // 2):   # soft: the post and the animation should name the same parts
            problems.append(f"the post never mentions these animated components: {absent}. Rename them to the words "
                            f"the post uses so the text and the animation agree")
        extra = poster_number_problems(ctx.outputs["writer"]["text"] + " " + " ".join(briefmod.numbers_in(briefmod.of(ctx))),
                                       sysflow.claim_text(out["spec"]["sysflow"]))
        return problems + [e.replace("the poster shows numbers the post does not",
                                     "the animation's titles and captions show numbers the post does not") for e in extra]

    def summary(self, out):
        if "sysflow" in out.get("spec", {}):
            s = out["spec"]["sysflow"]
            return f"system animation ({len(s.get('systems', []))} components, {out.get('seconds', 0):.0f}s)"
        if out.get("kind") == "video" and "algo" not in out.get("spec", {}):
            return f"animated poster ({out['spec'].get('layout', '?')}, {out.get('seconds', 0):.0f}s)"
        if out.get("kind") == "video":
            return f"animation {out['spec']['algo']} ({out.get('seconds', 0):.0f}s)"
        return f"poster ({out.get('spec', {}).get('layout', '?')})"
