"""
Snapshots your desktop settings before Minimalistic Desktop touches anything,
and restores them on exit.

State is written to state.json next to this file, so even a hard crash or
task-manager kill leaves a record you can restore from later with:
    python main.py --restore
"""
import json
import os

from modules import theme, wallpaper

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")


def capture_state() -> dict:
    """Reads current wallpaper/theme values BEFORE we change anything."""
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


def restore_all(state: dict, restart_explorer: bool = False) -> None:
    """Undoes wallpaper and theme changes using a saved snapshot."""
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
