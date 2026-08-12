"""
Reads shortcuts (.lnk files) and folders from the real Windows Desktop folder,
so our overlay can display them as plain text instead of icons.
"""
import glob
import os

import win32com.client


def get_desktop_items() -> list[dict]:
    """Returns a sorted list of {name, target, path, is_folder} for everything
    on the real desktop. Folders are flagged so the UI can still show a folder
    glyph for them later (per your rule: folders/img/vid keep visuals)."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    shell = win32com.client.Dispatch("WScript.Shell")
    items = []

    # .lnk shortcuts
    for f in glob.glob(os.path.join(desktop, "*.lnk")):
        try:
            sc = shell.CreateShortCut(f)
            name = os.path.splitext(os.path.basename(f))[0]
            items.append({
                "name": name,
                "target": sc.TargetPath or f,
                "path": f,
                "is_folder": False,
            })
        except Exception:
            continue

    # Real folders sitting directly on the desktop
    for entry in os.scandir(desktop):
        if entry.is_dir():
            items.append({
                "name": entry.name,
                "target": entry.path,
                "path": entry.path,
                "is_folder": True,
            })

    return sorted(items, key=lambda x: x["name"].lower())


# Windows keeps two Start Menu "Programs" folders: one for the current user
# and one shared across all accounts. Real apps can live in either (or both).
START_MENU_DIRS = [
    os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
]


def get_all_apps() -> list[dict]:
    """Recursively scans both Start Menu Programs folders for .lnk/.url
    shortcuts and returns a deduped, alphabetically sorted list of
    {name, target, path, is_folder}. This is what the overlay's search
    list uses - effectively 'every app you'd find by opening Start'."""
    shell = win32com.client.Dispatch("WScript.Shell")
    seen_names = set()
    items = []

    for base in START_MENU_DIRS:
        if not base or not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                lower = fname.lower()
                if not (lower.endswith(".lnk") or lower.endswith(".url")):
                    continue

                name = os.path.splitext(fname)[0]
                key = name.lower()
                if key in seen_names:
                    continue  # same app often appears in both per-user and all-users folders
                seen_names.add(key)

                full_path = os.path.join(root, fname)
                items.append({
                    "name": name,
                    # Launch the shortcut file, not its resolved target. This
                    # preserves arguments, working directories, and AppUserModel
                    # activation used by packaged Windows apps.
                    "target": full_path,
                    "path": full_path,
                    "is_folder": False,
                })

    return sorted(items, key=lambda x: x["name"].lower())
