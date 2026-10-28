# Release notes

## 0.2.0: YouTube, per-app settings and a faster Studio

### New
- **Explainroo renderer.** Videos can be made by [explainroo](https://www.explainroo.com), an open-source tool that runs on your computer:
  hand-drawn lines, icons, charts, code, a camera that follows the narration, sound effects and quiet music. The approved ElevenLabs
  voice is used as its narration; an AI agent writes the pictures from the script's plan, explainroo's own layout checks are fed back
  until clean, the agent looks at each scene's last frame and fixes what is wrong, then it renders and verifies. Choose it under
  Settings > YouTube > Video renderer (or per topic). See docs/video-and-voice.md.
- **Less like a slide deck.** Boxes are drawn as solid 3D blocks that float gently; the blocks a scene will need are faintly outlined
  before they are named, so the screen is never empty; data dots keep flowing along every arrow; dust drifts and the camera pushes in
  slowly. Statement scenes get a large illustrated object, and bullet lists sit in the middle of the screen.
- **A more human voice.** ElevenLabs is asked for a less flat delivery (lower stability, some style), capitalised ordinary words
  ("UP", "NOT") are read as words instead of letters (real acronyms like API and TCP are still spelled out), and the writer is told to
  talk to one viewer with varied rhythm and small reactions. An algorithm video must contain a trace scene and a system-design video a
  flow scene, or the script is sent back.
- **Videos that show the example moving.** New `trace` scenes (an example array whose pointers slide, with the sum or decision for each
  step and a hash map of what is remembered) and `flow` scenes (one real request travelling between components with the actual data on
  each arrow). The writer prompt, the topic briefs, the Editor's rubric and the Video Editor all ask for them: an algorithm video must
  show the two-pointer pass on a real array; a system-design video must follow one request through the boxes.
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
- **Explainer renderer (new default).** A slow, clean animated explanation modelled on KodeKloud and TechPrep: one picture that
  grows across scenes, icon boxes that pop in as they are named, arrows that draw themselves with a travelling dot, the current
  thing glowing while the rest dims, handwritten chapter titles, caption chunks timed to the voice. The writer and the Editor
  are trained on this structure.
- **Slow pace setting** and **Shorts up to 3 minutes** (was 60 seconds).
- **Video Editor (a second review, after the video is drawn).** For blackboard videos the new step measures each box, arrow and bullet
  against the recorded voice (pauses in the real audio), fixes a different order for free, lets an AI reviewer replace graphics that
  do not follow the narration, and draws only the changed scenes again. The voice is never generated again. The Queue shows the
  sync score.
- **Animation MCP option.** Optionally render scenes with an MCP server; falls back to the built-in renderer.
- **Ideas with context.** `Title :: context` ideas (up to 600 characters) and per-topic context and planning notes now reach the
  planner and the script writer.
- **New Studio design.** The Studio follows a saved Stitch design (icons, colour-coded status chips, tooltips), built without a
  JavaScript build step. `scripts/stitch_sync.py` and `scripts/stitch_check.py` keep it faithful.

### Changed
- **Scripts that pass the Editor.** The Week Planner now knows how long each video is and plans one main idea per video (about one
  idea per 25 seconds) instead of bundling several subtopics. The writer is told the length is a hard limit and that the brief's
  beats are one sentence each in a Short; standard concepts need no source but are worded carefully, and examples are introduced
  as examples. The Editor judges a video brief as a guide (a short beat counts, no asking for words over the budget, layouts are
  the writer's choice) and flags `unsupported_claim` only for specific numbers, defaults and named-product behaviour.
- **Teaching tone.** Scripts are written like an online lesson: simple English, short sentences, technical terms used by their
  real names and explained the first time they appear. New automatic check: no sentence over 30 words.
- **Natural pauses for ElevenLabs.** Full stops, question marks and "..." become timed pauses (`<break>` tags) when the voice is
  requested; the script text stays clean.
- **Fewer tokens per piece.** Anthropic prompt caching, cache-aware cost, per-run token accounting and an Editor that stops
  re-reading once a read fails.
- `video.renderer` accepts `ffmpeg`, `blackboard` or `mcp`; a topic may set `renderer` and its own `format` / `target_seconds`.
- The Studio stylesheet `style.css` is replaced by `studio.css` and a compiled `tailwind.css`.

### Known limits
- ElevenLabs, the YouTube upload and a real animation MCP server have only been tested with fakes.
- Unverified Google apps upload as private until Google audits them; uploads share a daily quota.
- Blackboard timing inside a scene is estimated, not read from the voice service. Very long videos render slowly.
- The hand-written chalk font is used when the system has one (Chalkboard, Marker Felt); otherwise Inter Bold.
