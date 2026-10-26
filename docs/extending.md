# Extending Postcrew

Postcrew is small on purpose: standard-library Python plus Pillow, no framework, no database. This page shows
where things live and how to add to them. Read [CONTRIBUTING.md](../CONTRIBUTING.md) before opening a pull
request.

## Code map

```
postcrew/
  __main__.py        the command line (demo, init, serve, run, publish, check, doctor, status, plan, import)
  defaults.py        default settings
  workspace.py       the workspace folder, config validation, queue and history
  crew.py            starts a run for one date
  scheduler.py       the built-in scheduler (inside `serve`)
  llm.py             AI backends: Claude Code CLI, Claude API, OpenAI API, OpenAI-compatible
  demo.py            the demo backend: scripted answers and the one page it serves (`postcrew demo`)
  checks.py          deterministic checks: placeholders, hype, invented experience, numbers, links, repeats
  memory.py          working and long-term memory
  runlog.py          events.jsonl and status.json per run
  notify.py          bell, desktop, Gmail, Telegram
  linkedin.py        LinkedIn OAuth and REST API (posts, images, videos, comments)
  agents/            one file per agent; supervisor.py holds CREW, the order of steps
  prompts/           every agent's instructions, in Markdown
  render/            poster renderer (Pillow), algorithm tracers and the animation renderer (ffmpeg)
  studio/            the Studio: server.py (HTTP API) and static/ (one HTML page, app.js, style.css)
tests/               offline tests: the LLM, the web and LinkedIn are faked (helpers.py)
deploy/              launchd and systemd service files
```

## Add a category

No code needed: add it in **Settings > Topics** or in `config.json` ([reference](configuration.md#categories)).
The `brief` is where you describe what the post must contain.

## Change how an agent writes or judges

Copy its prompt from `postcrew/prompts/` into `workspace/prompts/` and edit the copy
([details](configuration.md#changing-the-prompts)). To change it for everyone, edit the file in
`postcrew/prompts/` and send a pull request.

## Add an agent

1. Subclass `Agent` in `postcrew/agents/` with `id`, `title`, `name`, `role`, and two methods:
   - `run(ctx, guidance)` returns the output (a dict). `self.ask(ctx, prompt, schema)` calls the model with a
     JSON schema; `guidance` carries the reasons and instructions if the work was sent back.
   - `validate(ctx, out)` returns a list of problems (empty means accepted). Make it deterministic wherever
     you can; use the model for judgment, not for checks a program can do.
2. Add it to `CREW` in `postcrew/agents/supervisor.py` and to `STEPS` in `postcrew/runlog.py`.
3. Add its id to `AGENT_IDS` in `postcrew/defaults.py` (and a model entry under `llm.agents` if it uses one).
4. Give it a colour, team and icon in `AGENTS` in `postcrew/studio/static/app.js`.
5. Write tests with the fakes in `tests/helpers.py`.

## Add an algorithm animation

Algorithm posts use built-in, tested traces in `postcrew/render/tracers.py`: Java source plus a
step-by-step trace of what it does. Add a `Tracer` to `TRACERS` and run the tests: they compile and run the
Java and compare its output with the animation, so the code on screen is real (needs Java 17+).

## Add a model backend

Four ship with Postcrew ([AI providers](ai-providers.md)). For another API, subclass `APIBackend` in
`postcrew/llm.py` (it handles keys, model tiers, retries, errors and cost) and implement `ask()`; or implement a class with
`call(agent_id, system, prompt, schema, tools=(), cwd=None, model=None, member=None)` that returns an
`LLMResult(data=..., cost_usd=..., model=..., turns=...)`, and register it in `make_backend` in
`postcrew/llm.py`. Add its name to the `llm.backend` check in `validate_config`, its key to `SECRET_KEYS`, and
its label to `PROVIDER` in `agents/credentials.py`. Keep the guarantees: the
output must match the JSON schema, and only the tools listed in `tools` may be available to the model.

## Run the tests

```bash
python3 -m unittest discover -s tests
```

No network, no tokens, about 20 seconds. Tests for the algorithm animations need Java and ffmpeg; CI
installs both (`.github/workflows/tests.yml`).

## The Studio's look (Stitch)

The Studio UI is built from the Stitch design saved in `design/stitch/` (screens as HTML + PNG, plus `design.md`). Never restyle
from memory: copy the screen.

- `postcrew/studio/static/index.html` + `app.js`: the shell (top bar, app switcher, banner, footer), router and API helpers.
- `ui.js`: shared components (icons, status chips, app badges, tooltips, buttons). `views/<tab>.js`: one file per screen.
- `tailwind.css`, `fonts.css`, `fonts/` are **generated** by `python3 scripts/build_ui_assets.py` (Tailwind for the classes in
  the screens and views, plus only the Material Symbols icons used). The Studio loads nothing from the internet.
- Design changed in Stitch? `python3 scripts/stitch_sync.py`, then rebuild, then update the matching view.
  `python3 scripts/stitch_check.py` checks the views still follow it (no emoji icons, no old classes, known icons and classes).
- Where the Studio differs from Stitch on purpose: `design/DEVIATIONS.md`.

Claude Code users get this wired in: the `stitch-ui` and `stitch-sync` skills and hooks in `.claude/` keep UI changes on the design.
