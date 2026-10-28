# Where the Studio differs from the Stitch screens

Rule (stitch-ui skill): the Studio copies `design/stitch/*`. Only these differences are allowed. Keep this list current.

| Screen | Stitch shows | Studio does | Why |
|---|---|---|---|
| all | sample data (names, numbers, dates, "Claude 3.5 Sonnet", "+14% vs last month", "Agent Command") | real data from the API | the screens are mock-ups |
| all | Google Fonts / Tailwind / Material Symbols from CDNs | the same fonts, Tailwind and only the used icons, vendored in `static/` | the Studio is offline and has no external requests |
| all | Agent Command avatar in the top bar | omitted (no user accounts) | nothing to show |

## Per screen (written while converting; keep current)

### crew-credentials
# Crew and Credentials: deviations

No Stitch screen exists for either view. Both are derived from the shell, design.md and the Overview/Queue/Settings components
(page header with title and helper text, `card()`, `sectionHead()` tinted tiles, `chip()`, Recent-runs table style, Settings
"Connected apps" cards and toggles/inputs styling).

- Credentials: YouTube is a greyed dashed "Coming soon" card (same style as Settings > Connected apps), no controls.
- Credentials: form inputs use a Tailwind-forms style (slate border, violet focus ring); Stitch has no labelled text inputs.
- Crew: the old coloured legend dots now use the team gradient; "At risk"/"Working"/"On the bench" use chip().
- Behaviour and API calls unchanged from design/legacy/app.js (renderTeam, renderCredentials); secrets are never read back.

### overview
# Overview deviations from Stitch
- Header chip "Production Studio" shows the current app name; status line reflects real state (paused / running / on schedule) instead of "All 7 agent pods...".
- Stat cards: real values. Next post chip = real queue status; Connection card shows the LinkedIn credential state (YouTube: "connector soon"); Published card shows the real count and the approval mode instead of "+14% vs last month" / "On track".
- Target publication slot is a real date input; "Topic & Angle synthesis" is a Category select (the API takes a category, not a topic). "Estimated execution time / tokens" microcopy omitted (no real estimate).
- Added a Pause/Resume schedule button in the Run card header (existing behaviour from the old UI, not in Stitch).
- Coming up: next 7 calendar days from `upcoming`; days without a schedule are Rest cards. "All slots backed by Fact-Checking" omitted (not data). Summary shows only the current app.
- Run rows: Retry is disabled ("Coming soon", no retry API). Failed rows show Retry plus none other; running/other rows get Inspect log. Sub-line shows date/rehearsal/result, not model names. Footer shows the sum of listed runs' cost, not a billing-cycle total.
- Filter and Export CSV disabled ("Coming soon"). Sync Pipelines re-fetches data; Run now scrolls to the Run card.

### plan
# Plan deviations
- Day cards show real data only: app + topic-type label instead of "Short 45s" format chip (no format in /api/plan); no fake hook outline, "Locked by", render notes or agent captions.
- Editable days use inline inputs for topic/angle/brief (legacy editing kept) instead of static h3/p.
- Weekly Recap and Rest slots: generic text (no backend text). "Add slot anyway" disabled (Coming soon).
- Date navigator arrows, Quick drop idea, Export CSV: disabled (Coming soon). Preview notes / Unassign / "Added Nd ago" dropped (ideas are plain strings from config).
- Idea bank: filters by topic type; "Assign" and drag/drop fill the day's topic field (then Save plan). Assign picks the first day with an empty topic.
- App toggle in sub-header has no "N scheduled" counts. "Re-plan this week" = POST /api/plan/fill {replan:true}.

### queue
# Queue and Upload dialog: deviations from Stitch

- Disabled (title "Coming soon"): Pause Auto-Publish, Bulk Approve, card overflow (more_vert), table view toggle, "Veto window" countdown (not shown), Upload dialog drop zones, "Skip the Editor" toggle, "Use these files & update run" (no upload backend yet).
- "Let the crew make it", Cancel and X close the upload dialog.
- Not shown (no real data): author "Alex Rivera"/avatar, carousel slide mock, scene timeline, ElevenLabs voice pill, voiceover/video specs, "Drafted by ... using ...", "Quality Agent (Indigo Pod)" threshold text, "Veto window expiring" sort.
- Header pill says "N Awaiting approval" instead of "N Pending Veto Windows".
- Card shows the real post text and media (/media) in the preview frame; topic is the title.
- "Passed Quality Gates" = overall >= 80 and no red flags (else amber "Needs a look"); bars green >= 85, amber >= 70, red below.
- Brand hex colours replaced by ui.js APPS classes (app chip uses APPS.<app>.soft) and Tailwind palette classes (checker forbids hex in views). Invalid Stitch classes py-0.2 and shadow-xs dropped.
- Upload dialog zones show an empty "No file yet" state with the Stitch check rows as pending, instead of Stitch's sample files.
- Initial filter = the app chosen in the app switcher (mine()); "All" shows both apps. Edit is a modal (text, date, first comment) instead of in-card editing. Published list is restyled as a card/table with Tailwind.
- openUploadDialog(post, focus) takes an optional 2nd arg ("script"|"voice"|"video") to scroll to a zone.

### settings
# Settings (views/settings.js) vs Stitch "Apps & Schedules"

