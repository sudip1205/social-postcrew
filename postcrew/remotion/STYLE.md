# The look of a Postcrew video

This is where the look of a video is defined. Every scene, in both engines (Remotion and HyperFrames), follows it, so a video looks
like one piece. Change a rule here, then change the code that draws it (the places are listed at the end).

## Principle

Professional and calm, not casual or trendy. A flat page, three colours with fixed jobs, large clear type, thin lines, slow movement. Nothing
decorative: no coloured or animated backgrounds, no glow, no gradients, no bouncing, no icons for decoration. Colour marks what the viewer
should look at (the key word, the active box, the pointer) and nothing else.

## Colour (render/looks.py)

Two pages, chosen per app in Settings > YouTube > Video look (`video.look`): **auto** (the default) uses the white page for a vertical video and
the black page for a wide one; **paper** or **ink** force one. The colours come with every render (`props.theme`), so both engines and the
thumbnail always match.

| | white page (paper) | black page (ink) |
|---|---|---|
| page | `#F5F2EB` | `#0D0D0D` |
| headings and text | `#424242` | `#C7C7C7` |
| accent: rules, arrows, the active box, pointers, numbers, code keywords | `#279CF5` blue | `#24C1FF` cyan |
| highlight: the key word of a headline, the last word of the closing card | `#FA7900` orange | `#FA7900` orange |
| positive: what was found or went right | `#068200` green | `#FA7900` orange (no green on black) |

A colour that is not in this table does not belong in a video. To add a look, add one entry to `LOOKS` in `render/looks.py` and its name to the
lists that check `video.look` (`workspace.py`, `platforms.py`) and to the Settings select. No scene code changes.

## Type

Inter (bold for headlines, semibold for text), JetBrains Mono for numbers, labels and code. Both ship in `render/fonts`.
Headlines are tight (-0.028em) and large: 132 px opening card, 98 px statement in a vertical video (112 and 86 in a 16:9 one).
Text 52-62 px vertical, 40-42 px horizontal. Captions 52 px (40 px), plain text, no box.

## Layout

A vertical video keeps 96 px at the sides, 170 px at the top and 400 px at the bottom (the captions live there); a 16:9 one 150 px at the
sides. Content is left aligned. The heading of a scene is small, with a short accent rule under it. Dividers are 2 px rules.

## Motion

- One easing for everything: it starts fast and settles slowly (`cubic-bezier(0.16, 1, 0.3, 1)`, "expo out"). No springs, no overshoot.
- Slow: a move takes 0.9 to 1.4 seconds. Headlines rise out of a mask one word at a time (0.14 s apart). Rules draw from the left.
- Content fades in over 0.7 s, and the page pushes in by 1.4% over the scene, so it is never quite still.
- Things appear when the voice says them (Python works the times out from the recording). Nothing loops.
- Every scene ends 0.6 s after its voice; the closing scene starts with one second of silence.

## The scenes

| Layout | Engine | How it looks |
|---|---|---|
| title | HyperFrames | Accent rule, then a very large headline; the longest word is in the highlight colour (orange). The narration is the introduction. |
| statement | HyperFrames | The same, smaller. |
| closing (last scene) | HyperFrames | A rule draws in the silence, then "Like", "Comment", "Share" appear one by one as they are said, each with a divider. |
| points | Remotion | Numbered rows (01, 02...) separated by thin rules, each when the voice names it. |
| code | Remotion | A surface card with line numbers; lines appear one by one; keywords in the accent colour. |
| diagram, flow | Remotion | Outlined boxes, thin lines that draw, numbered labels; in a flow the active box has the accent outline and a dot travels. |
| trace | Remotion | Outlined cells, pointers as accent triangles, the note below, memory as outlined chips. |

## The thumbnail

1280x720, in the look of the video. A few very large words (the script's `thumbnail_text`, which finishes the title instead of repeating it) with
the key word in orange, a blue rule, the topic in a quiet colour, and a picture drawn from the video's own content: its first diagram or
request flow (the box named in the title is outlined in orange), else its first trace (the array, the answer marked), else its first code.
No image model is involved; a video with none of these gets a type-only thumbnail. `thumbnail()` in `render/remotion.py`, `src/Thumbnail.tsx`.

## Where it is drawn

- Colours: `postcrew/render/looks.py`
- Remotion scenes: `postcrew/remotion/src/Video.tsx` (preview with `npm run studio` in this folder), thumbnail `src/Thumbnail.tsx`, tokens `src/theme.ts`
- HyperFrames scenes: `scene_html()` in `postcrew/render/hyperframes.py`
- The script (introduction, closing scene, tone): `postcrew/prompts/youtube/writer.md`
