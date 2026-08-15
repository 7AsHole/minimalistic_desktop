"""
Minimalistic Desktop

1. Black desktop wallpaper
2. Native desktop icons replaced by a text-only overlay list
3. Clock + calendar on the desktop overlay
4. Custom bottom status bar with scratch-built controls:
   - Pinned apps, clock/date, volume slider popup, Wi-Fi details popup,
     battery indicator, mic toggle.

Does NOT modify or interfere with native taskbar settings or Explorer.
"""
import argparse
import atexit
import ctypes
import os
import sys

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

if sys.platform != "win32":
    sys.exit("This app only runs on Windows.")

from modules import startup, state, theme, wallpaper
from modules.overlay import DesktopOverlay
from modules.statusbar import StatusBar

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BLACK_IMAGE_PATH = os.path.join(ASSETS_DIR, "black.png")

_restored = False


def apply_system_changes() -> dict:
    """Applies wallpaper and theme settings safely without restarting Explorer."""
    print("Snapshotting current wallpaper/theme state...")
    snapshot = state.capture_state()
    state.save_state(snapshot)

    print("[wallpaper] Setting black wallpaper...")
    wallpaper.generate_black_image(BLACK_IMAGE_PATH)
    wallpaper.set_wallpaper(BLACK_IMAGE_PATH)

    print("[theme] Applying dark mode...")
    theme.set_dark_mode(enable=True)

    return snapshot


def restore_now():
    """Restores from snapshot if applicable."""
    global _restored
    if _restored:
        return
    saved = state.load_state()
    if not saved:
        print("Nothing to restore (no state.json found).")
        return
    print("\nReverting original settings...")
    state.restore_all(saved)
    _restored = True


def main():
    parser = argparse.ArgumentParser(description="Minimalistic Desktop")
    parser.add_argument("--no-statusbar", action="store_true",
                        help="Don't launch the custom bottom status bar.")
    parser.add_argument("--skip-system-changes", action="store_true",
                        help="Only launch the overlay, don't touch wallpaper/theme.")
    parser.add_argument("--restore", action="store_true",
                        help="Restore from saved state and exit.")
    args = parser.parse_args()

    if args.restore:
        restore_now()
        return

    startup.enable()

    applied_changes = False
    if not args.skip_system_changes:
        apply_system_changes()
        applied_changes = True
        atexit.register(restore_now)

    tray_icon = None

    def handle_quit():
        if tray_icon is not None:
            tray_icon.stop()
        if applied_changes:
            restore_now()

    print("Launching Minimalistic Desktop...")

    status_bar = None

    def on_pins_changed():
        if status_bar is not None:
            status_bar.refresh_pins()

    app = DesktopOverlay(on_quit=handle_quit, on_pins_changed=on_pins_changed)

    if not args.no_statusbar:
        print("Launching custom status bar...")
        status_bar = StatusBar(app, on_quit=app.request_quit)

    try:
        from modules.tray import TrayIcon
        # The notification-area menu must remain usable even when the custom
        # status bar is disabled or unavailable.
        tray_icon = TrayIcon(app, on_quit=app.request_quit)
        tray_icon.start()
        print("Tray icon ready.")
    except RuntimeError as e:
        print(f"[tray] {e}")
    except Exception as e:
        print(f"[tray] Could not start tray icon: {e}")

    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        handle_quit()


if __name__ == "__main__":
    main()
