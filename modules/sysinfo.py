"""
Small helpers that read live system info (battery, Wi-Fi, volume, microphone)
for the status bar widgets. No admin rights required for any of this.
"""
import ctypes
import os
import subprocess
from typing import Any

try:
    import winreg
except ImportError:
    winreg = None


_cached_volume_interface: Any = None


def get_brightness() -> int | None:
    """Returns the primary display brightness (0-100), if Windows exposes it.

    The WMI brightness API is available on most laptop/internal displays. Many
    external monitors do not expose software brightness control to Windows.
    """
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
                "-ErrorAction Stop | Select-Object -First 1 -ExpandProperty CurrentBrightness)",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        value = int(result.stdout.strip())
        return max(0, min(100, value))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def set_brightness(percent: int) -> bool:
    """Sets display brightness through Windows WMI; returns whether it succeeded."""
    value = max(0, min(100, int(percent)))
    command = (
        "$methods = Get-CimInstance -Namespace root/WMI "
        "-ClassName WmiMonitorBrightnessMethods -ErrorAction Stop; "
        "if ($null -eq $methods) { exit 1 }; "
        f"$methods | ForEach-Object {{ Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={value}}} -ErrorAction Stop }}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def get_hotspot_status() -> bool:
    try:
        ps = (
            "$profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile(); "
            "if ($null -eq $profile) { Write-Output 'Off'; exit }; "
            "$tether = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]::CreateFromConnectionProfile($profile); "
            "Write-Output $tether.TetheringOperationalState"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "On" in result.stdout
    except Exception:
        return False

def toggle_hotspot() -> None:
    try:
        ps = (
            "$profile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile(); "
            "$tether = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]::CreateFromConnectionProfile($profile); "
            "if ($tether.TetheringOperationalState -eq 'Off') { "
            "  $tether.StartTetheringAsync().AsTask().Wait() "
            "} else { "
            "  $tether.StopTetheringAsync().AsTask().Wait() "
            "}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        print(f"Toggle hotspot error: {e}")

def get_available_wifi_networks() -> list:
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "networks"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        ssids = []
        for line in result.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    if ssid and ssid not in ssids:
                        ssids.append(ssid)
        return ssids
    except Exception:
        return []

def connect_to_wifi(ssid: str) -> None:
    subprocess.run(
        ["netsh", "wlan", "connect", f"name={ssid}"],
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def is_wifi_autoconnect(ssid: str) -> bool:
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "profile", f"name={ssid}"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.splitlines():
            if "Connection mode" in line:
                return "auto" in line.casefold()
    except Exception:
        pass
    return False

def set_wifi_autoconnect(ssid: str, enable: bool) -> None:
    mode = "auto" if enable else "manual"
    subprocess.run(
        ["netsh", "wlan", "set", "profileparameter", f"name={ssid}", f"connectionmode={mode}"],
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    
def _activate_endpoint_volume(device: Any) -> Any:
    """Shared last step for both speaker and mic lookups: activate
    IAudioEndpointVolume on an already-resolved MMDevice and cast the
    result. Kept in one place since _get_volume_interface() and
    _get_mic_interface() were previously duplicating this verbatim."""
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _get_volume_interface() -> Any:
    global _cached_volume_interface
    if _cached_volume_interface is not None:
        return _cached_volume_interface

    from comtypes import GUID
    from comtypes.client import CreateObject
    from pycaw.pycaw import IMMDeviceEnumerator

    CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    enumerator: Any = CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
    endpoint: Any = enumerator.GetDefaultAudioEndpoint(0, 1)
    _cached_volume_interface = _activate_endpoint_volume(endpoint)
    return _cached_volume_interface


def get_volume() -> tuple[int, bool]:
    """Returns (volume_percent_0_to_100, is_muted)."""
    try:
        vol: Any = _get_volume_interface()
        percent = int(vol.GetMasterVolumeLevelScalar() * 100)
        muted = bool(vol.GetMute())
        return percent, muted
    except Exception:
        return 50, False


def set_volume(percent: int) -> None:
    """Sets master speaker volume (0 to 100)."""
    try:
        vol: Any = _get_volume_interface()
        scalar = max(0.0, min(1.0, percent / 100.0))
        vol.SetMasterVolumeLevelScalar(scalar, None)
    except Exception as e:
        print(f"Set volume error: {e}")


def toggle_volume_mute() -> None:
    """Toggles master speaker mute state."""
    try:
        vol: Any = _get_volume_interface()
        vol.SetMute(not vol.GetMute(), None)
    except Exception as e:
        print(f"Toggle volume mute error: {e}")



class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def get_battery() -> tuple[int | None, bool]:
    """Returns (percent, is_charging). percent is None on desktops with no
    battery (BatteryFlag == 0x80 / 128, or the unknown value 0xFF)."""
    status = _SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None, False

    battery_flag = status.BatteryFlag & 0xFF
    if battery_flag == 0x80 or battery_flag == 0xFF:
        return None, False

    percent = status.BatteryLifePercent & 0xFF
    if percent > 100:
        percent = None
    charging = status.ACLineStatus == 1
    return percent, charging



def get_wifi_status() -> tuple[bool, str | None]:
    """Returns (connected, ssid) by shelling out to `netsh wlan show interfaces`."""
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = result.stdout
    except Exception:
        return False, None

    ssid = None
    connected = False

    for raw_line in out.splitlines():
        line = raw_line.strip()
        lower = line.lower()

        if lower.startswith("ssid") and "bssid" not in lower:
            parts = line.split(":", 1)
            if len(parts) == 2:
                ssid = parts[1].strip() or None
                if ssid:
                    connected = True
                    break

    if connected:
        return True, ssid

    try:
        result = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        in_wifi_section = False
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.endswith(":") and "." not in line:
                header = line.casefold()
                in_wifi_section = any(term in header for term in ("wi-fi", "wireless", "wlan"))
                continue
            if in_wifi_section and ":" in line and any(
                marker in line.casefold() for marker in ("ipv4", "ipv6", "default gateway")
            ):
                value = line.split(":", 1)[1].strip()
                if value:
                    return True, None
    except Exception:
        pass

    return False, None



_cached_mic_interface: Any = None


def _get_mic_interface() -> Any:
    global _cached_mic_interface
    if _cached_mic_interface is not None:
        return _cached_mic_interface

    from pycaw.pycaw import AudioUtilities

    device: Any = AudioUtilities.GetMicrophone()
    if device is None:
        raise RuntimeError("No microphone found")

    _cached_mic_interface = _activate_endpoint_volume(device)
    return _cached_mic_interface


def is_mic_muted() -> bool:
    try:
        mic: Any = _get_mic_interface()
        return bool(mic.GetMute())
    except Exception:
        return False


def toggle_mic_mute() -> None:
    try:
        mic: Any = _get_mic_interface()
        mic.SetMute(not mic.GetMute(), None)
    except Exception as e:
        print(f"Mic toggle failed: {e}")



def get_all_notify_icon_apps() -> list[dict]:
    """Reads HKCU\\Control Panel\\NotifyIconSettings - the registry key
    Windows itself uses to remember every app that's ever registered a
    notification-area icon, and whether it's pinned to "always show" or
    collapsed into the hidden-icons overflow ('IsPromoted' 0/1). There's
    no official API for enumerating other processes' tray icons; this is
    the same registry-backed approach tools like NirSoft's TrayIconsView
    use. Returns a deduped, name-sorted list of
    {'exe', 'name', 'promoted'} for entries whose executable still exists
    on disk. Callers should further filter by which ones are actually
    running right now (e.g. via running_apps.is_running) if they only
    want live icons."""
    if winreg is None:
        return []

    base = r"Control Panel\NotifyIconSettings"
    seen: set[str] = set()
    apps: list[dict] = []

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1

                exe = None
                promoted = 0
                try:
                    with winreg.OpenKey(key, subkey_name) as sub:
                        try:
                            exe, _ = winreg.QueryValueEx(sub, "ExecutablePath")
                        except FileNotFoundError:
                            continue
                        try:
                            promoted, _ = winreg.QueryValueEx(sub, "IsPromoted")
                        except FileNotFoundError:
                            promoted = 0
                except OSError:
                    continue

                if not exe or exe in seen or not os.path.exists(exe):
                    continue
                seen.add(exe)
                apps.append({
                    "exe": exe,
                    "name": os.path.splitext(os.path.basename(exe))[0],
                    "promoted": bool(promoted),
                })
    except FileNotFoundError:
        pass

    return sorted(apps, key=lambda a: a["name"].lower())
