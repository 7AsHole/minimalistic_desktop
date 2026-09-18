import json
import os

from modules import theme, wallpaper

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")

def capture_state() -> dict:
    apps_light, system_light = theme.get_theme_values()
    return {
        "wallpaper": wallpaper.get_current_wallpaper(),
        "apps_light": apps_light,
        "system_light": system_light,
        "applied": True,
    }


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def load_state() -> dict | None:
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH) as f:
        return json.load(f)


def clear_state() -> None:
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)


def get_or_capture_state() -> dict:
    """Use this instead of calling capture_state() + save_state() directly
    at startup. If state.json already exists, a previous run never made it
    to a clean restore (crash, hard kill, power loss) - that file is the
    real "before we touched anything" snapshot, so we reuse it as-is
    instead of overwriting it with the current (already-modified) desktop.
    Only when nothing is on disk do we take a fresh snapshot."""
    existing = load_state()
    if existing is not None:
        print("Found a leftover state.json from a previous run that didn't "
              "restore cleanly - reusing it instead of overwriting it.")
        return existing

    snapshot = capture_state()
    save_state(snapshot)
    return snapshot


def restore_all(state: dict, restart_explorer: bool = False) -> None:
    print("Restoring previous wallpaper...")
    prev_wallpaper = state.get("wallpaper")
    if prev_wallpaper:
        try:
            wallpaper.set_wallpaper(prev_wallpaper)
        except FileNotFoundError:
            print(f"  -> Could not restore, original wallpaper file is gone: {prev_wallpaper}")

    print("Restoring previous theme...")
    theme.set_theme_values(state.get("apps_light", 1), state.get("system_light", 1))

    if restart_explorer:
        print("Restarting Explorer...")
        theme.restart_explorer()

    clear_state()
    print("Restore complete.")