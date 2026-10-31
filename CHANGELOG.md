# Release notes

## 0.2.0: YouTube, per-app settings and a faster Studio

### New
- **Video lengths: Shorts 50 to 100 seconds, long videos at least 5 minutes.** A Short is never planned shorter than 50 seconds (an assigned Short used to be 45), and the writer must fill at least 90% of the shortest allowed length; a long video is never shorter than 5 minutes. Settings: Short 50-100 s, Long 5-30 min. A Short made earlier with the old length is corrected when its plan is next assigned.
- **Bigger diagrams, and the mistake is shown.** In a wide video, boxes are larger (up to 340×150) with the label on two lines at up to 48 px, and arrow labels are bigger. The common-mistake scene must now be a picture (a flow or diagram where the wrong path goes wrong and then the fix, or code with the wrong line and the right one), never a list; the Editor checks it.
- **Storyboards that follow the voice.** A script is sent back unless it has a new picture every few seconds: no scene may talk for more than 16 seconds in a long video (11 in a Short) on one picture, every box and point on screen must be said by the voice in that scene, and no more than two words-only scenes may follow each other. The writer is told to plan shots first (a four-minute video has 20 to 28), and the Editor checks the same list. The earlier video had 9 scenes of 30 to 46 seconds each.
- **A voice of your own, ready to use: Kokoro.** `scripts/kokoro_server.py` runs Kokoro (free, Apache-2.0, runs on the CPU) as an OpenAI-style voice server. Set `video.voice.provider` to `openai-compatible` (the settings check now accepts it; it was refused before). See the header of the script.
- **Every video follows one story.** Each scene now says which part it is, and a script is sent back to the writer unless it has, in order: an **introduction that states the problem**, the **idea (the solution)**, a **worked example**, **one common mistake to avoid**, then the closing card. A video can no longer start on a diagram or the solution. (Scripts you write yourself are not checked.)
- **The Editor checks the story before approving.** Its checklist now has the introduction (problem), solution, working example, common mistake and closing card, plus a few voice-smoothness rules, and the app also checks the parts itself: a script missing one is sent back whatever the reviewer scores. The reviewer sees each scene's part.
- **No abrupt start.** The first picture is on screen 0.7 s before the voice begins.
- **Pauses: up to five takes, and a retry carries on.** A scene whose pause is still wrong after its takes no longer passes silently: the voice step is retried, recording more takes from the best one so far (up to five in all), before the video is accepted.
- **Several plans on one day (up to 5).** Assign more than one plan to a day with "+ Add one more". The scheduled run still makes one post a day, from the day's current plan (the first one still waiting, written ones first), chosen when it runs, so changes to the day are picked up. For more in one day, press **Create now** on a plan in the calendar: it makes the next plan of that day, one at a time. When a plan is published it is struck out in the list and leaves the calendar; the next plan on that day becomes current, and you can add one more.
- **Pauses that sound like a person.** Found in a real video: a sentence that began with an acronym or a number ("RAG often wins...") got no pause before it, because the app only added one when the next word started with a capital, and commas were only about 0.3 s. Now every sentence end is paused, the slow pace stops 0.4 s at a comma, and every scene's recording is checked against its punctuation with ElevenLabs' own word times: a scene with a missing or misplaced pause (even a stop inside a phrase) is recorded again, up to three takes, and the best is kept (about 35% more characters on the scenes that need it). Each scene is told what comes before and after it so the intonation carries across the join, and the writer is told to avoid inserted phrases between commas ("documents in, suits...").
- **Other voice tools.** A voice server of your own (Chatterbox, Kokoro, Orpheus, anything with an OpenAI-style `/v1/audio/speech`) can replace ElevenLabs: set `video.voice.provider` to `openai-compatible`. See docs/video-and-voice.md for the models and their licences.
- **Colours by page, a picture on every thumbnail.** On the white page headings are `#424242` with blue `#279CF5`, orange `#FA7900` and green `#068200`; on the black page headings are `#C7C7C7` with cyan `#24C1FF` and orange `#FA7900`. A vertical video uses the white page and a wide one the black page unless Settings > Video look says otherwise. Every thumbnail now carries a picture drawn from its own video (its request diagram with the box named in the title outlined, its array, or its code), a few very large words and the topic. Voices are brought to -14 LUFS (they were about -20, too quiet).
- **Found by more people.** Titles lead with the phrase people search for; tags are ordered by importance and kept within YouTube's limits (13 to 15); descriptions open with the promise in the first 150 characters and end with three hashtags; long videos get real chapters worked out from the scene lengths. The Script Writer's instructions now cover all of this. (Whether a title is "trending" cannot be known without YouTube's own analytics: the writer is asked for the exact phrases people type, not for guesses about trends.)
- **A daily clean-up.** Every day at 03:30 everything older than 30 days is deleted from the workspace: run folders, frames, videos, pictures in media/, the voice cache, day briefs and old config backups. Never the settings, secrets, history, queue or state, and never anything a post still waiting in the Queue uses. Settings: `cleanup.enabled`, `cleanup.keep_days`, `cleanup.time`. `python3 -m postcrew clean --dry-run` shows what would go, and `--videos` clears every finished video and frames folder at once.
- **A calm, professional look for videos.** The coloured animated backgrounds are gone. Videos are now drawn on a flat page, off-white (**Paper**) or black (**Ink**), chosen in Settings > YouTube > Video look, with one accent colour used only for what is being explained. Large Inter type rises out of a mask one word at a time, thin rules draw themselves, the pace is slow and eased with no bouncing, and captions are plain text without a box. Both engines (Remotion and HyperFrames) and the thumbnail read the same look (`render/looks.py`), and the rules are written down in `postcrew/remotion/STYLE.md`.
- **An introduction and a closing scene.** The first scene is now a spoken introduction (the problem, what you will understand by the end, why it matters), and the tone is composed and professional, not casual. The video ends with its own closing card, "Like · Comment · Share", that appears one second after the last point, each word as it is said. The closing line defaults to "If this was useful, please like, comment and share it with someone who would find it helpful."; change it in Settings. A calmer gap (0.6 s) follows every scene in every renderer, and captions are six words at a time.
- **The quality check no longer calls a dark page a black frame.**
- **Open the Studio to your local network.** `python3 -m postcrew serve --lan` (or `--host <address>`) lets other computers on your network use the Studio, for example from a lab server. It stays on this computer only unless you ask. On the network it needs an access token: the server prints a link ending `/?token=...` that opens the Studio and keeps you signed in with a cookie; the token is made once and kept in `studio-token` in the workspace (or pass `--token` / `$POSTCREW_TOKEN`). Writes must come from the page the Studio served. LinkedIn and YouTube sign-in still return to localhost, so connect those accounts on the server itself or through an SSH tunnel.
- **A monthly plan you assign by hand.** Settings > Topics is now a list of one-line topics per app (LinkedIn and YouTube): no details, add as many boxes as you like and save. On the 1st of every month Postcrew writes 10 related plans for each topic, with the context, research topics, a real-world example and the takeaway. They are not put on days: the Plan page is a month calendar plus the list of generated plans, and you assign each plan to a date (for YouTube also Short or Long). Only assigned days get a post. Published plans stay listed, struck through, and are never planned again; no plan repeats another or a published post. Topics changed in the middle of a month are used for the next month's plan (or press Generate plan). The weekly cadence, one-off dates and the weekly planner are gone from Settings; an existing weekly schedule is switched to assigned dates.
- **Remotion is now the video renderer.** Every YouTube video is drawn by Remotion (React) by default: title, statement, points, code, diagram, flow and trace scenes, timed to the recorded voice, with captions that follow the words. Needs only Node.js 18+; the first run installs the project (`postcrew/remotion`) and Remotion fetches its own browser. The thumbnail is drawn by the same project. The picture is made by three steps you can watch in the Workflow view: **HyperFrames Producer** (HeyGen, HTML + GSAP: the opening card and big statements, with drifting colour, blur-in words and a highlighted key word), **Remotion Producer** (diagrams, flows, traces, code, lists) and **Video Composer** (joins the clips in scene order, lays the voice under them, makes the thumbnail). Each drawing step shows its engine and a live progress bar; if HyperFrames cannot run, Remotion draws every scene. No watermark, handle or brand text is drawn on the picture or thumbnail. The older renderers stay available per app or per topic in Settings.
- **Hooks agent: a quality gate for every video.** A new step ("Hook") looks at the finished video before it is queued, with no AI, in
  seconds: sound where the voice should speak (missing sound, long silences, wrong loudness, clipping), the voice against the
  punctuation and the words, and the frames (black frames, a picture frozen for ages, an empty scene, things drawn at the edge).
  For an explainroo video it fixes only what is wrong, once: a scene with missing sound is recorded again, a scene with an empty or
  crowded picture gets one scoped round from the picture agent, then it renders again. A fault it cannot fix does not fail (and
  re-run) the whole video: the video is held for your approval with the findings, whatever the approval setting.
- **Cheaper production.** A retry of the video step keeps the pictures already drawn when the script is the same; fix rounds name the
  scenes to change and leave the others alone; the picture agent's second look is off by default because the Hooks agent checks the
  frames for free (turn it on in Settings if you want it).
- **The voice stops where the punctuation says.** Measured on real ElevenLabs output: a comma could run on with no pause (0.0 s), and a
  misplaced "..." stopped the voice in the middle of a phrase for 0.6 s. Now clause commas get a small break, list items keep the
  voice's own breath, sentence ends and "..." beats keep theirs, and the writer is told to put "..." only after a complete sentence
  (the checks send a script back for one in the middle of a phrase). After the voice is recorded the Explainroo Producer listens
  (explainroo aligns every word): a scene whose stops are in the wrong places is recorded again with another seed, up to twice.
- **Space and spacing in Explainroo videos.** The agent is told the free area in pixels and must use all of it; explainroo's check now
  also reports texts closer than 28 px, content that stops short of the free area, text under 44 px on a phone and a scene that
  fills too little of the height, and the agent fixes them before the render. Subtitles default to the very bottom (88%).
- **Nothing is left for the voice to guess.** Before narration goes to ElevenLabs, every symbol, number and acronym is written out as the
  words to be said (`postcrew/speech.py`): "O(n^2)" becomes "O of n squared", "9 - 7 = 2" becomes "nine minus seven equals two",
  "95%" and "$4.50" and "20ms" become words, acronyms are said the way people say them (A P I, sequel, cube control for kubectl) and
  unknown ones are spelled letter by letter. Following ElevenLabs' guidance that too many break tags cause artifacts and noises, at most
  three pauses are added per request.
- **Unspeakable text is caught.** The writer's automatic checks send a script back for code, identifiers, addresses, emoji, lone letters,
  words with no vowels or mixed letters and digits; the Editor sees what the voice will actually be given and has a new red flag,
  `unpronounceable`, for anything a voice could not say.
- **Closing line in every video.** The writer ends each video with a call to action ("If you like this kind of content, please like,
  comment and subscribe. And if you don't like it, definitely tell me why in the comments..."); the checks send a script back without
  it. Edit or switch it off in Settings > YouTube > Closing line.
- **More room at the edges, subtitles lower.** Pictures stay further from the sides of the frame and the subtitles sit near the bottom
  (adjustable per Settings > YouTube > Explainroo). Explainroo has no such setting, so a small patch
  (`postcrew/tools/explainroo-layout.patch`) is applied to your install automatically.
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
