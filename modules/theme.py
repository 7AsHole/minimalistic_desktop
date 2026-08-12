"""
Toggles Windows dark mode (apps + taskbar/start) via the per-user registry.
No admin rights required - this writes to HKEY_CURRENT_USER only.
"""
import subprocess
import time

try:
    import winreg
except ImportError:
    winreg = None  # allows the module to be imported (but not used) on non-Windows for linting


PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def get_theme_values() -> tuple[int, int]:
    """Reads current (AppsUseLightTheme, SystemUsesLightTheme) so they can be restored later.
    Defaults to (1, 1) i.e. light mode if the key/values don't exist yet."""
    if winreg is None:
        raise RuntimeError("Theme settings are only available on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 0, winreg.KEY_READ) as key:
            apps, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            system, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return apps, system
    except FileNotFoundError:
        return 1, 1


def set_theme_values(apps_light: int, system_light: int) -> None:
    """Writes explicit values back - used both by set_dark_mode() and by restore."""
    if winreg is None:
        raise RuntimeError("Theme settings are only available on Windows.")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, apps_light)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, system_light)


def set_dark_mode(enable: bool = True) -> None:
    """Flips both AppsUseLightTheme and SystemUsesLightTheme (taskbar/start menu)."""
    value = 0 if enable else 1
    set_theme_values(value, value)


def restart_explorer() -> None:
    """Kills and relaunches explorer.exe so theme/wallpaper changes apply immediately.
    Your desktop will flicker/disappear for a second - this is normal."""
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False)
    time.sleep(1.5)
    subprocess.Popen("explorer.exe")
