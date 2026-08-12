"""
Snapshots your desktop settings before Minimalistic Desktop touches anything,
and restores them on exit.

State is written to state.json next to this file, so even a hard crash or
task-manager kill leaves a record you can restore from later with:
    python main.py --restore
"""
import json
import os

from modules import taskbar_search, theme, wallpaper

STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")


def capture_state(icons_will_be_hidden: bool) -> dict:
    """Reads current wallpaper/theme/search-box values BEFORE we change anything."""
    apps_light, system_light = theme.get_theme_values()
    return {
        "wallpaper": wallpaper.get_current_wallpaper(),
        "apps_light": apps_light,
        "system_light": system_light,
        "icons_were_toggled": icons_will_be_hidden,  # so we know whether to toggle back
        "search_mode": taskbar_search.get_mode(),
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


def restore_all(state: dict, restart_explorer: bool = True) -> None:
    """Undoes wallpaper, theme, and icon-visibility changes using a saved snapshot."""
    from modules import desktop_icons

    print("Restoring previous wallpaper...")
    prev_wallpaper = state.get("wallpaper")
    if prev_wallpaper:
        try:
            wallpaper.set_wallpaper(prev_wallpaper)
        except FileNotFoundError:
            print(f"  -> Could not restore, original wallpaper file is gone: {prev_wallpaper}")

    print("Restoring previous theme...")
    theme.set_theme_values(state.get("apps_light", 1), state.get("system_light", 1))

    if state.get("icons_were_toggled"):
        print("Restoring desktop icon visibility...")
        desktop_icons.toggle_desktop_icons()  # toggling again flips it back to the original state

    if "search_mode" in state:
        print("Restoring taskbar search box visibility...")
        search_mode = state["search_mode"]
        if search_mode is None:
            taskbar_search.clear_mode()
        else:
            taskbar_search.set_mode(search_mode)

    if restart_explorer:
        print("Restarting Explorer to apply restored settings...")
        theme.restart_explorer()

    clear_state()
    print("Restore complete.")
