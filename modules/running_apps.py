import os
import re
import psutil
import win32con
import win32gui
import win32process
import win32com.client

_shell = None

_lnk_target_cache: dict[str, str] = {}

def _get_shell():
    global _shell
    if _shell is None:
        _shell = win32com.client.Dispatch("WScript.Shell")
    return _shell


def _resolve_exe_name(target_path: str) -> str:
    if target_path in _lnk_target_cache:
        return _lnk_target_cache[target_path]

    if target_path.lower().endswith(".lnk"):
        try:
            real_path = _get_shell().CreateShortCut(target_path).Targetpath
            exe_name = os.path.basename(real_path).lower()
        except Exception:
            exe_name = os.path.basename(target_path).lower().replace(".lnk", ".exe")
    else:
        exe_name = os.path.basename(target_path).lower()

    _lnk_target_cache[target_path] = exe_name
    return exe_name


def _running_exe_names() -> set[str]:
    names = set()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name:
            names.add(name.lower())
    return names


def get_running_snapshot() -> set[str]:
    return _running_exe_names()


def is_running(target_path: str, running_snapshot: set[str] | None = None) -> bool:
    if not target_path:
        return False

    target_path = target_path.strip('"\'')
    real_exe_name = _resolve_exe_name(target_path)
    running_processes = running_snapshot if running_snapshot is not None else _running_exe_names()

    if real_exe_name and real_exe_name.endswith(".exe"):
        if real_exe_name in running_processes:
            return True

    fallback_name = os.path.basename(target_path).lower().replace(".lnk", ".exe")
    if fallback_name in running_processes:
        return True

    return False


def _windows_for_exe(exe_name: str) -> list[int]:
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
    if not target_path:
        return

    target_path = target_path.strip('"\'')
    real_exe_name = _resolve_exe_name(target_path)

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