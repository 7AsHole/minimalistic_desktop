"""
Reads Start Menu app shortcuts (.lnk/.url files) plus a handful of built-in
Windows system tools, so the overlay/status-bar can display them as
plain-text, searchable entries instead of icons.
"""
import os

START_MENU_DIRS = [
    os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
]

SYSTEM_TOOLS = [
    {"name": "Add or Remove Programs", "target": "appwiz.cpl", "path": "appwiz.cpl", "is_folder": False},
    {"name": "Settings", "target": "ms-settings:", "path": "ms-settings:", "is_folder": False},
    {"name": "Device Manager", "target": "devmgmt.msc", "path": "devmgmt.msc", "is_folder": False},
    {"name": "Control Panel", "target": "control", "path": "control", "is_folder": False},
    {"name": "Network & Internet Settings", "target": "ms-settings:network-wifi", "path": "ms-settings:network-wifi", "is_folder": False},
    {"name": "Display Settings", "target": "ms-settings:display", "path": "ms-settings:display", "is_folder": False},
    {"name": "Sound Settings", "target": "ms-settings:sound", "path": "ms-settings:sound", "is_folder": False},
]


def get_all_apps() -> list[dict]:
    """Recursively scans both Start Menu Programs folders for .lnk/.url
    shortcuts and appends built-in Windows system tools. Returns a deduped, 
    alphabetically sorted list of {name, target, path, is_folder}."""
    seen_names = set()
    items = []

    for tool in SYSTEM_TOOLS:
        key = tool["name"].lower()
        seen_names.add(key)
        items.append(tool)

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
                    continue
                seen_names.add(key)

                full_path = os.path.join(root, fname)
                items.append({
                    "name": name,
                    "target": full_path,
                    "path": full_path,
                    "is_folder": False,
                })

    return sorted(items, key=lambda x: x["name"].lower())