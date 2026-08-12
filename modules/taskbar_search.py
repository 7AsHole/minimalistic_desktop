"""
Hides/shows the Windows TASKBAR search box (the pill/icon next to the
Start button).

IMPORTANT LIMITATION: this is NOT the search field inside the opened Start
Menu itself. Microsoft doesn't expose any API, registry key, or Group
Policy - admin or not - that lets a third-party app remove Start Menu's
own internal search. This only controls the separate taskbar search
control, which is the closest real equivalent. No admin rights required.
"""
try:
    import winreg
except ImportError:
    winreg = None

SEARCH_KEY = r"Software\Microsoft\Windows\CurrentVersion\Search"
VALUE_NAME = "SearchboxTaskbarMode"

# 0 = hidden, 1 = icon only, 2 = full search box (default on most installs)
HIDDEN = 0
ICON_ONLY = 1
BOX = 2


def get_mode() -> int | None:
    """Reads the current taskbar search mode, or None when Windows uses its default."""
    if winreg is None:
        raise RuntimeError("Taskbar search settings are only available on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SEARCH_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return value
    except FileNotFoundError:
        return None


def set_mode(mode: int) -> None:
    if winreg is None:
        raise RuntimeError("Taskbar search settings are only available on Windows.")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, SEARCH_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, mode)


def clear_mode() -> None:
    """Returns the setting to Windows' default by removing the override."""
    if winreg is None:
        raise RuntimeError("Taskbar search settings are only available on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SEARCH_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def hide() -> None:
    set_mode(HIDDEN)
