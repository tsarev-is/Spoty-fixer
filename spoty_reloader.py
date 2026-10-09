#!/usr/bin/env python3
"""Watch Spotify over MPRIS (D-Bus). Restart the client when an ad starts and resume playback."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from gi.repository import Gio, GLib

BUS_NAME = "org.mpris.MediaPlayer2.spotify"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
FLATPAK_APP_ID = "com.spotify.Client"
PROCESS_NAME = "spotify"
DBUS_TIMEOUT_MS = 2000
KWIN_BUS_NAME = "org.kde.KWin"
KWIN_SCRIPTING_IFACE = "org.kde.kwin.Scripting"
KWIN_SCRIPT_NAME = "spoty-reloader-keep-window"
KWIN_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keep_window.js")


def log(message):
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)


def is_ad(metadata):
    # Ads use a track id like /com/spotify/ad/<id> (older clients: spotify:ad:<id>).
    track_id = str(metadata.get("mpris:trackid", ""))
    url = str(metadata.get("xesam:url", ""))
    return track_id.startswith("/com/spotify/ad/") or track_id.startswith("spotify:ad:") or "/ad/" in url


def describe(metadata):
    artists = ", ".join(metadata.get("xesam:artist") or [])
    title = metadata.get("xesam:title") or "?"
    return f"{artists} - {title}" if artists else title


def wait_until(condition, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.5)
    return condition()


def detect_launch_command():
    if shutil.which("flatpak"):
        result = subprocess.run(["flatpak", "info", FLATPAK_APP_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return ["flatpak", "run", FLATPAK_APP_ID]
    if shutil.which("spotify"):
        return ["spotify"]
    return None


class Spotify:
    def __init__(self, bus, launch_command):
        self._bus = bus
        self._launch_command = launch_command

    def read_player(self):
        """Return player properties (PlaybackStatus, Metadata, ...) or None if Spotify is not running."""
        try:
            result = self._call(PROPERTIES_IFACE, "GetAll", GLib.Variant("(s)", (PLAYER_IFACE,)), "(a{sv})")
            return result[0]
        except GLib.Error:
            return None

    def restart(self, finished_track_id):
        """
        Close Spotify, start it again, and resume playback.
        finished_track_id is the track that ended before the ad; skip ahead if the client restores on it.
        """
        self._arm_window_keeper()
        log("Stopping Spotify...")
        self._shutdown()
        log(f"Starting Spotify: {' '.join(self._launch_command)}")
        # Drop the activation token from a menu launch, or KWin will not raise the restarted window.
        env = {key: value for key, value in os.environ.items() if key not in ("XDG_ACTIVATION_TOKEN", "DESKTOP_STARTUP_ID")}
        subprocess.Popen(
            self._launch_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True)
        if not wait_until(lambda: self.read_player() is not None, timeout=40):
            log("Spotify did not appear on D-Bus after start.")
            return
        self._resume(finished_track_id)

    def _shutdown(self):
        try:
            self._call(ROOT_IFACE, "Quit")
        except GLib.Error as error:
            log(f"MPRIS Quit failed: {error.message}")
        if wait_until(lambda: not self._process_alive(), timeout=10):
            return
        log("Spotify did not quit in time, sending SIGTERM.")
        self._pkill("-TERM")
        if wait_until(lambda: not self._process_alive(), timeout=5):
            return
        log("Spotify is still alive, sending SIGKILL.")
        self._pkill("-KILL")
        wait_until(lambda: not self._process_alive(), timeout=5)

    def _resume(self, finished_track_id):
        skipped = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            player = self.read_player()
            if player is not None:
                metadata = player.get("Metadata") or {}
                if player.get("PlaybackStatus") == "Playing":
                    log(f"Playback resumed: {describe(metadata)}")
                    return
                try:
                    if not skipped and finished_track_id and metadata.get("mpris:trackid") == finished_track_id:
                        self._call(PLAYER_IFACE, "Next")
                        skipped = True
                    else:
                        self._call(PLAYER_IFACE, "Play")
                except GLib.Error:
                    # The client is still loading; try again.
                    pass
            time.sleep(1)
        log("Could not resume playback within 30 seconds.")

    def _arm_window_keeper(self):
        """Load keep_window.js into KWin so the new Spotify window opens where the old one was and does not take focus."""
        try:
            # A script from a previous restart may still be loaded; KWin will not load a second one with the same name.
            self._call_on(KWIN_BUS_NAME, "/Scripting", KWIN_SCRIPTING_IFACE, "unloadScript", GLib.Variant("(s)", (KWIN_SCRIPT_NAME,)), "(b)")
            script_id = self._call_on(
                KWIN_BUS_NAME,
                "/Scripting",
                KWIN_SCRIPTING_IFACE,
                "loadScript",
                GLib.Variant("(ss)", (KWIN_SCRIPT_PATH, KWIN_SCRIPT_NAME)),
                "(i)")[0]
            if script_id < 0:
                log("KWin refused to load keep_window.js, window placement will not be restored.")
                return
            self._call_on(KWIN_BUS_NAME, f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        except GLib.Error as error:
            log(f"KWin is not available, window placement will not be restored: {error.message}")

    def _call(self, interface, method, parameters=None, reply_type=None):
        return self._call_on(BUS_NAME, OBJECT_PATH, interface, method, parameters, reply_type)

    def _call_on(self, bus_name, path, interface, method, parameters=None, reply_type=None):
        result = self._bus.call_sync(
            bus_name,
            path,
            interface,
            method,
            parameters,
            GLib.VariantType(reply_type) if reply_type else None,
            Gio.DBusCallFlags.NONE,
            DBUS_TIMEOUT_MS,
            None)
        return result.unpack() if result is not None else None

    @staticmethod
    def _process_alive():
        result = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", PROCESS_NAME], stdout=subprocess.DEVNULL)
        return result.returncode == 0

    @staticmethod
    def _pkill(signal):
        subprocess.run(["pkill", signal, "-u", str(os.getuid()), "-x", PROCESS_NAME], stdout=subprocess.DEVNULL)


def watch(spotify, interval, cooldown):
    last_track_id = None
    last_restart = 0.0
    while True:
        player = spotify.read_player()
        if player is not None:
            metadata = player.get("Metadata") or {}
            track_id = metadata.get("mpris:trackid")
            if is_ad(metadata):
                # Only react to a playing ad. Leave it alone if the user paused it.
                if player.get("PlaybackStatus") == "Playing" and time.monotonic() - last_restart >= cooldown:
                    log(f"Ad detected: {describe(metadata)} ({track_id})")
                    spotify.restart(last_track_id)
                    last_restart = time.monotonic()
            elif track_id and track_id != last_track_id:
                last_track_id = track_id
                log(f"Now playing: {describe(metadata)}")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Restarts Spotify when an ad starts and resumes the music.")
    parser.add_argument("--interval", type=float, default=1.0, help="polling interval in seconds (default: 1)")
    parser.add_argument("--cooldown", type=float, default=10.0, help="minimum seconds between restarts (default: 10)")
    parser.add_argument("--command", help="command to start Spotify (default: auto-detect flatpak or native)")
    parser.add_argument("--restart-now", action="store_true", help="restart Spotify once and exit (for testing)")
    args = parser.parse_args()

    launch_command = args.command.split() if args.command else detect_launch_command()
    if not launch_command:
        log("Spotify not found: neither flatpak com.spotify.Client nor 'spotify' in PATH. Use --command.")
        return 1

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    spotify = Spotify(bus, launch_command)

    if args.restart_now:
        spotify.restart(finished_track_id=None)
        return 0

    log(f"Watching Spotify for ads (launch command: {' '.join(launch_command)}).")
    try:
        watch(spotify, args.interval, args.cooldown)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
