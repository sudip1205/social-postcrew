"""Blackboard Producer and Explainer Producer (YouTube): a drawn video made to the voice that was recorded first. No LLM.

The voice is made first (the Voice step). The pace is the voice's: every scene is as long as its recording, and render/timeline.py
places each box, arrow, bullet and line of code inside the scene by when its words are said, measured on the real audio.

  explainer   (video.renderer = "explainer") a slow, clean animated explanation on a dark screen: one picture that keeps
              growing while the narrator explains, the thing being explained glowing, highlighted caption chunks.
  blackboard  (video.renderer = "blackboard") the same, drawn in chalk on a green board.

A topic's own "renderer" overrides the app's. The Video Editor (agents/video_review.py) then checks the finished video.
"""
from ..render import blackboard as bb
from ..render import explainer as ex
from ..render import video as video_mod
from .base import AgentError
from .video import VideoAgent


class BlackboardAgent(VideoAgent):
    title = "Blackboard Producer"
    name = "Chalk"
    role = ("Draws the script by hand on a blackboard, timed to the voice that was recorded first: boxes, arrows, bullets "
            "and code appear as they are spoken.")
    renderer = "blackboard"
    draw = bb

    def thumbnail(self, script, kicker, handle, path):
        return self.draw.thumbnail(script, kicker, handle, path)

    def render(self, ctx, scenes, audio, out_path, work, kicker, handle):
        if audio:
            ctx.run.event(self.id, "timeline", "timing the drawing to the voice: every scene is as long as its recording")
        else:
            ctx.run.event(self.id, "timeline", "no voice yet: timing the drawing to the narration's word count", level="warning")
        try:
            info = self.draw.render(scenes, out_path, ctx.video["format"], work, audio=audio, handle=handle, kicker=kicker,
                                    captions=bool(ctx.cfg["video"].get("captions", True)),
                                    progress=lambda done, total: ctx.run.event(self.id, "progress", f"scene {done}/{total}"))
        except video_mod.VideoError as e:
            raise AgentError(f"drawing the video failed: {e}")
        drawn = sum(len(t["drawn"]) for t in info["timeline"])
        ctx.run.event(self.id, "drawn", f"{drawn} things drawn across {len(scenes)} scenes")
        return info, self.renderer


class ExplainerAgent(BlackboardAgent):
    title = "Explainer Producer"
    name = "Motion"
    role = ("Animates the script on a dark screen, slowly and to the voice recorded first: icon boxes pop in as they are named, "
            "arrows draw themselves, the thing being explained glows, and captions follow the words.")
    renderer = "explainer"
    draw = ex
