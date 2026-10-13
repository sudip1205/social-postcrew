"""Media agent: designs and renders the visual. Posters are a JSON spec drawn by Pillow (1080x1350 PNG);
algorithm posts get an MP4 where the Java line being executed is highlighted as the data moves."""
import json
import shutil
from urllib.parse import urlparse

from ..checks import check_code, number_problems, poster_number_problems
from ..render import animate, poster, tracers
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


class MediaAgent(Agent):
    id = "media"
    title = "Visual Designer"
    name = "Pixel"
    role = "Designs the poster (or renders the algorithm animation) and checks it fits and matches the post."

    def applies(self, ctx):
        return ctx.cat["media"] != "none"

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
        system = self.prompt(ctx, layouts=", ".join(ctx.cat["layouts"]), kicker=ctx.cat.get("kicker", ""))
        prompt = (f"Allowed layouts: {ctx.cat['layouts']}\nKicker (pill text): {ctx.cat.get('kicker', '')}\n\n"
                  f"THE POST (the poster must agree with it and add no new claims):\n{ctx.outputs['writer']['text']}"
                  + "\n\nEvery fact, name and number on the poster must appear in the post above, worded the same way "
                    "(same qualifiers, same figures). Leave out anything the post does not say."
                  + (f"\n\nYOUR PREVIOUS POSTER SPEC (revise it to match the post above):\n"
                     f"{json.dumps(ctx.previous['media'].get('spec', {}), ensure_ascii=False)}"
                     if ctx.previous.get("media") else "")
                  + guidance_block(guidance))
        spec = self.ask(ctx, system, prompt, SCHEMA)
        spec["kicker"] = spec.get("kicker") or ctx.cat.get("kicker", "")
        spec["footer_left"] = source_footer(ctx.outputs.get("research"), ctx.outputs["writer"].get("first_comment", ""))
        path = ctx.run.dir / "poster.png"
        try:
            poster.render_poster(spec, path, handle)
        except (poster.PosterError, ValueError, KeyError, TypeError) as e:
            return {"kind": "image", "path": None, "spec": spec, "shown_text": "", "render_error": str(e)}
        return {"kind": "image", "path": str(path), "spec": spec, "shown_text": poster.poster_text(spec)}

    def validate(self, ctx, out):
        if out.get("render_error"):
            return [f"the poster did not render: {out['render_error']}. Shorten the text or use fewer items"]
        problems = []
        spec = out.get("spec", {})
        if out["kind"] == "image" and spec.get("layout") not in ctx.cat.get("layouts", []):
            problems.append(f"layout must be one of {ctx.cat['layouts']}")
        if out["kind"] == "video" and not 15 <= (out.get("seconds") or 0) <= 60:
            problems.append(f"video is {out.get('seconds')}s; it must be 15-60s")
        if spec.get("code"):
            err = check_code(spec["code"], spec.get("language"))
            if err:
                problems.append(f"the poster code does not parse: {err}")
        if out["kind"] == "image":
            problems += poster_number_problems(ctx.outputs["writer"]["text"], out.get("shown_text", ""))
        if ctx.cat.get("fact_check"):
            research = ctx.outputs.get("research") or {}
            verified = [dict(s, page=research.get("_pages", {}).get(s["url"], ""))
                        for s in research.get("verified", [])]
            problems += [p.replace("are not in", "on the poster are not in")
                         for p in number_problems("", out.get("shown_text", ""), verified)]
        return problems

    def summary(self, out):
        if out.get("kind") == "video":
            return f"animation {out['spec']['algo']} ({out.get('seconds', 0):.0f}s)"
        return f"poster ({out.get('spec', {}).get('layout', '?')})"
