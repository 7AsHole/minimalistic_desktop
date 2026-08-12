"""
Toggles the native Windows desktop icons on/off.
This mimics right-click desktop > View > "Show desktop icons".

Note: Windows exposes this as a TOGGLE, not an explicit on/off command,
so we can't directly query current state without extra digging. We track
state ourselves in main.py to avoid accidentally toggling it back on.
"""
import ctypes

WM_COMMAND = 0x0111
TOGGLE_DESKTOP_ICONS = 0x7402


def toggle_desktop_icons() -> None:
    """Sends the same message Explorer sends when you click 'Show desktop icons'."""
    progman = ctypes.windll.user32.FindWindowW("Progman", None)
    if not progman:
        raise RuntimeError("Could not find Progman window - is Explorer running?")
    ctypes.windll.user32.SendMessageW(progman, WM_COMMAND, TOGGLE_DESKTOP_ICONS, 0)
