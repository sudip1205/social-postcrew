# Troubleshooting and FAQ

Start with `python3 -m postcrew doctor`: it checks Python, Pillow, ffmpeg, Claude Code, your settings and
LinkedIn, and says what to do for anything missing. For a failed run, open it in **Workflow** and click the
agent with the red **!**: its rejected attempts list the exact reasons.

## Installing and starting

**`claude: command not found`, or Claude Code shows `missing` on Credentials.**
Install Claude Code and run `claude` once to log in. If the Studio runs as a service, it may not see your
shell's `PATH`: put the full path (`which claude`) in **Settings > Advanced > Claude Code command**, or add its
folder to `PATH` in the service file.

**`logged_out`.** Run `claude` in a terminal, log in, and click **Check now** on Credentials.

**Port 8765 is already in use.** Another Studio is running (`lsof -i :8765`), or pick another port with
`serve --port 9000`. Remember to add that port's redirect URL to your LinkedIn app.

**`ModuleNotFoundError: PIL`.** Run `python3 -m pip install -r requirements.txt` with the same Python you
start Postcrew with (activate the virtual environment first).

**Algorithm posts fail at the Visual Designer.** Install ffmpeg (`brew install ffmpeg` or
`sudo apt install ffmpeg`).

## Runs

**A run stopped with "max total attempts" or "run budget".**
The crew hit a limit in `pipeline`. Open the run in Workflow to see which step kept failing. Common causes:
a topic with no recent primary source (the research team can't verify it; plan a different topic), or a
category brief that asks for something the rules forbid (a source list, links in the body).

**The Editor keeps sending the post back.**
Look at the Editor's step: it shows each criterion's score and the fixes. If the hook keeps failing, the
topic probably has no single concrete fact to lead with; prefer topics readers can use now. Make sure the
Editor and the Pre-reviewer use the same model (sonnet by default). Don't lower `min_overall`; fix the brief
or the topic instead.

**"another crew run is in progress".** Only one run happens at a time. Wait for it to finish (Workflow shows
it live).

**Nothing was written last night.**
Was `postcrew serve` running and the computer awake at `generate_time`? Is the schedule paused? Does that
day have a category? Was there already a post for that date? The Overview shows when the next run will happen.

**A post was written twice for one day.** The scheduler skips a date that already has a post, but another
tool (an older auto-poster, a second Postcrew on another computer) can't see this queue. Run only one.

## Publishing

**Nothing is posted to LinkedIn.**
Check, in order: **Practice mode** is off (Settings); the post's date and post time have passed; the approval
mode is not waiting for you (**Approve** in the Queue); LinkedIn shows `ok` or `expiring` on Credentials.

**`invalid` or `expired` LinkedIn token.** Click **Reconnect LinkedIn** on Credentials. Queued posts wait and go
out at the next publish check.

**LinkedIn says the redirect URL doesn't match.** The URL in your LinkedIn app (Auth tab) must be exactly
`http://localhost:<port>/oauth/callback`, with the port the Studio runs on.

**`LinkedIn-Version` / version errors.** Set **Settings > Advanced > LinkedIn API version** to a recent month
(`YYYYMM`).

**The first comment is missing.** Postcrew retries it a few times; the Published table says whether it was
added. If it says "add it by hand", paste the link as the first comment on LinkedIn yourself.

## Notifications

**Gmail test fails with `535`.** The App Password is wrong, or 2-Step Verification is off. Create a new App
Password and paste it again; don't use your normal Gmail password.

**Telegram test sends nothing.** Send any message to your bot first, then check the chat id with `getUpdates`.

**No desktop notification on Linux.** Install `libnotify-bin` (it provides `notify-send`).

## FAQ

**Does it need an Anthropic API key?** No. It uses your Claude Code login. On a Claude plan, usage counts
towards your plan's limits; the costs shown are API-equivalent estimates.

**Can I use another model provider?** Not out of the box. The LLM layer is one small class; see
[extending](extending.md).

**Will it post things I haven't seen?** Only if you choose `auto_with_veto` or `immediate` and turn practice
mode off. With `manual`, nothing goes out until you approve it. Every post must pass strict checks either way.

**Can it make up experience or quotes?** The writers may only use facts from **About you** for anything
personal, and research quotes are checked against the pages Postcrew downloaded itself. Drafts that sound
like invented experience are rejected automatically.

**Where is my data?** Only in your workspace folder, on your computer. Postcrew has no server and no
telemetry. Agent prompts go to Anthropic through Claude Code; posts go to LinkedIn when published.

**Does it work on Windows?** Use [WSL](https://learn.microsoft.com/windows/wsl/install) and follow the Linux
instructions.

**How do I start over?** Stop the Studio and delete (or rename) the workspace folder, then
`python3 -m postcrew init`.
