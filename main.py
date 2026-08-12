"""
Minimalistic Desktop - v1 (steps 1-4)

1. Black desktop wallpaper (+ optional lockscreen, Pro/Enterprise + admin only)
2. Native desktop icons hidden, replaced by a text-only overlay list
3. Clock + calendar on the desktop overlay
4. Dark mode applied system-wide (closest we can get to a monochrome taskbar
   without injecting into Explorer - see README for why full icon
   recoloring isn't done here)

Run with a normal (non-admin) terminal for steps 1-4.
Only pass --lockscreen if you're on Windows Pro/Enterprise AND running as
Administrator.
"""
import argparse
import atexit
import os
import sys

if sys.platform != "win32":
    sys.exit("This app only runs on Windows.")

from modules import desktop_icons, state, theme, wallpaper
from modules.overlay import DesktopOverlay

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BLACK_IMAGE_PATH = os.path.join(ASSETS_DIR, "black.png")

_restored = False  # guard so restore never runs twice (e.g. atexit + explicit quit)


def apply_system_changes(hide_icons: bool, do_lockscreen: bool) -> dict:
    """Applies all changes and returns the snapshot needed to undo them later."""
    print("Snapshotting current wallpaper/theme so we can restore it later...")
    snapshot = state.capture_state(icons_will_be_hidden=hide_icons)
    state.save_state(snapshot)

    print("[1/4] Generating and setting black wallpaper...")
    wallpaper.generate_black_image(BLACK_IMAGE_PATH)
    wallpaper.set_wallpaper(BLACK_IMAGE_PATH)

    print("[2/4] Applying dark mode (apps + taskbar/start)...")
    theme.set_dark_mode(enable=True)

    if hide_icons:
        print("[3/4] Hiding native desktop icons (overlay will show text list instead)...")
        desktop_icons.toggle_desktop_icons()
    else:
        print("[3/4] Skipping icon hide (--keep-icons was passed).")

    if do_lockscreen:
        print("[4/4] Attempting lockscreen image (requires admin + Pro/Enterprise)...")
        from modules import lockscreen
        ok = lockscreen.set_lockscreen_image(BLACK_IMAGE_PATH)
        if not ok:
            print("      -> Failed. Either not running as admin, or you're on Windows Home.")
    else:
        print("[4/4] Skipping lockscreen (use --lockscreen to attempt it).")

    print("Restarting Explorer to apply changes cleanly...")
    theme.restart_explorer()
    return snapshot


def restore_now():
    """Restores from whatever snapshot is on disk. Safe to call multiple times."""
    global _restored
    if _restored:
        return
    saved = state.load_state()
    if not saved:
        print("Nothing to restore (no state.json found).")
        return
    print("\nReverting to your original desktop...")
    state.restore_all(saved)
    _restored = True


def main():
    parser = argparse.ArgumentParser(description="Minimalistic Desktop v1")
    parser.add_argument("--keep-icons", action="store_true",
                         help="Don't hide native desktop icons.")
    parser.add_argument("--lockscreen", action="store_true",
                         help="Also attempt to set a black lockscreen (needs admin + Pro/Enterprise).")
    parser.add_argument("--skip-system-changes", action="store_true",
                         help="Only launch the overlay, don't touch wallpaper/theme/icons "
                              "(no restore will happen either, since nothing changed).")
    parser.add_argument("--restore", action="store_true",
                         help="Don't launch anything - just restore from the last saved state and exit.")
    args = parser.parse_args()

    if args.restore:
        restore_now()
        return

    applied_changes = False
    if not args.skip_system_changes:
        apply_system_changes(hide_icons=not args.keep_icons, do_lockscreen=args.lockscreen)
        applied_changes = True
        # Safety net: covers Ctrl+C, unhandled exceptions, and normal interpreter exit.
        atexit.register(restore_now)

    print("Launching overlay... (Esc or the on-screen button to quit and restore)")
    app = DesktopOverlay(on_quit=restore_now if applied_changes else None)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        if applied_changes:
            restore_now()


if __name__ == "__main__":
    main()
