# Configuration reference

Every setting lives in `workspace/config.json`. You can change almost all of them in the Studio
(**Settings** tab); a few advanced ones are only in the file. Either way, Postcrew validates the whole file
when it is saved and tells you exactly what to fix, so a typo can't break a scheduled run.

You only need to keep the settings you change: anything missing from `config.json` takes its default from
[`postcrew/defaults.py`](../postcrew/defaults.py). After editing the file by hand, restart the Studio or
just save once from the Settings page.

**Contents:** [profile](#profile) · [schedule](#schedule) · [planning](#planning) ·
[publishing](#publishing) · [llm](#llm) · [pipeline](#pipeline) · [team](#team) ·
[notifications](#notifications) · [categories](#categories) · [secrets](#secrets-secretsjson) ·
[the workspace folder](#the-workspace-folder) · [environment variables](#environment-variables) ·
[changing prompts](#changing-the-prompts)

---

## profile

Who you are. Studio: **Settings > 3. About you** (and **Advanced > Other** for the blocklist).

| Key | Default | What it does |
|---|---|---|
| `name` | `""` | Your name. The agents write in your voice and refer to you by it. |
| `handle` | `""` | Printed at the bottom of every poster, e.g. `linkedin.com/in/your-name`. Max 60 characters. |
| `audience` | `"software engineers and technology leaders"` | Who reads your posts. Topics, depth and examples are chosen for them. |
| `voice` | `"Plain words, short paragraphs, concrete. Helpful, never salesy."` | How you write. |
| `about` | `[]` | **True facts about you**, one per item ("10 years building Java backends"). The writers may only claim experience listed here. Anything else that sounds like personal experience ("I migrated...", "at my company...") is rejected automatically and flagged by the Editor as `invented_experience`. |
| `blocklist` | `["my employer", "my company", "confidential", "proprietary", "internal only", "NDA"]` | Words and phrases that must never appear in a post or on a poster (whole words, any case). Add your employer's name or internal project names here. |

## schedule

When posts are written and published. Studio: **Settings > 2. Weekly schedule**, plus **Advanced > Other**.

| Key | Default | What it does |
|---|---|---|
| `timezone` | `"America/Chicago"` | An [IANA time zone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) (`Europe/London`, `Asia/Kolkata`...). All times below are in this zone. |
| `generate_time` | `"19:00"` | When the crew writes the next post (24-hour `HH:MM`). |
| `post_time` | `"08:30"` | When queued posts are published on their date. |
| `lead_days` | `1` | How many days ahead the crew writes. `1` = write tomorrow's post this evening, which leaves you the night to read, edit or veto it. `0` = write today's post at `generate_time`. 0-7. |
| `credential_check_time` | `"09:00"` | When the daily credential check runs. |
| `days` | see below | Which category is posted on each day: `mon` ... `sun`, each a category id from [categories](#categories), or `""` for no post. At least one day must have a category. |

Default week: Monday `algorithm`, Tuesday `ai-news`, Wednesday `build-guide`, Thursday `tool-spotlight`,
Friday `security`, Saturday `dev-tip`, Sunday `week-recap`.

**What the scheduler does each day** (while `postcrew serve` is running; it checks every 30 seconds):

1. At `credential_check_time`: checks LinkedIn and Claude Code, and notifies you of any problem.
2. On `planning.weekday` at `planning.time`: the Week Planner drafts the week's open days.
3. At `generate_time`: runs the crew for the date `lead_days` ahead, **unless that date already has a post**
   (queued, waiting for approval or published) or a run is already going. Vetoed and failed posts don't
   count. The scheduler runs once per date; to replace a post you vetoed after that, start a run by hand.
4. From `post_time` on, every 15 minutes: publishes whatever is due, and retries first comments that failed.

Missed a time because the computer was asleep? The scheduler catches up as soon as it runs again the same day.

## planning

The Week Planner (Vega) drafts a topic for every remaining day of the week so you can review them in the
**Plan** tab. Studio: **Settings > 2. Weekly schedule**.

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Plan automatically every week. You can always plan by hand from the Plan tab. |
| `weekday` | `"mon"` | Which day it plans. |
| `time` | `"10:00"` | At what time. |
| `focus` | `""` | Optional direction for the whole plan, e.g. "This week is about Kubernetes; keep examples in Python". Max 600 characters. |

Days you planned (or typed) are written about as planned. A day left open is picked by the Topic Scout the
evening before. Categories with `plan_ahead: false` (AI news, by default) are always picked the evening
before, because news a week old is stale.

## publishing

Studio: **Settings > Publishing and alerts**, plus **Advanced > Other**.

| Key | Default | What it does |
|---|---|---|
| `approval` | `"auto_with_veto"` | `auto_with_veto`: queued posts go out at `post_time` unless you veto them in the Queue. `manual`: nothing goes out until you click **Approve**. `immediate`: published as soon as the post passes review. |
| `dry_run` | `true` | **Practice mode.** The crew writes and queues posts, but the Publisher only logs what it would send. Turn this off to post for real. |
| `linkedin_api_version` | `"202601"` | The `LinkedIn-Version` header (`YYYYMM`). LinkedIn retires old versions about a year after release; if publishing starts failing with a version error, set a recent month. |

## llm

Which model each agent uses and how much a single call may cost. Studio: **Settings > Advanced > AI models**.

| Key | Default | What it does |
|---|---|---|
| `backend` | `"claude-code"` | Which AI runs the crew: `claude-code` (your Claude Pro / Max / Team plan through the Claude Code CLI), `anthropic` (Claude API key), `openai` (OpenAI API key), `openai-compatible` (Ollama, LM Studio, OpenRouter, Groq, vLLM...), or `demo` (scripted answers, no AI; what `postcrew demo` uses). See [AI providers](ai-providers.md). |
| `claude_path` | `"claude"` | The Claude Code command. Use the full path (`which claude`) if the Studio runs as a service and can't find it. |
| `api.base_url` | `""` | Server address for `openai-compatible` (required), e.g. `http://localhost:11434/v1`; optional for `openai`. |
| `api.models.<provider>` | see [AI providers](ai-providers.md#model-tiers) | Which model each tier (`opus`, `sonnet`, `haiku`) means for that provider. |
| `api.prices` | estimates for the default models | USD per million tokens (`input`, `output`) per model id, for the cost shown and the budget caps. |
| `api.max_output_tokens` | `16000` | Longest answer per call with an API provider (1000-200000). |
| `defaults` | `{"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0}` | Used for any agent not listed under `agents`. |
| `agents.<id>.model` | see below | A tier: `haiku` (fastest, cheapest), `sonnet` or `opus` (strongest), mapped to your provider's models; or a full model id such as `gpt-5` or `qwen3:32b`. |
| `agents.<id>.timeout_s` | see below | Seconds before a call is stopped and counted as a failed try. 30-3600. |
| `agents.<id>.max_budget_usd` | see below | Cost cap for **one call** (Claude Code's `--max-budget-usd`; for API providers, Postcrew stops a call that goes over it). Up to 20. |

Defaults per agent:

| Agent id | Name | Model | Timeout | Max $ per call |
|---|---|---|---|---|
| `planner` | Vega, Week Planner | sonnet | 600 | 1.00 |
| `topic` | Nova, Topic Scout | sonnet | 300 | 0.50 |
| `research` | Ada · Ravi, Research team | sonnet | 900 | 1.50 |
| `writer` | Maya · Leo, Writing team | sonnet | 600 | 1.00 |
| `reviewer` | Iris, Pre-reviewer | sonnet | 300 | 0.40 |
| `media` | Pixel, Visual Designer | haiku | 300 | 0.30 |
| `editor` | Quinn, Editor Review | sonnet | 300 | 0.40 |
| `supervisor` | Orion, Supervisor | haiku | 180 | 0.20 |

Keep the Editor and the Pre-reviewer on the same model: the Pre-reviewer's job is to predict the Editor's score.
Haiku makes reviews cheaper but noticeably less consistent.

The Credential Monitor, Formatter and Publisher use no AI; they are plain rules.

**About cost.** Each call reports what it would cost at API prices, and the run log adds them up. On a
Claude Pro or Max plan you are not charged that amount; the usage counts towards your plan's limits instead.
With an API provider you pay that amount (estimated from `llm.api.prices`).
With the defaults, a researched news post typically uses $1-2 of API-equivalent usage, and a short dev tip
much less.

## pipeline

Quality bar and hard limits for one post. Studio: **Settings > Advanced > Quality bar and limits**.

| Key | Default | What it does |
|---|---|---|
| `min_overall` | `80` | The Editor's overall score a post needs to be queued (0-100). |
| `min_subscore` | `70` | Every single criterion (accuracy, clarity, hook, value, tone, format) must reach this too. A post at 85 overall with a weak hook (66) is sent back. |
| `review_runs` | `3` | The Editor reviews the post this many times independently; the **worst** result counts. 1-5. |
| `max_attempts_per_step` | `4` | Tries per agent before the Supervisor gives up on that step. 1-10. |
| `max_total_attempts` | `16` | Tries across the whole run, rewinds included. 1-40. |
| `max_run_budget_usd` | `5.0` | Hard stop for one post (API-equivalent dollars). Up to 100. |

If a run hits a limit, nothing is queued for that day and you are notified with the reason. The scheduler
does not retry that date by itself; start a run by hand from the Overview if you want to.

## team

The research and writing teams, and how members are judged. Studio: **Settings > Advanced > Team**
(`pre_review_margin` and `polish_rounds` are in `config.json` only).

| Key | Default | What it does |
|---|---|---|
| `research` | `2` | Researchers per post (1-4). They work in parallel; their verified sources and facts are combined. |
| `writer` | `2` | Writers per post (1-4). Each writes a full draft in their own style; the best one goes on. |
| `pre_review` | `true` | Iris, the Pre-reviewer, scores every draft with the Editor's rubric, picks the best and polishes it before the Editor sees it. Cheaper than a failed Editor round. |
| `pre_review_margin` | `5` | Polish the chosen draft unless its pre-review score beats `min_overall` by this much. |
| `polish_rounds` | `2` | At most this many polishes before the Editor (0-3). Each polish applies Iris's exact fixes to the failing criteria only. |
| `fire_window` | `6` | Judge a member on their last N posts (3-20). |
| `fire_min_success` | `0.34` | Replace a member whose share of good posts in that window is below this (0-1). The replacement inherits the lessons the team wrote down. See [the crew](agents.md#the-roster-hiring-and-replacing). |

More members means better odds and higher usage: each extra writer adds one draft and one pre-review per post.

## notifications

Studio: **Settings > Publishing and alerts** (switches) and **Credentials** (Gmail and Telegram details).
See [notifications](notifications.md).

| Key | Default | What it does |
|---|---|---|
| `desktop` | `true` | macOS Notification Center, or `notify-send` on Linux. |
| `email` | `false` | Email through your Gmail account (needs a Gmail App Password). |
| `telegram` | `false` | Messages from your own Telegram bot. |
| `warn_days_before_expiry` | `7` | Warn this many days before the LinkedIn token expires (1-30). |
| `studio_url` | `"http://localhost:8765"` | Where the button in each email points. Change it if you use another port or reach the Studio through an SSH tunnel on another port. |

Every notification also appears under the bell icon in the Studio, whatever these switches say.

## categories

A **category** (shown as a *topic* in the Studio) is a kind of post: what it must contain, whether it needs
research, its length and its picture. Studio: **Settings > 1. Topics**, then **More options** on each card.
Add one with **Add topic**; the id is made from its name.

| Key | Required | What it does |
|---|---|---|
| *id* (the key) | yes | Lowercase letters, digits and dashes, up to 31 characters. Used in `schedule.days`. |
| `label` | yes | The name shown everywhere. |
| `brief` | yes | **What this kind of post must contain**, in plain words. Every agent reads it. This is the most powerful setting: describe the order of sections, the hook you want, what is forbidden, what goes in the first comment. |
| `media` | yes | `poster` (a 1080×1350 image), `video` (the same poster as an MP4 of about 18 seconds: the title first, then each card, step, box or few lines of code fading in; any topic, needs ffmpeg, falls back to the poster image without it), `animation` (an MP4 for algorithm posts), or `none`. |
| `layouts` | for posters | Allowed poster layouts, any of `points` (numbered cards), `steps` (a how-to), `code` (a highlighted snippet; the code must parse), `flow` (a step-by-step flow). |
| `kicker` | no | The small label on top of the poster, e.g. `AI NEWS`. Max 26 characters. |
| `research` | no | `required`: the research team must find and verify sources (default for news). `optional`: research when useful. `off`: write from general, well-established knowledge only. |
| `max_source_age_days` | no | Sources must be newer than this. Leave out for any age. |
| `min_chars` / `max_chars` | yes | Post length. 50 ≤ min < max ≤ 3000 (LinkedIn's limit). |
| `fact_check` | no | When `true`, every price, percentage and large number in the post must appear in a verified source, or the post is rejected before the Editor sees it. |
| `plan_ahead` | no | `false` = the Week Planner leaves this day open and the topic is picked the evening before. Default `true`. |
| `ideas` | no | Your own topic ideas, one per item (up to 60, 3-150 characters each). The planner and the Topic Scout use these first, mark each one with the date it was used, and never use one twice. |

The built-in categories:

| Id | Label | Media | Research | Length |
|---|---|---|---|---|
| `algorithm` | Algorithm in Java (animation) | animation | off | 500-1800 |
| `ai-news` | Latest AI news | poster: points | required, sources ≤ 10 days old, fact-checked | 500-1800 |
| `build-guide` | Complete how-to: build something cool | poster: steps | optional | 1400-2900 |
| `tool-spotlight` | Tool or open-source project worth trying | poster: points | required, fact-checked | 500-1800 |
| `security` | Security and identity explained | poster: flow, points | optional | 800-2200 |
| `dev-tip` | Quick developer tip with code | poster: code | off | 400-1500 |
| `week-recap` | Week in review plus one thing to try | poster: points | off (uses the week's posts) | 500-1600 |

Two are special: `algorithm` picks the next algorithm from the built-in library of tested animations (merge
sort, quick sort, insertion sort, bubble sort, binary search, BFS, DFS), and `week-recap` summarises the
posts of the last 7 days. Neither uses topic ideas.

Example: a category of your own, posted on Fridays.

```json
{
  "categories": {
    "career": {
      "label": "Career advice for engineers",
      "media": "poster", "layouts": ["points"], "kicker": "CAREER",
      "research": "off", "min_chars": 600, "max_chars": 1600, "fact_check": false,
      "ideas": ["How to write a promotion packet", "Saying no to a meeting"],
      "brief": "One practical career lesson for mid-level engineers. Hook: the mistake, in one line. Then why it happens, what to do instead in 3 numbered steps, a question, 3 hashtags. No personal stories unless they are in About you."
    }
  },
  "schedule": { "days": { "fri": "career" } }
}
```

## Secrets (`secrets.json`)

Secrets never live in `config.json`. They are kept in `workspace/secrets.json`, created readable only by
your user account (mode 600) and ignored by git. Set them on the **Credentials** page; the Studio never
sends them back to the browser.

| Key | Set by |
|---|---|
| `linkedin_client_id`, `linkedin_client_secret` | you, from your LinkedIn developer app |
| `linkedin_access_token`, `linkedin_token_expires_at`, `linkedin_person_urn`, `linkedin_name` | **Connect LinkedIn** |
| `gmail_address`, `gmail_app_password`, `email_to` | you, for email notifications |
| `anthropic_api_key`, `openai_api_key`, `llm_api_key` | you, for the Claude API, the OpenAI API or an OpenAI-compatible server ([AI providers](ai-providers.md)) |
| `telegram_bot_token`, `telegram_chat_id` | you, for Telegram notifications |

With the default `claude-code` provider there is no API key: Claude Code keeps its own login. API keys may
also come from the environment variables `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `LLM_API_KEY`.

## The workspace folder

```
workspace/
  config.json          your settings (no secrets; safe to back up or share)
  secrets.json         LinkedIn, Gmail and Telegram secrets (mode 600; never share or commit)
  queue.json           posts that passed review and wait for their date
  history.json         everything published, plus posts you added by hand: never repeated
  media/               posters and videos of queued posts
  prompts/             optional: your own version of any agent prompt (see below)
  runs/<run_id>/       one folder per crew run:
    status.json          state of every step, tries, cost
    events.jsonl         the full event log
    memory.json          working memory: what was sent back during this run, and why
    <step>.json          each agent's accepted output
    <step>.rejected.N.json   every rejected attempt, with the reasons
    media files          rendered posters and videos
  state/
    scheduler.json       what the scheduler already did today
    credentials.json     the last credential check
    plan.json            this week's plan
    roster.json          team members, their results and the team's lessons
    memory.json          long-term memory: problems fixed in approved runs
    notifications.json   everything under the bell icon
  PAUSE                create this (empty) file to stop all writing and publishing
```

Back up the whole folder to keep your history, roster and memory. Copying it to another machine (with the
code) moves your whole setup; reconnect LinkedIn there if the redirect port differs.

## Environment variables

| Variable | What it does |
|---|---|
| `POSTCREW_HOME` | Workspace folder. Default: `./workspace` in a source checkout, `~/.postcrew` when installed from PyPI. Same as `--workspace`. `postcrew demo` always uses its own folder (`./workspace-demo` or `~/.postcrew-demo`) unless you pass `--workspace`. |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LLM_API_KEY` | API keys, used when none is saved on Credentials. |

## Changing the prompts

Every agent's instructions are plain Markdown in [`postcrew/prompts/`](../postcrew/prompts):

| File | Used by |
|---|---|
| `planner.md` | Vega, the Week Planner |
| `topic.md` | Nova, the Topic Scout |
| `research.md`, `research_extract.md` | the research team (choosing pages; quoting them) |
| `writer.md` | the writing team |
| `rubric.md` | the scoring guide shared by the writers, Iris and Quinn |
| `editor.md` | Quinn, the Editor (and Iris, who predicts Quinn) |
| `media.md` | Pixel, the Visual Designer |
| `supervisor.md` | Orion, the Supervisor |

To change one without touching the code, copy it into `workspace/prompts/` with the same name and edit the
copy; Postcrew uses yours from the next run, and `git pull` never overwrites it. Placeholders such as
`{{name}}`, `{{audience}}` and `{{rubric}}` are filled in automatically; keep them.

If you change `rubric.md`, the writers and the Editor both switch to your version, so they keep aiming at
the same target.
