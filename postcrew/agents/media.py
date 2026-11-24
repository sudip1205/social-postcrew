"""Media agent: designs and renders the visual, a still 1080x1350 image (owner, 2026-11-24: "for linkedin post do not create
movies. create images instead ... create a own attractive style"). The image is a JSON spec drawn in the Signal Board style by
render/card.py (headless Chrome); without Chrome the older Pillow poster (render/poster.py) is the fallback. The algorithm
animation, the animated poster and the system-flow animation are no longer made for LinkedIn."""
import json
import subprocess
from urllib.parse import urlparse

from .. import brief as briefmod
from ..checks import check_code, number_problems, poster_number_problems
from ..render import card, poster, sysflow
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
        if card.available():
            return self._card(ctx, guidance, handle)
        ctx.run.event(self.id, "fallback", "Chrome is not installed, so this post gets the plain poster instead of the Signal Board image",
                      level="warning")
        return self._poster(ctx, guidance, handle)

    def _card(self, ctx, guidance, handle):
        system = self.prompt(ctx, "card", kicker=KICKER_RULE, icons=", ".join(card.ICONS))
        prev = (ctx.previous.get("media") or {}).get("spec", {})
        prompt = (f"THE POST (the image must agree with it and add no new claims):\n{ctx.outputs['writer']['text']}"
                  + "\n\nEvery fact, name and number on the image must appear in the post above, worded the same way "
                    "(same qualifiers, same figures). Leave out anything the post does not say."
                  + (f"\n\nYOUR PREVIOUS IMAGE SPEC (revise it to match the post and fix what was wrong):\n{json.dumps(prev, ensure_ascii=False)}"
                     if prev.get("layout") in card.LAYOUTS else "")
                  + guidance_block(guidance))
        spec = self.ask(ctx, system, prompt, card.SCHEMA)
        spec["kicker"] = kicker_for(ctx, spec)
        source = source_footer(ctx.outputs.get("research"), ctx.outputs["writer"].get("first_comment", ""))
        out = {"kind": "image", "path": None, "spec": spec, "shown_text": card.shown_text(spec), "style": "signal-board"}
        bad = card.validate_spec(spec)
        if bad:
            return dict(out, render_error="; ".join(bad))
        path = ctx.run.dir / "image.png"
        try:
            card.render_card(spec, path, handle, source)
        except (card.CardError, OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as e:
            return dict(out, render_error=str(e))
        return dict(out, path=str(path))

    def _poster(self, ctx, guidance, handle):
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
        return {"kind": "image", "path": str(path), "spec": spec, "shown_text": poster.poster_text(spec)}

    def validate(self, ctx, out):
        if "sysflow" in out.get("spec", {}):
            return self._validate_sysflow(ctx, out)
        if out.get("kind") == "video":   # an older run's video: LinkedIn gets images now (owner, 2026-11-24)
            return ["LinkedIn posts get a still image, not a video: design the image"]
        if out.get("style") == "signal-board":
            return self._validate_card(ctx, out)
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

    def _validate_card(self, ctx, out):
        if out.get("render_error"):
            return [f"the image did not render: {out['render_error']}"]
        spec, problems = out["spec"], []
        if spec.get("layout") == "code":
            err = check_code(spec.get("code") or "", spec.get("language"))
            if err:
                problems.append(f"the code on the image does not parse: {err}")
        problems += poster_number_problems(ctx.outputs["writer"]["text"], out.get("shown_text", ""))
        if ctx.cat.get("fact_check"):
            research = ctx.outputs.get("research") or {}
            verified = [dict(s, page=research.get("_pages", {}).get(s["url"], "")) for s in research.get("verified", [])]
            problems += [p.replace("are not in", "on the image are not in") for p in number_problems("", out.get("shown_text", ""), verified)]
        return [p.replace("the poster", "the image") for p in problems]

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
        if out.get("style") == "signal-board":
            return f"image ({out.get('spec', {}).get('layout', '?')}, Signal Board)"
        if "sysflow" in out.get("spec", {}):
            s = out["spec"]["sysflow"]
            return f"system animation ({len(s.get('systems', []))} components, {out.get('seconds', 0):.0f}s)"
        if out.get("kind") == "video" and "algo" not in out.get("spec", {}):
            return f"animated poster ({out['spec'].get('layout', '?')}, {out.get('seconds', 0):.0f}s)"
        if out.get("kind") == "video":
            return f"animation {out['spec']['algo']} ({out.get('seconds', 0):.0f}s)"
        return f"poster ({out.get('spec', {}).get('layout', '?')})"
