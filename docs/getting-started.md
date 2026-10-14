# Getting started

This guide takes you from nothing to your first rehearsed post in about 15 minutes, and then to a live,
scheduled post. Everything runs on your own computer.

- [1. What you need](#1-what-you-need)
- [2. Install Claude Code](#2-install-claude-code)
- [3. Download and install Postcrew](#3-download-and-install-postcrew)
- [4. Create your workspace and check everything](#4-create-your-workspace-and-check-everything)
- [5. Open the Studio](#5-open-the-studio)
- [6. Tell the crew about you](#6-tell-the-crew-about-you)
- [7. Run a rehearsal](#7-run-a-rehearsal)
- [8. Connect LinkedIn](#8-connect-linkedin)
- [9. Go live](#9-go-live)
- [10. Keep it running](#10-keep-it-running)
- [Updating](#updating)
- [Uninstalling](#uninstalling)

## 1. What you need

| | Required? | Why |
|---|---|---|
| macOS or Linux (Windows: use [WSL](https://learn.microsoft.com/windows/wsl/install)) | yes | Postcrew is plain Python and runs anywhere Python and Claude Code run |
| Python 3.9 or newer | yes | `python3 --version` |
| [Claude Code](https://claude.com/claude-code), logged in | yes | every agent thinks through your Claude Code login; no API key is stored by Postcrew |
| A Claude plan (Pro, Max, Team) or an Anthropic Console account | yes | Claude Code needs one of them |
| A LinkedIn account and a free LinkedIn developer app | to publish | only needed when you want posts to go out ([guide](linkedin-setup.md)) |
| ffmpeg | optional | only for the algorithm animation videos |
| Java 17+ | optional | only for running the test suite (it compiles the Java shown in animations) |

## 2. Install Claude Code

Follow the [official instructions](https://docs.claude.com/en/docs/claude-code/setup). The short version:

```bash
curl -fsSL https://claude.ai/install.sh | bash     # or: npm install -g @anthropic-ai/claude-code
claude                                              # opens Claude Code; log in once, then type /exit
```

Postcrew calls `claude -p` in an isolated mode: no shell or code tools, no MCP servers, and your own Claude
settings and hooks are ignored. Each agent gets only the tools it needs (the researchers get web search).

## 3. Download and install Postcrew

```bash
git clone https://github.com/<owner>/postcrew.git
cd postcrew
python3 -m venv .venv && source .venv/bin/activate   # recommended: keeps Postcrew's one dependency separate
python3 -m pip install --upgrade pip                 # older pips can't install the `postcrew` command below
python3 -m pip install -r requirements.txt           # installs Pillow, the only dependency
```

Prefer a `postcrew` command? Run `python3 -m pip install -e .` in the same folder; then `postcrew serve`
works as well as `python3 -m postcrew serve` (while the virtual environment is active). Run
`source .venv/bin/activate` again in each new terminal.

Optional, for algorithm videos:

```bash
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Debian / Ubuntu
```

## 4. Create your workspace and check everything

```bash
python3 -m postcrew init       # creates ./workspace with default settings
python3 -m postcrew doctor     # checks Python, Pillow, ffmpeg, Claude Code, settings and LinkedIn
```

The **workspace** is the one folder that holds everything that is yours: settings, secrets, the queue, the
published list, run logs and memory. It is never committed to git. By default it is `./workspace` inside
the project; set `POSTCREW_HOME=/some/folder` (or pass `--workspace /some/folder`) to keep it elsewhere.
See [the workspace layout](configuration.md#the-workspace-folder).

`doctor` prints a checklist. A missing LinkedIn connection is expected at this point.

## 5. Open the Studio

```bash
python3 -m postcrew serve      # http://localhost:8765
```

This starts the **Studio** (the dashboard) and the **scheduler** in one process. Leave it running in a
terminal, or set it up as a service later ([running unattended](running-unattended.md)). Stop it with
Ctrl+C. Use `--port 9000` to pick another port.

The Studio listens on `127.0.0.1` only, so nobody else on your network can open it.

## 6. Tell the crew about you

Open **Settings** and work through the three steps on the page:

1. **Topics**: the kinds of posts you want. Seven come built in (AI news, how-to guides, tool spotlights,
   security explainers, dev tips, algorithm animations, a weekly recap). Remove the ones you don't want, add
   your own, and list your own topic ideas under each one.
2. **Weekly schedule**: which topic goes out on which day, the time posts are published, the time the crew
   writes them (the evening before), and your time zone.
3. **About you**: your name, the profile link printed on posters, who reads your posts, how you write, and
   **true facts about you**. The writers may only claim experience that is listed here; they never invent
   any.

Click **Save settings**. Every field is explained in the [configuration reference](configuration.md).

## 7. Run a rehearsal

On **Overview**, under **Run the crew now**, keep **Rehearsal** ticked and click **Start run**. A rehearsal
runs every agent but never adds the post to the queue, so nothing can be published.

Open **Workflow** to watch it: each agent lights up while it works, sent-back work shows as red arrows, and
clicking an agent shows its output, the problems it was sent back for, and the rendered poster. A researched
post takes about 2-5 minutes.

Run a few rehearsals for different days and categories until you like what you see. The
[Studio guide](studio-guide.md) explains every panel.

## 8. Connect LinkedIn

Follow [Connect LinkedIn](linkedin-setup.md): create a free developer app (5 minutes), paste its Client ID
and Secret on **Credentials**, then click **Connect LinkedIn**.

## 9. Go live

Postcrew starts in **practice mode** (`publishing.dry_run`): the publisher logs exactly what it would send
and sends nothing. When you trust the output:

1. Pick an approval mode in **Settings > Publishing and alerts**:
   - **Publish at post time unless I veto it** (default): queued posts go out at the post time; veto any of
     them in the Queue before then.
   - **Wait for my approval**: nothing goes out until you click **Approve** in the Queue.
   - **Publish right away**: posts go out as soon as they pass review.
2. Untick **Practice mode** and save.

From now on the scheduler writes each post the evening before and publishes it at the post time. If you
already made a post for a day by hand, the scheduler sees it and does not make another one.

> **Already running another auto-poster?** Turn it off first (for example an old GitHub Actions schedule),
> or both will post.

## 10. Keep it running

The scheduler only works while `postcrew serve` is running. To keep it running after you close the
terminal, log out or restart, install it as a service: [running unattended](running-unattended.md).

## Updating

```bash
cd postcrew
git pull
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests     # optional: check everything still works
```

Then restart the Studio. Your workspace is untouched by updates; new settings get their default values
automatically.

## Uninstalling

Stop the Studio (and the service, if you installed one), then delete the project folder. Your workspace
lives inside it unless you moved it with `POSTCREW_HOME`. To revoke Postcrew's access to LinkedIn, remove the
app under LinkedIn **Settings > Data privacy > Permitted services**, or delete the developer app.