- Sub-tabs: Apps & Schedules (topics, schedule, planning, publishing), Brand Voice & Tone (about you, blocked phrases, alert channels), Quality Gates (old Advanced). All three are in one DOM so the save payload equals the old collectSettings output.
- Disabled with title "Coming soon", no config keys: YouTube video type, duration slider, ElevenLabs voice and Play sample, Test API. Instagram and TikTok cards.
- Invented Stitch sample data dropped: "@AgentDevStudio / Google OAuth", "OAuth Tokens Status: Valid", the Instagram/TikTok beta lines, "Long video / Shorts clip" day footers (now "Post day"), the "You modified ..." change list in the save bar (now Unsaved changes / Saved).
- Timezone is a text input with a datalist (free entry), not a 4-option select. Times are native time inputs (HH:MM 24h, what the backend validates), not "02:00 PM" text.
- Added beyond Stitch (old functionality kept): Weekly planning card with Save and plan / re-plan, Topics editor (ideas, context, brief), every-N-days fields, dates-as-text editor, planning focus, lead days, generate time.
- Practice mode and approval policy are per app (each app has its own). Weekly day chips for YouTube are disabled until it has topics.
- Focus rings are violet; the Stitch screen uses red on its YouTube page.
- Calendar shows recurring days for weekly and every-N-days cadences.

### workflow
# Workflow deviations
- Pause run, Stop, Re-run, Override and force pass, Inspect prompt diff, Adjust threshold: kept, disabled ("Coming soon"); no backend yet.
- Stitch's YouTube sample nodes (Aegis/Nova/ElevenLabs, scenes, "Iteration 2") replaced by the real steps of the selected run; voice/video nodes appear when the run has those steps.
- "Avg latency" pill replaced by "n of m steps done"; "Accuracy threshold" metric replaced by Tokens; no budget bar unless config.pipeline.max_run_budget_usd is set.
- "Editor's exact fixes" is the list of instructions the supervisor sent back to the selected agent (from run memory), not editor-only.
- Run picker is a select in the breadcrumb; "Only the selected step" checkbox replaces auto-scroll (the log scrolls itself when at the bottom).
- Sent-back arrow is drawn as an SVG measured from the real node positions (several arrows stack); Stitch's was a fixed-coordinate SVG.
- Node shadow-2xs / shadow-xs / active:scale-98 become shadow-sm / active:scale-95 (not in the Tailwind build).
- Working memory section is the legacy feature, styled with the same cards (no Stitch element).

## YouTube screens (written while wiring)

### queue-upload-plan-yt
# Queue / Upload / Plan: YouTube differences from Stitch

- Queue YouTube card: the thumbnail is the real `<video controls>` (native controls) instead of Stitch's custom play button; the 1080x1920/60fps overlay is dropped (not in post data). Long videos use a 16:9 frame.
- Queue: the right panel is titled "Quality Assurance" (the real Editor score), not "Shorts Retention Score". "Inline edit" and "Edit draft" both open the in-card form (title, description, tags).
- Queue: scene bar shows scene numbers (not names); hover shows on-screen text and narration. "Watch on YouTube" link added once a URL exists.
- Upload: script zone is .txt/.md only (no .docx); voice zone has no waveform (audio element only when the API gives a url); the per-scene "pace" labels are omitted. Remove buttons added. "Skip the Editor" stays disabled (Coming soon).
- Upload: toast() has no action slot, so "Run the crew now for this date" is a small secondary button shown beside the toast for 12 s.
- Plan: YouTube day cards gain a format chip, Format / Length controls and a "Use my own files" link (not in Stitch).

### settings-credentials-yt
# Settings and Credentials: YouTube + ElevenLabs

- Settings > Topics (YouTube): each topic card also has "Video style" (slides or blackboard) beside Format and Length; it overrides the app's video renderer for that topic. Not in the Stitch screen (the Topics editor is not either); same field component.
- Settings > Weekly cadence: the day cards use 2 columns on small, 4 on normal and 7 only on very wide screens (Stitch: always 7), so a topic name such as "Short: system design" and the time are readable instead of cut to "Short:" and "11:0".
- Settings > YouTube video settings: a "Pace" select (slow or normal) sits beside the "Video renderer" select, whose options are now Explainer (default), Plain slides, Blackboard and Animation MCP. The Short length slider runs 15 s to 3 min. None of this is in the Stitch screen; same field and select components.
- Settings: "Burn in captions" switch, "Video renderer" select, the MCP fields (command, tool, arguments, timeout) and the docs link are not in the Stitch screen; they use the same card, field and switch components.
- Settings: visibility select and "Made for kids" switch were added under the approval cards of the YouTube "When a post is ready" card (not in Stitch).
- Settings: YouTube topic cards show "Format" and "Length (seconds)" fields (optional, omitted from config when inherit/empty); LinkedIn topic cards are unchanged.
- Settings: the Short/Long cards are clickable divs with a decorative radio (Stitch uses a real radio), so switching can reset the slider.
- Settings: the "Coming soon" badge on the YouTube card and the disabled controls are removed; the card no longer has an opacity wash.
- Credentials: the YouTube card copies the LinkedIn card (no Stitch screen); "Connect YouTube" is disabled until client ID and secret are saved.
- Credentials: new "Voice" section with an ElevenLabs card (violet left border: ElevenLabs has no brand colour in the design system).
