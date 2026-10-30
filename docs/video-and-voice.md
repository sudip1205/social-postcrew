# YouTube videos: script, voice and video

## How a video is made

The YouTube crew is the LinkedIn crew with a different back half. The same Supervisor (Orion), Topic Scout, Researchers and
writer team work on it; the writers become the **Script Writer**.

```
Aegis (credentials) > Nova (topic) > Ada · Ravi (research) > Script team > Quinn (Editor, x3) > Voice > Video > Echo (upload)
```

1. **Script.** Title, description, tags, thumbnail text and the scenes: what the voice says and what is on screen
   (a title card, one big statement, up to five points, or a short correct snippet of code). The script is checked automatically
   (the words must fit the length, 2.5 words a second; the scene count; title, description and tag limits; no filler opener,
   no web address read aloud, code that parses, no invented experience, no blocked phrases), pre-reviewed, polished and then
   scored by the Editor exactly like a post: three reads, the worst counts, exact fixes go back to the writer.
2. **Voice.** Only after the script has passed, each scene is read with ElevenLabs. Clips are cached by text and voice, so
   running the same script again costs nothing, and a script that is sent back never spends a character.
3. **Video.** Slides, captions and the voice are put together locally (Pillow and ffmpeg), plus a 1280x720 thumbnail.
4. **Queue and upload.** The video waits for your approval, or goes out at its time unless you veto it, like a LinkedIn post.

A **rehearsal** (Run the crew now > Rehearsal) runs everything except the voice (no characters are spent) and the queue.

## Short or long, and how long

Settings > Apps & Schedules > YouTube > **YouTube video settings**:

| Setting | Meaning |
|---|---|
| Video type | **Short**: vertical 1080x1920, 15-60 s. **Long**: 16:9 1920x1080, 1-30 minutes. |
| Duration | About how long. The script's word budget is this x 2.5 words a second (a 45 s Short: 78-112 words). |

