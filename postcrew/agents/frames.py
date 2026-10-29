"""The three steps that make a Remotion-style video, one engine each, then one to join them. No LLM.

  text_frames  HyperFrames (HeyGen, HTML + GSAP) draws the scenes that are only words: the opening card and the big statements.
  data_frames  Remotion (React) draws every scene with data: diagrams, flows, traces, code, lists.
  media        the Video Composer joins the clips in scene order, lays the recorded voice under them, makes the thumbnail and
               checks the file. It is also the step the Editor and Supervisor call "the visuals".

Each drawing step reports its engine and a percentage to the run (shown live in the Studio), so you can see which engine is working.
"""
import json
from pathlib import Path

from ..render import hyperframes as hf
from ..render import remotion as rm
from ..render import video as video_mod
from ..render.scenes import FORMATS
from .base import Agent, AgentError
from .video import VideoAgent

FRAMES = ("text_frames", "data_frames")


class FramesAgent(Agent):
    uses_llm = False
    engine = ""

    def inputs(self, ctx):
        """(scenes, audio, kicker, handle) of this run, the same for both engines."""
        from .. import assets as assets_mod
        script = ctx.outputs["writer"]
        own = assets_mod.find(ctx.ws, ctx.platform, ctx.day)
        voice = ctx.outputs.get("voice") or {}
        audio = own.get("voice")
        audio = str(audio) if audio else (voice.get("files") or None)
        return [dict(sc) for sc in script["scenes"]], audio, own

    def cfg(self, ctx):
        r = ctx.cfg["video"].get("remotion")
        return {"remotion": r} if r else {}

    def mine(self, ctx, scenes):
        """The scene numbers this engine draws."""
        raise NotImplementedError

    def applies(self, ctx):
        from .. import assets as assets_mod
        if "video" in assets_mod.find(ctx.ws, ctx.platform, ctx.day):   # the owner's own finished video is used as it is
            return False
        return bool(self.mine(ctx, [dict(s) for s in ctx.outputs["writer"]["scenes"]]))

    def progress(self, ctx, done, total, what):
        pct = round(100 * done / max(1, total))
        ctx.run.step(self.id, progress=pct, engine=self.engine, detail=what)
        ctx.run.event(self.id, "progress", f"{self.engine}: {what} ({pct}%)", {"engine": self.engine, "percent": pct})

    def run(self, ctx, guidance):
        scenes, audio, _own = self.inputs(ctx)
        fmt, w = ctx.video["format"], FORMATS[ctx.video["format"]]
        kicker = handle = ""
        mine = self.mine(ctx, scenes)
        work = ctx.run.dir / ("frames-" + self.id)
        work.mkdir(parents=True, exist_ok=True)
        ctx.run.step(self.id, engine=self.engine, progress=0, detail="starting")
        try:
            props, _lengths = rm.build_props(scenes, fmt, audio)
            if not ctx.cfg["video"].get("captions", True):
                for s in props["scenes"]:
                    s["captions"] = []
            clips = self.draw(ctx, props, mine, work, w, fmt)
        except video_mod.VideoError as e:
            raise AgentError(f"{self.engine} could not draw the scenes: {e}")
        ctx.run.step(self.id, progress=100, detail=f"{len(mine)} scene(s) drawn")
        return {"engine": self.engine, "scenes": mine, "clips": clips}

    def draw(self, ctx, props, mine, work, size, fmt):
        raise NotImplementedError

    def validate(self, ctx, out):
        bad = [c["path"] for c in out["clips"] if not Path(c["path"]).exists() or Path(c["path"]).stat().st_size == 0]
        return [f"{self.engine} left no picture for {len(bad)} clip(s)"] if bad else []

    def summary(self, out):
        return f"{len(out['scenes'])} scene(s) drawn by {self.engine}"


class HyperFramesAgent(FramesAgent):
    id = "text_frames"
    title = "HyperFrames Producer"
    name = "Glyph"
    role = "Draws the scenes that are only words (the opening card and the big statements) with HyperFrames: HTML and GSAP motion."
    engine = "hyperframes"

    def mine(self, ctx, scenes):
        if hf.available():
            return []
        return [i for i, s in enumerate(scenes) if hf.engine_for(s) == "hyperframes"]

    def draw(self, ctx, props, mine, work, size, fmt):
        out = []
        for k, i in enumerate(mine):
            self.progress(ctx, k, len(mine), f"scene {i + 1}: {props['scenes'][i]['layout']}")
            path = work / f"scene-{i:02d}.mp4"
            hf.render_scene(props["scenes"][i], path, size[0], size[1], work / f"scene-{i:02d}")
            out.append({"scenes": [i], "path": str(path)})
        self.progress(ctx, len(mine), len(mine), "done")
        return out


