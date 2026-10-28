"""Voice (YouTube): reads every scene's narration aloud with ElevenLabs. No LLM.

Runs after the Editor has passed the script, so no characters are spent on a script that is sent back. Each scene is a
separate request (so the video can time the picture to the voice), cached by text, voice and settings: re-running the same
script costs nothing. A rehearsal (dry run) never calls ElevenLabs. If the owner supplied their own voice file this step
is skipped and the Video step uses that file.
"""
from .. import assets as assets_mod
from .. import platforms
from .. import voice as voice_mod
from .base import Agent, AgentError


class VoiceAgent(Agent):
    id = "voice"
    title = "Voice"
    name = "Echo Voice"
    role = "Reads the approved script aloud with ElevenLabs, one clip per scene (cached, so re-runs are free)."
    uses_llm = False

    def applies(self, ctx):
        return "voice" not in assets_mod.find(ctx.ws, ctx.platform, ctx.day)   # the owner's own voice replaces this step

    def run(self, ctx, guidance):
        scenes = ctx.outputs["writer"]["scenes"]
        cfg = dict(ctx.cfg["video"]["voice"], pace=ctx.cfg["video"].get("pace", "normal"))   # slow pace: longer pauses
        if ctx.dry_run:
            ctx.run.event(self.id, "rehearsal", "rehearsal: no voice is generated (no ElevenLabs characters are spent)")
            return {"mode": "rehearsal", "files": [], "seconds": [], "total_seconds": 0, "characters": 0, "voice": "none"}
        key = ctx.ws.secrets().get("elevenlabs_api_key")
        if not key:
            raise AgentError("ElevenLabs is not set up: add your API key in Credentials, or upload your own voice for this "
                             "video", fatal=True)
        if not cfg.get("voice_id"):
            raise AgentError("choose a voice in Settings > Apps & Schedules > YouTube video settings, or upload your own "
                             "voice for this video", fatal=True)
        files, seconds, chars = [], [], 0
        for i, sc in enumerate(scenes, 1):
            try:
                r = voice_mod.cached_synthesize(ctx.ws.root, sc["narration"], cfg, key)
            except voice_mod.VoiceError as e:
                raise AgentError(f"ElevenLabs, scene {i}: {e}", fatal=e.kind in ("auth", "quota", "invalid"))
            files.append(r["path"])
            seconds.append(round(r["seconds"], 2))
            chars += r["characters"]
        total = round(sum(seconds), 1)
        ctx.run.event(self.id, "voice", f"{len(files)} clips, {total}s, {chars} characters", {"characters": chars})
        return {"mode": "elevenlabs", "files": files, "seconds": seconds, "total_seconds": total, "characters": chars,
                "voice": cfg.get("voice_name") or cfg["voice_id"]}

    def validate(self, ctx, out):
        scenes = ctx.outputs["writer"]["scenes"]
        if out["mode"] == "rehearsal":
            return []
        problems = []
        if len(out["files"]) != len(scenes) or any(s <= 0 for s in out["seconds"]):
            problems.append("a scene came back without audio")
        if ctx.video["format"] == "short" and out["total_seconds"] > platforms.SHORT_MAX_S + 0.5:
            problems.append(f"the voice-over runs {out['total_seconds']:.0f} seconds: too long for a Short (3 minutes). Shorten the "
                            f"narration by about {out['total_seconds'] - platforms.SHORT_MAX_S + 3:.0f} seconds of words")
        return problems

    def summary(self, out):
        return ("rehearsal: no voice generated" if out["mode"] == "rehearsal"
                else f"{len(out['files'])} clips, {out['total_seconds']:.0f}s, {out['characters']} characters ({out['voice']})")