The kind of video can be set at four levels, the latest winning: the app's default, a **topic** (Format and Length in the topic
card), one **plan day** (Plan > the day's Format and Length), and one **run** (`postcrew run --platform youtube --format long
--seconds 480`, or the Studio's Run now).

## Your idea for each video

Every video starts from an idea exactly like a LinkedIn post: list ideas under a topic (Settings), write or ask for a topic and
angle for each day in **Plan** (and an optional brief), or let the Topic Scout choose.

## Voice with ElevenLabs

Credentials > ElevenLabs: paste your API key (it is write-only). Settings > YouTube video settings: pick a voice (the list is
loaded from your account) and press **Play sample**. The free ElevenLabs plan has a monthly character allowance and its terms
limit commercial use: check your plan. Characters are only spent on scripts that passed the Editor.

### Pauses that sound like a person

The voice is recorded one scene at a time, and each recording is checked against its punctuation using the voice's own word times: a sentence
end must be followed by a stop (at least 0.4 s at the slow pace), a comma that ends a clause by a stop of at least 0.2 s, and no stop may fall
inside a phrase. A scene that fails is recorded again (up to three takes) and the best take is kept; the run log says how many characters the
re-takes used and, if a pause is still wrong in the best take, which one. Each scene is also told what comes before and after it, so the
intonation carries across the join. The slow pace stops 0.4 s at a comma and 0.35 s after a sentence (the voice adds its own natural stop).
A sentence that starts with an acronym or a number ("RAG often wins...") gets its pause like any other.

### Another voice tool instead of ElevenLabs

ElevenLabs is the default, but any server that speaks the OpenAI speech API (`POST /v1/audio/speech`) can be used, which is how most free local
models are served. In `config.json`, under `platforms.youtube.video.voice`:

```json
"voice": {"provider": "openai-compatible", "base_url": "http://localhost:8880/v1", "model": "kokoro", "voice_id": "af_bella", "speed": 1.0}
```

Leave `provider` out (or `"elevenlabs"`) to go back. A key, if your server wants one, goes in `secrets.json` as `voice_api_key`. `python3 -m postcrew doctor`
shows the server address. A local server decides for itself how punctuation sounds, so Postcrew cannot check the pauses or re-take a scene
with it (it only writes numbers and symbols as words first); listen to a sample before you switch.

Free models worth trying on a machine with a GPU (licences checked against each model card, but check again before you rely on one: some
free models forbid commercial use, which includes a monetised channel):

| Model | Size | Licence | Server that speaks the OpenAI API | Notes |
|---|---|---|---|---|
| Chatterbox (Resemble AI) | 0.5B | MIT | [Chatterbox-TTS-Server](https://github.com/devnen/Chatterbox-TTS-Server) | Clones a voice from about 5 s of audio; an "exaggeration" control for expression. The first to try for a human sound. |
| Kokoro | 82M | Apache 2.0 | Kokoro-FastAPI (`ghcr.io/remsky/kokoro-fastapi-gpu`, port 8880) | Fast and light, runs on a CPU; English is its strength. A good, steady baseline. |
| Orpheus 3B (Canopy Labs) | 3B | Apache 2.0 (the weights follow Llama terms: read them) | [Orpheus-FastAPI](https://github.com/Lex-au/Orpheus-FastAPI) | Emotion tags, 24 voices; heavier. |
| Qwen3-TTS | 1.7B | Apache 2.0 | (check its repository) | Many languages, voice cloning. |

Not for a monetised channel: XTTS v2 (non-commercial licence), F5-TTS weights, Fish Speech and Voxtral (CC BY-NC). VibeVoice (MIT code) is listed by Microsoft
as research only.

## Use your own script, voice or video

On a YouTube card in the Queue (or on a day in Plan): **Use my own ...**. Files are kept per date and used by the next crew run
for that date.

| You upload | What happens |
|---|---|
| **Script** (`.txt` or `.md`) | Parsed into scenes (below). The crew only completes missing metadata; the Editor still reviews it. A Short must fit in a minute. |
| **Voice** (`.mp3`, `.wav`, `.m4a`) | Replaces ElevenLabs. The voice's length sets the length of the video. |
| **Video** (`.mp4`, `.mov`) | Used as it is, after checking format, length and audio. The crew writes the title, description and tags. |

Script format: lines before the first blank line may set `title:`, `description:`, `tags:` (comma separated) and `thumbnail:`.
Then scenes separated by blank lines. In a scene, `on-screen: text` sets the big text, lines starting with `- ` become points,
a fenced code block becomes a code scene, and everything else is what the voice says.

```
title: Why your JWTs leak
tags: jwt, security, auth

Your login token can leak from a log file.
on-screen: Tokens in logs

Most teams log every request. That includes the header.

Here is the fix:
- Strip the header
- Log a hash instead
```

## Animated video with an MCP server

By default scenes are slides with a slow zoom and captions, which needs nothing but ffmpeg. For richer animation you can let an
**animation MCP server** draw each scene: set the renderer to *Animation MCP server* in Settings and give the command that starts
the server (stdio), its arguments, and the name of the tool that renders a scene. Postcrew starts the server for the run, calls
the tool once per scene and uses the clips it returns; if the server fails, the built-in renderer takes over.

The tool is called with these arguments (so a thin wrapper around any renderer will do):

```json
{"scene": {"layout": "statement", "on_screen": "...", "items": [], "code": "", "language": "", "narration": "...", "seconds": 7.2},
 "format": "short", "width": 1080, "height": 1920, "seconds": 7.2, "output_path": "/path/to/clip-01.mp4"}
```

It must write an `.mp4` at `output_path` (or return the path of one in its text result). Good fits are MCP servers built on
programmatic animation tools such as Remotion (React-based video) or Manim (math and diagram animation), or a headless
browser that renders HTML/CSS scenes. Check each server's own documentation and licence, and run only servers you trust: they
run on your computer with your permissions.

Needs: Python 3.9+, Pillow, and ffmpeg (`brew install ffmpeg` / `sudo apt install ffmpeg`).

## Explainer channels: system design, components, cryptography, algorithms

Videos that teach a flow work best as **diagram scenes**: boxes and arrows that build up while the voice explains. The
writer uses them when a topic's brief and context say the video is a visual explainer. In your own script file, write
`flow: Client > API Gateway > Service` inside a scene.

In **Settings > Apps & Schedules > YouTube > Topics**, give each kind of video:

- **Name and brief**: what one video of this kind contains (hook, diagram, trade-off, next step).
- **Your ideas** (one per line): `Title :: context`. The title is what the planner matches against videos already made; the
  words after `::` (up to 600 characters in all) tell the planner and writer what to cover, e.g.
  `Circuit breaker :: closed, open, half-open; fail fast; Resilience4j`.
- **About this type of topic (context)**: who watches, what to always include (trade-offs, complexity), what never to claim.
- **How to plan it**: how the Week Planner should pick and vary topics.
- **Format and length**: Short (15-60 s) or long (60 s-30 min) per topic.

## Blackboard "draw and explain" videos

Set **Video renderer** to *Blackboard* in Settings > Apps & Schedules > YouTube (or give one topic `"renderer": "blackboard"`
in `config.json`) and the **Blackboard Producer** (agent "Chalk") replaces the Video Producer.

Order of work: the script passes the Editor, then the **Voice** step records every scene (ElevenLabs, or your own voice file),
then Chalk draws. Every scene is exactly as long as its recording. Inside a scene, the narration's word times are estimated
(letters per word, a pause at each comma and full stop) and each thing on the board starts when the narrator says its name:

- the heading is written first, then boxes (when their name is said), arrows (when their label or target is said), edge labels;
- points are ticked and written as spoken; code is written line by line, spread over the scene;
- a chalk stick follows the stroke; captions are timed to the same words.

Write narration that names things in the order they are drawn ("A client sends a request. The load balancer ...") and use
`diagram` scenes; the writer is told this automatically for blackboard videos. Without a voice (rehearsal) the pace is the
word count. The hand-written look uses Chalkboard / Marker Felt when the machine has them (any machine: Inter Bold instead).
Word times are estimates, so a stroke can be a fraction of a second early or late; they are not read from ElevenLabs.

## Teaching tone and pauses

Scripts are written like an online lesson: simple English, one idea per sentence (20 words or fewer, 25 at the very most), the
real technical names used consistently, and **every uncommon term explained in one plain sentence the first time it is said**.
The order is what it is, why it exists, how it works step by step, an example, the common mistake. The Editor scores this under
"clarity" and "tone", and an automatic check sends a script back if any sentence is longer than 30 words.

Pauses are made from punctuation, so the script itself stays clean text (captions, word counts and timing are unaffected):

| In the script | What ElevenLabs gets |
|---|---|
| a full stop, question mark or exclamation mark | a 0.35 s pause after the sentence |
| a comma | a short breath (the voice's own) |
| `...` (the writer uses at most one per scene, after a question, a new term or before the key point) | a 0.8 s pause |

The pause tags (`<break time="0.35s" />`) are added only when the voice is requested, and the same text is never sent twice
(cached audio is reused). Models that do not understand break tags (`eleven_v3`) follow the punctuation instead. Pauses add a few
seconds to a Short, so the Voice step still stops a Short that would run past 60 seconds and sends the script back to be shortened.
Writers are told not to write `[pause]` or `<break>` themselves; a script that does is sent back.

## The second Editor: does the picture go with the voice?

The first Editor reviews the **script**. Nothing used to look at the finished **video**. For blackboard videos the **Video Editor**
(agent "Cut", step *video_review*) now does, right after the video is drawn:

1. **Measures the sync.** It listens to each scene's recorded voice for the real pauses after sentences and lines the narration up
   with them, then compares when every box, arrow, bullet and line of code was drawn with when the narrator says its name. It
   reports things drawn more than a second late or 1.5 seconds early, things drawn that the voice never says, an explanation that
   jumps back to something already drawn, and stretches of seven seconds or more where the voice talks over an unchanging board.
   The result is a sync score out of 100.
2. **Fixes the order for free.** If the arrows or bullets are listed in a different order than the narrator explains them, they are
   put in the spoken order, with no AI call.
3. **Asks an AI reviewer.** It reads each scene's narration, what is drawn and the timeline, and may replace the graphics of the
   scenes that do not follow the voice (labels in the narrator's own words, arrows in spoken order, a busier or simpler board).
   A replacement that breaks a rule (for example a diagram with one box) is ignored.
4. **Draws only the changed scenes again.** The unchanged scenes keep their pictures, and the video is joined again.

**The voice is never made again.** The reviewer never sees the narration as something it can edit, and the redraw uses the audio
files the Voice step already recorded, so no ElevenLabs characters are spent. It runs at most two review rounds. If a mismatch is
still left, the video is queued anyway and the Workflow and the Queue show the score and what is left for you to judge.

Notes: it only runs for the blackboard renderer, and not when you supplied your own voice file (it cannot tell which scene is
which in one file). In a rehearsal there is no voice, so the timing is estimated from the word count and the score says so. The
check uses the pauses in the audio; it does not understand the words, so it trusts the narration text for what is said when.

## Explainer videos (the default look)

The default video style is the **Explainer**: a slow, clean animation on a dark screen, modelled on what the best system-design
channels do (KodeKloud and TechPrep, studied for this). It is drawn locally with Pillow and joined with ffmpeg; nothing else
to install. Pick the style in Settings > YouTube > Video renderer, or per topic with its **Video style** field.

What the style does, and how the agents are trained for it:

- **One picture that keeps growing.** Consecutive diagram scenes that share a box are drawn on the same canvas. The boxes of the
  scene before are already on screen and only the new boxes and arrows animate in. The writer is told to reuse the same box
  labels, add at most three new things per scene, and name each one in the narration at the moment it should appear.
- **Attention.** Each box pops in as its name is spoken; each arrow draws itself and a dot travels along it; the thing being
  explained glows (dashed outline) while the rest dims for a few seconds.
- **Icons.** Boxes carry an icon (client, phone, user, server, service, database, cache, queue, gateway, cloud, globe, lock, key,
  file, terminal). The writer picks one with `"Cache|cache"`; if it does not, one is guessed from the name.
- **Handwritten chapter titles** (2-4 words per scene, changing with the idea), a title card for the opening, a numbered card list
  for points, an animated editor for code with syntax colours.
- **Captions:** two to four words at a time on a highlighted bar, timed to the real voice.
- **Slow pace** (Settings > Pace, on by default): the script budget is about 2 words per second instead of 2.5, the voice
  pauses 0.6 s after a sentence and 1.2 s at a "...", and nothing is added faster than it is explained.
- **Shorts up to 3 minutes.** YouTube allows it, and these channels' Shorts run 1.5 to 3 minutes. A Short can be 15 to 180
  seconds (a long video 1 to 30 minutes).

The Video Editor (see above) checks explainer videos too: it measures every box and arrow against the voice and fixes the
graphics without making the voice again.

### Watch the example move: trace and flow scenes

Labels on boxes do not teach an algorithm or a system; watching real data move does. The explainer renderer has two scenes for that,
and the Script Writer is told to use them (and the Editor to ask for them when they are missing):

- **trace** (algorithms, data structures): an example array (`cells`) and the moves (`steps`). Each step says when it happens
  (`say`: two or three words of the narration), where each pointer is (`pointers: ["left=0", "right=3"]`, which slide smoothly to the
  next cell), which cells are being compared (`active`), ruled out (`out`) or the answer (`found`), the arithmetic or decision
  (`note`: "2 + 15 = 17, too big") and what is remembered (`memo`: a hash map or a target). Two Sum with two pointers is the model case.
- **flow** (system design, architecture): the `nodes` and `edges` of a diagram, but the edges are one concrete request in the order it
  travels, each with the real data on the wire ("Client > Load Balancer: GET /cart?user=42", "Database > Server 1: 3 items"). A dot
  carries the data along each arrow, and finished hops stay numbered on screen.

Steps are timed to the real voice like every other thing on the screen, so the Video Editor can check and fix them. Only the explainer
renderer draws them; the slide and blackboard renderers show the heading only.

### Explainroo: the video made by an open-source animation tool

[explainroo](https://www.explainroo.com) (MIT licence, runs on your computer) turns a `script.md` (the words) and a `scenes.js` (what
is drawn, each thing on a spoken word) into an MP4 with hand-drawn lines, 1,800 icons, charts, code that changes step by step, a camera
that follows the narration, sound effects and quiet music. Choose **Settings > YouTube > Video renderer > Explainroo** (or per topic).

Install it once, in its own folder, outside Postcrew:

```bash
git clone https://github.com/vincentsch/explainroo.git
cd explainroo && npm install && node bin/explainroo.js doctor --fetch   # about 400 MB of voice and timing models, once
```

Needs Node.js 20.11+, ffmpeg and Chrome. Then put the folder in `platforms.youtube.video.explainroo.path`. How a run goes: the Voice
step records the approved script with ElevenLabs, as usual; the **Explainroo Producer** gives each scene's recording to explainroo as the
narration, an AI agent (the same Claude Code login) writes `scenes.js` from the script's picture plan (the example array and its
pointers, the request and the data on each arrow) tied to the words that are spoken, Postcrew runs explainroo's own layout and timing
checks and sends every problem back to the agent, the agent looks at the contact sheet once, then it renders and verifies the file. The
words in `script.md` are checked against the approved script, so the picture agent can never change what the voice says. Settings:
`theme` (paper, clean, chalk, blueprint, midnight, editorial), `music`, `watermark` (explainroo asks you to keep its small credit),
`review`. The Video Editor step is skipped: explainroo does its own checks.

### The look of a video

Videos are drawn on a flat page: white for a vertical video and black for a wide one (**Settings > YouTube > Video look**: Automatic, or
force one). White uses `#424242` headings with blue, orange and green; black uses `#C7C7C7` headings with cyan and orange. The colours are defined in
`postcrew/render/looks.py` and the rules for type, layout and motion in `postcrew/remotion/STYLE.md`; add a look by adding one entry to `LOOKS`.
The first scene of every script is a spoken introduction and the last is a closing card ("Like · Comment · Share") that appears after one second of silence.

### Remotion (the default renderer)

Videos are drawn by [Remotion](https://www.remotion.dev) from the project in `postcrew/remotion` (set `video.remotion.path` to use your
own copy). Python works out when each box, arrow, bullet and step is said (from the recorded voice) and writes a props file; the
React scenes in `src/Video.tsx` only draw a frame for a given time; ffmpeg then lays the voice under the picture. The picture is three steps: the HyperFrames Producer (`text_frames`), the Remotion Producer (`data_frames`) and the Video Composer (`media`), each reporting its engine and progress to the Workflow view. No watermark or handle is drawn. The opening card and the big statements are drawn by [HyperFrames](https://hyperframes.heygen.com) (`postcrew/hyperframes`, HTML + GSAP, rendered by the `hyperframes` CLI) and joined with the Remotion clips; if HyperFrames cannot run, Remotion draws every scene. Run
`npm run studio` in that folder to preview and restyle the scenes. Needs Node.js 18+. Remotion is free for individuals and small
teams; a company above that size needs its licence.

### Going further: Manim, After Effects

I looked at what people use to make this kind of video. The built-in renderer is the practical, dependency-free choice. If you
want richer motion graphics later:

| Tool | Good for | Fit |
|---|---|---|
| **Manim** (Python) | Maths: equations, graphs, geometry | Good for algorithm and maths scenes; render a scene to a clip and use it as a clip. |
| **Motion Canvas / Revideo** (TypeScript) | Hand-tuned narrated explainers | Great with a human at the keyboard; weaker for unattended runs. |
| **After Effects + MCP** | Studio-quality motion graphics | Needs a paid Adobe licence and the app open with a bridge panel running; not suitable for an unattended pipeline. |

Sources: the Remotion, Manim and Motion Canvas comparisons and the After Effects MCP repositories listed in the pull request notes.