class RemotionFramesAgent(FramesAgent):
    id = "data_frames"
    title = "Remotion Producer"
    name = "Plot"
    role = "Draws the scenes with data (diagrams, request flows, step-by-step traces, code and lists) with Remotion: React animation."
    engine = "remotion"

    def mine(self, ctx, scenes):
        taken = set((ctx.outputs.get("text_frames") or {}).get("scenes") or [])
        if not taken and not hf.available():   # HyperFrames will draw the word scenes: Remotion does the rest
            taken = {i for i, s in enumerate(scenes) if hf.engine_for(s) == "hyperframes"}
        return [i for i in range(len(scenes)) if i not in taken]

    def draw(self, ctx, props, mine, work, size, fmt):
        problems = rm.problems(self.cfg(ctx))
        if problems:
            raise video_mod.VideoError("; ".join(problems))
        root = rm.project_dir(self.cfg(ctx))
        rm.install(root, log=lambda m: ctx.run.event(self.id, "install", m))
        groups, out = [], []
        for i in mine:   # runs of neighbouring scenes are drawn in one go (a diagram keeps its boxes from scene to scene)
            if groups and groups[-1][-1] == i - 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        done = 0
        for n, g in enumerate(groups):
            self.progress(ctx, done, len(mine), f"scenes {g[0] + 1}-{g[-1] + 1}: {', '.join(props['scenes'][i]['layout'] for i in g)}")
            path = work / f"run-{n:02d}.mp4"
            pj = work / f"props-{n:02d}.json"
            pj.write_text(json.dumps(dict(props, scenes=[props["scenes"][i] for i in g]), indent=1))
            rm._run(["npx", "remotion", "render", "src/index.ts", "Video", str(path), f"--props={pj}", "--codec=h264", "--crf=18",
                     "--log=error"], root, "Remotion render")
            out.append({"scenes": g, "path": str(path)})
            done += len(g)
        self.progress(ctx, len(mine), len(mine), "done")
        return out


class RemotionAgent(VideoAgent):
    """The Video Composer (id media): joins the clips both engines drew."""
    title = "Video Composer"
    name = "Splice"
    role = ("Joins the HyperFrames and Remotion clips in scene order, lays the recorded voice under them, makes the thumbnail "
            "and checks the finished file.")
    renderer = "remotion"

    def run(self, ctx, guidance):
        self._cfg = {"remotion": ctx.cfg["video"]["remotion"]} if ctx.cfg["video"].get("remotion") else {}
        return super().run(ctx, guidance)

    def thumbnail(self, script, kicker, handle, path):
        try:
            return rm.thumbnail(script, path, self._cfg)
        except video_mod.VideoError as e:
            raise AgentError(f"drawing the thumbnail failed: {e}")

    def render(self, ctx, scenes, audio, out_path, work, kicker, handle):
        clips = []
        for step in FRAMES:
            clips += (ctx.outputs.get(step) or {}).get("clips") or []
        clips.sort(key=lambda c: c["scenes"][0])
        covered = sorted(i for c in clips for i in c["scenes"])
        if covered != list(range(len(scenes))):
            raise AgentError(f"the clips cover scenes {covered}, not all {len(scenes)}")
        engines = sorted({ctx.outputs[s]["engine"] for s in FRAMES if ctx.outputs.get(s)})
        ctx.run.step(self.id, engine=" + ".join(engines), progress=0, detail="joining the clips")
        ctx.run.event(self.id, "join", f"joining {len(clips)} clip(s) from {' and '.join(engines)}")
        try:
            props, lengths = rm.build_props(scenes, ctx.video["format"], audio)
            work.mkdir(parents=True, exist_ok=True)
            fitted = []
            for n, c in enumerate(clips):
                f = work / f"fit-{n:02d}.mp4"
                rm._fit(c["path"], f, ctx.video["format"])
                fitted.append(f)
                ctx.run.step(self.id, progress=round(80 * (n + 1) / len(clips)))
            video_mod.assemble(fitted, lengths, audio, out_path)
            info = video_mod.probe(out_path)
        except video_mod.VideoError as e:
            raise AgentError(f"joining the video failed: {e}")
        ctx.run.step(self.id, progress=100, detail="video ready")
        return ({"seconds": info["seconds"], "width": info["width"], "height": info["height"],
                 "extra": {"engines": engines}}, self.renderer)
