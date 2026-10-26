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
