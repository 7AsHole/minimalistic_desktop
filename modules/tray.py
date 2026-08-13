"""
Puts a small icon in the Windows notification area (the "hidden icons"
tray, reached via the ^ chevron next to the clock) so you can quit and
restore your desktop from there instead of an on-screen button.

Right-click the icon for "Quit & Restore". Left-click does the same thing
for convenience.

Requires the `pystray` package (see requirements.txt). If it isn't
installed, TrayIcon() raises RuntimeError. In that case, close the process
from its terminal or Task Manager to quit.
"""
import os
import threading

from PIL import Image, ImageDraw

try:
    import pystray
except ImportError:
    pystray = None


def _build_icon_image() -> "Image.Image":
    """Loads the custom logo from the assets folder."""
    # Find the root folder by going up one directory from 'modules'
    base_dir = os.path.dirname(os.path.dirname(__file__))
    logo_path = os.path.join(base_dir, "assets", "logo.png")
    
    try:
        # Try to load your custom logo!
        img = Image.open(logo_path)
        return img
    except FileNotFoundError:
        # Fallback: If it can't find logo.ico, it draws the old "M" so it doesn't crash
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, size - 4, size - 4], radius=12, fill=(18, 18, 18, 255))
        draw.text((size / 2, size / 2), "M", fill="white", anchor="mm")
        return img


class TrayIcon:
    """Wraps a pystray.Icon and runs its message loop on its own daemon
    thread, so it never blocks the Tkinter mainloop running on the main
    thread. Menu callbacks fire on pystray's thread, so they hop back onto
    the Tk thread via root.after(0, ...) before touching the overlay."""

    def __init__(self, root, on_quit):
        if pystray is None:
            raise RuntimeError(
                "pystray is not installed. Run: pip install pystray  "
                "(tray icon disabled until then)"
            )
        self._root = root
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "MinimalisticDesktop",
            icon=_build_icon_image(),
            title="Minimalistic Desktop - click to quit & restore",
            menu=pystray.Menu(
                pystray.MenuItem("Quit && Restore", self._request_quit, default=True),
            ),
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stopped = False

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        try:
            self._icon.stop()
        except Exception:
            pass

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:
            pass  # tray backend hiccups shouldn't take the overlay down with it

    def _request_quit(self, icon, item):
        # We're on pystray's thread here - schedule the actual quit on the
        # Tk thread instead of touching the overlay directly.
        self._root.after(0, self._on_quit)
