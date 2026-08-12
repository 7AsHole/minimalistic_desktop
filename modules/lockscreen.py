"""
Sets the Windows lock screen image via Group Policy registry key.

LIMITATIONS (read before relying on this):
- Requires Windows PRO, ENTERPRISE, or EDUCATION. Windows HOME does not
  honor this policy key at all - this will silently do nothing there.
- Requires the script to be run as Administrator (writes to HKEY_LOCAL_MACHINE).
- Takes effect after the next lock/sign-out, not instantly.
"""
try:
    import winreg
except ImportError:
    winreg = None

POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Windows\Personalization"


def set_lockscreen_image(image_path: str) -> bool:
    """Attempts to set the lock screen image. Returns True on success,
    False if it failed (most likely: not admin, or Windows Home)."""
    import os
    image_path = os.path.abspath(image_path)
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "LockScreenImage", 0, winreg.REG_SZ, image_path)
        winreg.CloseKey(key)
        return True
    except PermissionError:
        return False
    except OSError:
        return False
