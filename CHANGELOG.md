# Release notes

## 0.2.0: YouTube, per-app settings and a faster Studio

### New
- **Multiple apps.** LinkedIn and YouTube each have their own schedule, planning, topics, publishing settings and crew run.
  Frequency can be weekly, every N days or a list of dates, with a time per weekday or per date.
- **YouTube crew.** Script Writer, Editor, Voice (ElevenLabs), Video Producer and Publisher. Scripts are checked and reviewed
  like posts (length against words per second, scenes, title, description, tags). Voice and video are only made after the
  Editor passes, so a rejected script costs no voice characters. Shorts (9:16, up to 60 s) and long videos (16:9).
- **Official YouTube upload.** OAuth from the Studio, resumable upload, thumbnail, scheduled publishing, practice mode.
- **Bring your own.** Upload your own script, voice or finished video for any date; they are checked, and a script is still
  reviewed.
- **Diagram scenes.** Boxes and arrows that build up while the voice explains them, for system design, architecture
  components, cryptography and algorithms. In your own script: `flow: Client > Gateway > Service`.
- **Blackboard renderer and the Chalk agent.** Draw-and-explain videos: the voice is recorded first, then each stroke is drawn
  when the narrator says it (word times are estimated from the text). Chosen per app or per topic. Needs only Pillow and ffmpeg.
- **Animation MCP option.** Optionally render scenes with an MCP server; falls back to the built-in renderer.
- **Ideas with context.** `Title :: context` ideas (up to 600 characters) and per-topic context and planning notes now reach the
  planner and the script writer.
- **New Studio design.** The Studio follows a saved Stitch design (icons, colour-coded status chips, tooltips), built without a
  JavaScript build step. `scripts/stitch_sync.py` and `scripts/stitch_check.py` keep it faithful.

### Changed
- **Fewer tokens per piece.** Anthropic prompt caching, cache-aware cost, per-run token accounting and an Editor that stops
  re-reading once a read fails.
- `video.renderer` accepts `ffmpeg`, `blackboard` or `mcp`; a topic may set `renderer` and its own `format` / `target_seconds`.
- The Studio stylesheet `style.css` is replaced by `studio.css` and a compiled `tailwind.css`.

### Known limits
- ElevenLabs, the YouTube upload and a real animation MCP server have only been tested with fakes.
- Unverified Google apps upload as private until Google audits them; uploads share a daily quota.
- Blackboard timing inside a scene is estimated, not read from the voice service. Very long videos render slowly.
- The hand-written chalk font is used when the system has one (Chalkboard, Marker Felt); otherwise Inter Bold.
