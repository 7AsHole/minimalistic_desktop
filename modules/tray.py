"""
Puts a small icon in the Windows notification area (the "hidden icons"
tray, reached via the ^ chevron next to the clock) so you can quit and
restore your desktop from there.

Windows owns the notification-area menu. Its direct "Quit & Restore" item
is deliberately kept as a reliable exit route, independent of the custom
status bar.

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
    base_dir = os.path.dirname(os.path.dirname(__file__))
    logo_path = os.path.join(base_dir, "assets", "logo.png")

    try:
        img = Image.open(logo_path)
        return img
    except FileNotFoundError:
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([4, 4, size - 4, size - 4], radius=12, fill="#00FF00")
        return img


class TrayIcon:
    """Wraps a pystray.Icon and runs its message loop on its own daemon
    thread, so it never blocks the Tkinter mainloop running on the main
    thread. Menu callbacks hop back onto Tk's thread via `root.after()`
    before they touch the overlay."""

    def __init__(self, root, on_quit):
        if pystray is None:
            raise RuntimeError(
                "pystray is not installed. Run: pip install pystray  "
                "(tray icon disabled until then)"
            )
        self._root = root
        self._on_quit = on_quit

        try:
            self._icon = pystray.Icon(
                "MinimalisticDesktop",
                icon=_build_icon_image(),
                title="Minimalistic Desktop - quit and restore",
                menu=pystray.Menu(
                    pystray.MenuItem("Quit && Restore", self._request_quit, default=True),
                ),
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create tray icon: {e}") from e

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stopped = False

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped = True
        try:
            self._icon.stop()
        except Exception:
            pass

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception as e:
            print(f"[tray] icon thread stopped unexpectedly: {e}")

    def _request_quit(self, icon, item):
        self._root.after(0, self._on_quit)
