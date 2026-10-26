"""Blackboard Producer (YouTube): a "draw and explain" video. The voice is made first; the board is drawn to its timeline. No LLM.

Where the Video Producer shows finished slides, this one draws by hand on a chalkboard while the narrator talks: the heading is
written, each box is drawn when the voice says its name, each arrow when the voice explains the step, bullets and code lines as
they are spoken. The pace is the voice's: the Voice step (which runs before this one) gives every scene's real length, and
render/timeline.py places each stroke inside the scene by when its words are said. Without a voice (a rehearsal) the pace is
the narration's word count.

Chosen with video.renderer = "blackboard" (all of an app's videos) or a topic's own "renderer": "blackboard".
"""
from ..render import blackboard as bb
from ..render import video as video_mod
from .base import AgentError
from .video import VideoAgent


class BlackboardAgent(VideoAgent):
    title = "Blackboard Producer"
    name = "Chalk"
    role = ("Draws the script by hand on a blackboard, timed to the voice that was recorded first: boxes, arrows, bullets "
            "and code appear as they are spoken.")

    def thumbnail(self, script, kicker, handle, path):
        return bb.thumbnail(script, kicker, handle, path)

    def render(self, ctx, scenes, audio, out_path, work, kicker, handle):
        if audio:
            ctx.run.event(self.id, "timeline", "timing the drawing to the voice: every scene is as long as its recording")
        else:
            ctx.run.event(self.id, "timeline", "no voice yet: timing the drawing to the narration's word count", level="warning")
        try:
            info = bb.render(scenes, out_path, ctx.video["format"], work, audio=audio, handle=handle, kicker=kicker,
                             captions=bool(ctx.cfg["video"].get("captions", True)),
                             progress=lambda done, total: ctx.run.event(self.id, "progress", f"scene {done}/{total}"))
        except video_mod.VideoError as e:
            raise AgentError(f"drawing the video failed: {e}")
        drawn = sum(len(t["drawn"]) for t in info["timeline"])
        ctx.run.event(self.id, "drawn", f"{drawn} things drawn across {len(scenes)} scenes")
        return info, "blackboard"
