# Spoty-fixer

Restarting Spotify during an ad makes the ad disappear and the music resume immediately.
This script does that automatically.

## How it works

`spoty_reloader.py` reads the current Spotify track once a second over MPRIS (D-Bus).
When an ad is playing, the script closes Spotify, starts it again, and resumes playback.
If the client restores on the track that finished before the ad, the script skips to the next one.

On KDE Plasma the new Spotify window opens on the same monitor, desktop, and position as the old one,
and does not take focus (the KWin script `keep_window.js`). On other desktops that step is skipped.

## Requirements

- Linux with a session D-Bus
- Python 3 and PyGObject (`python-gobject` on Arch, `python3-gi` on Debian/Ubuntu)
- Spotify: flatpak `com.spotify.Client`, or `spotify` on `PATH`

## Running

```bash
./run.sh            # start in the background
./run.sh status     # check whether it is running
./run.sh log        # follow the log (~/.local/state/spoty-reloader.log)
./run.sh stop       # stop
```

Arguments after the command are passed to the script, for example `./run.sh start --cooldown 20`:

- `--interval` — how often to check the track, in seconds (default: 1)
- `--cooldown` — minimum pause between restarts, in seconds (default: 10)
- `--command` — command used to start Spotify, if auto-detection is not right
- `--restart-now` — restart Spotify once and exit (for testing)

`./run.sh spotify` starts the flatpak Spotify together with the script. That command is a good replacement for the Spotify menu entry.

## Autostart with systemd

```bash
cp spoty-reloader.service ~/.config/systemd/user/
# if the repo is not in ~/Spoty-fixer, edit ExecStart
systemctl --user daemon-reload
systemctl --user enable --now spoty-reloader.service
```
