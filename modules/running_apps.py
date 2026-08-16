"""
Matches your pinned shortcuts to currently-running processes, so the status
bar can show a "running" indicator and do focus-or-launch on click, just
like the real taskbar.
"""
import os
import re
import psutil
import win32con
import win32gui
import win32process
import win32com.client


def _running_exe_names() -> set[str]:
    """Lowercased basenames of every running process's exe."""
    names = set()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name:
            names.add(name.lower())
    return names


def is_running(target_path: str) -> bool:
    """True if a process matching this shortcut's target is currently running."""
    if not target_path:
        return False

    target_path = target_path.strip('"\'')
    
    real_exe_name = ""
    if target_path.lower().endswith(".lnk"):
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            real_path = shell.CreateShortCut(target_path).Targetpath
            real_exe_name = os.path.basename(real_path).lower()
        except Exception:
            pass
    else:
        real_exe_name = os.path.basename(target_path).lower()

    running_processes = _running_exe_names()

    if real_exe_name and real_exe_name.endswith(".exe"):
        if real_exe_name in running_processes:
            return True

    fallback_name = os.path.basename(target_path).lower().replace(".lnk", ".exe")
    if fallback_name in running_processes:
        return True

    return False


def _windows_for_exe(exe_name: str) -> list[int]:
    """Top-level, visible, titled windows owned by processes named exe_name."""
    exe_name = exe_name.lower()
    matches = []

    def _callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            if proc.name().lower() == exe_name:
                matches.append(hwnd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    win32gui.EnumWindows(_callback, None)
    return matches


def focus_or_launch(target_path: str) -> None:
    """Taskbar-like click behavior: if the app already has a window open,
    bring it to front (restoring it if minimized); otherwise launch it."""
    if not target_path:
        return

    target_path = target_path.strip('"\'')
    real_exe_name = ""

    if target_path.lower().endswith(".lnk"):
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            real_path = shell.CreateShortCut(target_path).Targetpath
            real_exe_name = os.path.basename(real_path).lower()
        except Exception:
            real_exe_name = os.path.basename(target_path).lower().replace(".lnk", ".exe")
    else:
        real_exe_name = os.path.basename(target_path).lower()

    windows = _windows_for_exe(real_exe_name) if real_exe_name.endswith(".exe") else []

    if windows:
        hwnd = windows[0]
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    else:
        try:
            os.startfile(target_path)
        except Exception as e:
            print(f"Failed to open {target_path}: {e}")

def get_open_window_apps() -> list[dict]:
    """Scans for top-level visible windows and returns app dicts 
    so unpinned open apps can be displayed on the status bar."""
    apps = []
    seen_exes = set()

    def _callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd)
        if title in ["Program Manager", "Settings", "Windows Input Experience"]:
            return True

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            exe_path = proc.exe()
            exe_name = os.path.basename(exe_path).lower()

            if exe_name and exe_name not in seen_exes:
                seen_exes.add(exe_name)
                apps.append({
                    "name": proc.name().replace(".exe", "").capitalize(),
                    "path": exe_path,
                    "target": exe_path
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return True

    win32gui.EnumWindows(_callback, None)
    return apps