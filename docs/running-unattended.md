# Running unattended

The scheduler lives inside `postcrew serve`, so posts are only written and published while that process is
running. For a hands-off setup, run it as a service that starts at login (or boot) and restarts after a crash.

Whatever you choose, the computer has to be **on and awake** at `generate_time` and `post_time`. If it was
asleep, the scheduler catches up as soon as it wakes the same day.

## macOS (launchd)

1. Open `deploy/launchd/com.postcrew.studio.plist` and replace:
   - `/PATH/TO/postcrew` (twice) with the folder you cloned, e.g. `/Users/you/postcrew`;
   - `/usr/bin/python3` with the Python you use (`which python3`; with a virtual environment, use
     `/Users/you/postcrew/.venv/bin/python3`);
   - `/Users/YOU/.local/bin` in `PATH` with the folder that contains `claude` (`dirname $(which claude)`).
     launchd does not expand `~`, so write the full path.
2. Install and start it:

   ```bash
   cp deploy/launchd/com.postcrew.studio.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.postcrew.studio.plist
   ```

3. Open http://localhost:8765. Logs go to `/tmp/postcrew.log`.

Stop it with `launchctl unload ~/Library/LaunchAgents/com.postcrew.studio.plist`. To stop the Mac from
sleeping at post time, use **System Settings > Battery (or Energy) > Options**, or schedule a wake with
`sudo pmset repeat wake MTWRFSU 08:20:00`.

## Linux (systemd user service)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/postcrew.service ~/.config/systemd/user/
# edit WorkingDirectory, POSTCREW_HOME, PATH and ExecStart in that file if postcrew is not in ~/postcrew
systemctl --user daemon-reload
systemctl --user enable --now postcrew
loginctl enable-linger $USER          # keep it running when you are logged out
journalctl --user -u postcrew -f      # follow the logs
```

`PATH` must include the folder that contains `claude`.

## cron instead of the built-in scheduler

Run the Studio without its scheduler, and let cron do the timing:

```bash
python3 -m postcrew serve --no-scheduler
```

```cron
# m  h  dom mon dow  command   (times are in the computer's time zone)
0   19 *   *   *    cd /home/you/postcrew && python3 -m postcrew run      >> /tmp/postcrew.log 2>&1
*/15 8-12 * * *     cd /home/you/postcrew && python3 -m postcrew publish  >> /tmp/postcrew.log 2>&1
0   9  *   *   *    cd /home/you/postcrew && python3 -m postcrew check    >> /tmp/postcrew.log 2>&1
0   10 *   *   1    cd /home/you/postcrew && python3 -m postcrew plan     >> /tmp/postcrew.log 2>&1
```

`run` writes the post for the date `lead_days` ahead; `publish` publishes whatever is due (and retries
first comments); `check` checks credentials and notifies you; `plan` drafts the week. `run` and `publish`
do nothing while the `PAUSE` file exists.

## On a server or another computer

The Studio only listens on `127.0.0.1`. To use it from your laptop, open an SSH tunnel:

```bash
ssh -L 8765:localhost:8765 you@your-server
```

and browse to http://localhost:8765 on the laptop. Connecting LinkedIn works through the tunnel too, because
the redirect URL is `http://localhost:8765/oauth/callback`.

Claude Code must be logged in on the server (`claude` once, then log in), as the same user that runs the
service.

## Pausing

- **Pause schedule** on the Overview, or
- `touch workspace/PAUSE` (delete the file to resume).

While paused, nothing is written or published automatically. You can still start runs by hand from the
Studio.
