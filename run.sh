#!/usr/bin/env bash
# Starts spoty_reloader.py in the background.
# Usage: ./run.sh [start|stop|restart|status|log] [spoty_reloader.py arguments]
#        ./run.sh spotify [%U] — start Spotify together with the watcher (for a menu entry)
set -euo pipefail

dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$dir/spoty_reloader.py"
log_file="${XDG_STATE_HOME:-$HOME/.local/state}/spoty-reloader.log"

running_pids() {
    # Match only a python interpreter running this script, not an editor or less that has the file open.
    pgrep -u "$UID" -f "^[^ ]*python[^ ]* $script( |$)" || true
}

start() {
    local pids
    pids="$(running_pids)"
    if [[ -n "$pids" ]]; then
        echo "Already running (PID $(echo $pids))."
        return 0
    fi

    mkdir -p "$(dirname "$log_file")"
    nohup python3 "$script" "$@" >>"$log_file" 2>&1 </dev/null &
    local pid=$!
    disown

    # Catch an immediate crash, for example when Spotify is not found.
    sleep 1
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "Failed to start, last log lines:" >&2
        tail -n 5 "$log_file" >&2
        return 1
    fi
    echo "Started (PID $pid). Log: $log_file"
}

stop() {
    local pids
    pids="$(running_pids)"
    if [[ -z "$pids" ]]; then
        echo "Not running."
        return 0
    fi
    kill $pids
    echo "Stopped (PID $(echo $pids))."
}

launch_spotify() {
    # For a menu entry: start the watcher if it is not running, then launch Spotify itself.
    start >/dev/null || true
    exec flatpak run --branch=stable --arch=x86_64 --command=spotify --file-forwarding com.spotify.Client @@u "$@" @@
}

status() {
    local pids
    pids="$(running_pids)"
    if [[ -n "$pids" ]]; then
        echo "Running (PID $(echo $pids)). Log: $log_file"
    else
        echo "Not running."
    fi
}

command="${1:-start}"
shift || true

case "$command" in
    start) start "$@" ;;
    stop) stop ;;
    restart) stop; sleep 1; start "$@" ;;
    spotify) launch_spotify "$@" ;;
    status) status ;;
    log) tail -n 50 -f "$log_file" ;;
    *)
        echo "Usage: $0 [start|stop|restart|status|log|spotify] [args]" >&2
        exit 2
        ;;
esac
