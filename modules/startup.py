import os
import subprocess
import sys
import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MinimalisticDesktop"


def enable() -> None:
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    executable = pythonw if os.path.exists(pythonw) else sys.executable
    main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    command = subprocess.list2cmdline([executable, main_path, "--hide-start-search"])

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
