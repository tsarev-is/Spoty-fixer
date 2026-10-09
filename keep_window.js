// KWin script loaded by spoty_reloader.py before restarting Spotify.
// Remembers where the Spotify window was and which window was active, then places the new
// Spotify window on the same monitor, desktop, and position without giving it focus. Runs once.

const EXPIRES_MS = 60000;
const startedAt = Date.now();

function isSpotify(window) {
    return window.normalWindow && window.resourceClass === "spotify";
}

function isOnCurrentDesktop(window) {
    return window.onAllDesktops || window.desktops.includes(workspace.currentDesktop);
}

const old = workspace.windowList().find(isSpotify);
const active = workspace.activeWindow;
const saved = old && {
    x: old.frameGeometry.x,
    y: old.frameGeometry.y,
    desktops: old.desktops,
    minimized: old.minimized,
    maximizeMode: old.maximizeMode,
    // If the user was in Spotify itself before the restart, the new window keeps focus.
    focusBackTo: active && !isSpotify(active) ? active : null,
};

let handled = false;

workspace.windowAdded.connect(window => {
    if (handled || !saved || !isSpotify(window) || Date.now() - startedAt > EXPIRES_MS) {
        return;
    }
    handled = true;

    // By now KWin has already placed the window on the active monitor and activated it.
    // Restore focus before moving the window: an active window on another desktop would switch the user there.
    const focusBackTo = saved.focusBackTo;
    if (focusBackTo && workspace.windowList().includes(focusBackTo) && isOnCurrentDesktop(focusBackTo)) {
        workspace.activeWindow = focusBackTo;
    }

    window.desktops = saved.desktops;
    window.setMaximize(false, false);
    // Move only; leave the size alone. Spotify restores it itself, and KWin applies a resize
    // only after the client replies, which a window on a hidden desktop may never do.
    const geometry = window.frameGeometry;
    window.frameGeometry = { x: saved.x, y: saved.y, width: geometry.width, height: geometry.height };
    if (saved.maximizeMode !== 0) {
        window.setMaximize((saved.maximizeMode & 1) !== 0, (saved.maximizeMode & 2) !== 0);
    }
    window.minimized = saved.minimized;
});
