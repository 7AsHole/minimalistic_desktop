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
    # 1. Try to find the standard Progman window
    hwnd = ctypes.windll.user32.FindWindowW("Progman", None)
    
    # 2. If Progman is missing (common during wallpaper changes), look for WorkerW
    if not hwnd:
        hwnd = ctypes.windll.user32.FindWindowW("WorkerW", None)
        
    # 3. If neither is found, Explorer is actually down/restarting
    if not hwnd:
        raise RuntimeError("Could not find Progman or WorkerW window - is Explorer running?")
        
    # Send the toggle command to whichever window we found
    ctypes.windll.user32.SendMessageW(hwnd, WM_COMMAND, TOGGLE_DESKTOP_ICONS, 0)