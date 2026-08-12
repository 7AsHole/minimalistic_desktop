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
