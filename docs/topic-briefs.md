# Topic briefs

A brief is the extra context you can attach to a day's topic (Plan > open the **Brief** box on a day), or load
for many days at once with `python3 -m postcrew plan-import FILE`.

## What it changes

| Part of the brief | Who uses it |
|---|---|
| Context, takeaway, tone, must include, avoid, question | Writers (the brief wins over the category brief) |
| Example + type (`scenario` or `incident`) | Writers build the post around it. A scenario is framed as illustrative ("Picture..."); an incident must be backed by verified sources, so the Researcher looks for primary sources |
| Pattern | Writers follow its beats: problem-story, how-it-works, before-after, myth-vs-reality, incident-lessons, decision-guide, walkthrough, checklist |
| References (https links) | The Researcher fetches them first |
| Visual: system-flow, Systems, Flow | Pixel draws an animated system diagram: real components with icons, messages travelling between them, state changes, an "on the wire" log and captions |
| Everything | Quinn (Editor) checks that the post follows the brief and that the post's steps use the animation's component names |

Numbers you write in the brief count as supplied facts for the number checks. Numbers on the animation must be in the post or the brief.

## Format

```
Topic: Why AI agents need their own token
Angle: one sentence
Category: briefed
Context: ...
Example: ...
Example type: scenario            (or incident)
Takeaway: ...
Pattern: before-after
Tone: ...
Must include:
- ...
Avoid:
- ...
References:
- https://...
Question: ...
Visual: system-flow               (or poster, none)
Systems:
- id | Label (max 16) | kind | note
Flow:
Scene: Before                     (optional, up to two scenes)
from > to | label (max 16) | request/response/data/token/event/attack/error | payload | caption
```

Component kinds: user, attacker, browser, mobile, service, api-gateway, load-balancer, database, cache, queue, idp,
vault, firewall, llm, agent, cdn, worker, storage, external.
Leave out Systems and Flow and the Visual Designer designs them from the post.

## Switching it on

* Category setting `briefing`: `owner` (use the brief as written), `auto` (Nova also fills missing fields; filled
  fields are marked generated and an invented example is always a scenario) or `off` (ignore briefs).
* Category `media: sysflow` always makes the system animation. In any other category a brief with
  `Visual: system-flow` does too; `Visual: poster` or `none` overrides the category.
* The new `briefed` category is ready for this. `plan-import --apply-schedule` also schedules the briefs' category on those weekdays.

`workspace/briefs/identity-ai-week.md` is a ready-to-load week; `sample_agent_spec.json` is the finished animation spec for Day 1.
Render a preview without the crew: `python3 -m postcrew.render.sysflow spec.json out.mp4`, or stills with `--stills DIR 1 6 12`.
