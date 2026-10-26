"""Video Producer (YouTube): turns the approved script and voice into the finished video and its thumbnail. No LLM.

Slides and captions are drawn locally (render/scenes.py) and put together with ffmpeg (render/video.py). With
video.renderer = "mcp" an animation MCP server draws each scene instead (render/mcp_renderer.py); if it fails the built-in
renderer takes over. If the owner supplied a finished video it is used as it is, after the format and length checks.
Its id is "media": the Editor's and the Supervisor's notion of "the visuals".
"""
import shutil

from .. import assets as assets_mod
from ..render import scenes as scenes_mod
from ..render import video as video_mod
from ..render.mcp_renderer import McpError, render_clips
from .base import Agent, AgentError

THUMB = (1280, 720)


def make_thumbnail(script, kicker, handle, out_path):
    """A 16:9 thumbnail (YouTube's size for every kind of video): the thumbnail text big, the title small."""
    from PIL import Image
    scene = {"layout": "title", "on_screen": script.get("thumbnail_text") or script["title"],
             "items": [script["title"]], "narration": "", "code": "", "language": "", "seconds": 0}
    img = scenes_mod.draw_frame(scene, "long", caption="", kicker=kicker, handle=handle, index=0, total=1)
    img.convert("RGB").resize(THUMB, Image.LANCZOS).save(out_path, "PNG")
    return out_path


class VideoAgent(Agent):
    id = "media"
    title = "Video Producer"
    name = "Reel"
    role = "Draws the scenes, adds captions and the voice, and renders the finished video and its thumbnail."
    uses_llm = False

    def run(self, ctx, guidance):
        if not shutil.which("ffmpeg"):
            raise AgentError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt install ffmpeg)",
                             fatal=True)
        script, spec = ctx.outputs["writer"], ctx.video
        own = assets_mod.find(ctx.ws, ctx.platform, ctx.day)
        kicker = (ctx.cat.get("kicker") or ctx.cat["label"]).upper()[:26]
        handle = ctx.profile.get("handle", "")
        thumb = ctx.run.dir / "thumbnail.png"
        self.thumbnail(script, kicker, handle, thumb)
        if "video" in own:   # a finished video from the owner: used as it is
            info = video_mod.probe(own["video"])
            bad = [c for c in video_mod.check_video(own["video"], spec["format"]) if not c["ok"]]
            if bad:
                raise AgentError("your video does not fit: " + "; ".join(f"{c['label']}: {c['detail']}" for c in bad)
                                 + f". This is a {spec['format']} video: change the video type in Settings or upload another file.",
                                 fatal=True)
            return {"kind": "video", "path": str(own["video"]), "thumbnail_path": str(thumb), "seconds": round(info["seconds"], 1),
                    "width": info["width"], "height": info["height"], "source": "own", "renderer": "own", "shown_text": ""}
        voice = ctx.outputs.get("voice") or {}
        audio = own.get("voice")
        audio = str(audio) if audio else (voice.get("files") or None)
        scenes = [dict(sc) for sc in script["scenes"]]
        out_path = ctx.run.dir / "video.mp4"
        work = ctx.run.dir / "frames"
        info, renderer = self.render(ctx, scenes, audio, out_path, work, kicker, handle)
        return {"kind": "video", "path": str(out_path), "thumbnail_path": str(thumb), "seconds": round(info["seconds"], 1),
                "width": info["width"], "height": info["height"], "source": "crew", "renderer": renderer,
                "voice": "own" if own.get("voice") else voice.get("mode", "none"), "shown_text": "",
                "timeline": info.get("timeline")}

    def thumbnail(self, script, kicker, handle, path):
        return make_thumbnail(script, kicker, handle, path)

    def render(self, ctx, scenes, audio, out_path, work, kicker, handle):
        """Draw and join the scenes: (facts about the file, name of the renderer used)."""
        spec = ctx.video
        clips, renderer = None, "ffmpeg"
        mcp = ctx.cfg["video"].get("mcp") or {}
        if ctx.cfg["video"].get("renderer") == "mcp":
            try:
                clips = render_clips(mcp, scenes, spec["format"], work)
                renderer = "mcp"
            except McpError as e:
                ctx.run.event(self.id, "mcp_failed", f"the animation MCP server failed ({e}); using the built-in renderer",
                              level="warning")
        try:
            info = video_mod.compose(scenes, out_path, spec["format"], work, audio=audio, handle=handle, kicker=kicker,
                                     captions=bool(ctx.cfg["video"].get("captions", True)), clips=clips,
                                     progress=lambda done, total: ctx.run.event(self.id, "progress", f"scene {done}/{total}"))
        except video_mod.VideoError as e:
            raise AgentError(f"rendering the video failed: {e}")
        return info, renderer

    def validate(self, ctx, out):
        checks = video_mod.check_video(out["path"], ctx.video["format"])
        return [f"video {c['label'].lower()}: {c['detail']}" for c in checks if not c["ok"]]

    def summary(self, out):
        return f"{out['seconds']:.0f}s {out['width']}x{out['height']} ({out['renderer']}, {out['source']})"
