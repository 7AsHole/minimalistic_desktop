"""
Minimalistic Desktop Status Bar (Bottom Strip)

A clean, modern bottom status bar built from scratch in CustomTkinter:
- Pinned app shortcuts on the left with executable icons.
- Clock and date in the center (clicking opens a mini calendar popup).
- Built-from-scratch custom controls on the right:
    - Master Volume button (opens a custom volume slider popup).
    - Wi-Fi status button (opens a custom network details popup).
    - Microphone mute toggle.
    - Battery indicator.
    - Menu button (opens the app menu - Quit & Restore - built the same
      way as the other popups here; the Windows tray icon opens this same
      popup instead of spawning a separate window of its own).

Features lightweight edge-reveal auto-hide without touching or interfering with
any native Windows Taskbar settings or processes.
"""
import calendar
import ctypes
import asyncio
import os
import threading
import time
from ctypes import wintypes
from datetime import datetime

import customtkinter as ctk
import win32api
import win32gui

from . import pins, running_apps, sysinfo
from .shortcuts import get_all_apps

FONT_FAMILY = "Bahnschrift"
BAR_HEIGHT = 44
ICON_SIZE = 24
RUNNING_COLOR = "#c5c5c5"

CLOCK_REFRESH_MS = 1_000
RUNNING_REFRESH_MS = 1_500
BATTERY_REFRESH_MS = 15_000
WIFI_REFRESH_MS = 10_000
VOLUME_REFRESH_MS = 2_000
BRIGHTNESS_REFRESH_MS = 5_000

AUTOHIDE_POLL_MS = 300
EDGE_TRIGGER_PX = 10
HIDE_DELAY_MS = 350

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_S = 0x53
VK_M = 0x4D
VK_D = 0x44


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
    ]


class GlobalHotkey:
    """Registers multiple global hotkeys with Windows, even when out of focus."""

    def __init__(self, bindings: dict):
        # Accepts a dictionary of {vk_code: callback_function}
        self._bindings = bindings
        self._thread_id = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self):
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        
        # Register all hotkeys provided in the dictionary
        for vk_code in self._bindings:
            if not user32.RegisterHotKey(None, vk_code, MOD_CONTROL | MOD_NOREPEAT, vk_code):
                print(f"[hotkeys] Ctrl+{chr(vk_code)} is already in use.")

        message = _MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    vk_code = message.wParam
                    if vk_code in self._bindings:
                        try:
                            # Trigger the assigned callback
                            self._bindings[vk_code]()
                        except Exception:
                            pass
        finally:
            for vk_code in self._bindings:
                user32.UnregisterHotKey(None, vk_code)


_icon_cache: dict[str, ctk.CTkImage | None] = {}


def _extract_icon_image(path: str, size: int = ICON_SIZE) -> ctk.CTkImage | None:
    if path in _icon_cache:
        return _icon_cache[path]

    img = None
    try:
        import win32ui
        from PIL import Image

        large, small = win32gui.ExtractIconEx(path, 0, 1)
        handles = (large or []) + (small or [])
        if large:
            hicon = large[0]
            ico_x = win32api.GetSystemMetrics(0)  # SM_CXICON
            ico_y = win32api.GetSystemMetrics(1)  # SM_CYICON

            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            hbmp = win32ui.CreateBitmap()
            hbmp.CreateCompatibleBitmap(hdc, ico_x, ico_y)
            hdc_mem = hdc.CreateCompatibleDC()
            hdc_mem.SelectObject(hbmp)
            hdc_mem.DrawIcon((0, 0), hicon)

            bmpinfo = hbmp.GetInfo()
            bmpstr = hbmp.GetBitmapBits(True)
            raw = Image.frombuffer(
                "RGBA", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRA", 0, 1
            )
            img = raw.resize((size, size), Image.Resampling.LANCZOS)

        for h in handles:
            win32gui.DestroyIcon(h)
    except Exception:
        img = None

    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size)) if img else None
    _icon_cache[path] = ctk_img
    return ctk_img

# ---------------- Custom Popup Windows ----------------
# ---------------- Spotify / Windows Media Control ----------------

class SpotifyMediaController:
    """Controls Spotify through Windows Global System Media Transport Controls.

    This talks to the Windows media session rather than Spotify's Web API,
    so no Spotify API key or login is required.
    """

    @staticmethod
    def _is_spotify_session(session) -> bool:
        try:
            app_id = (session.source_app_user_model_id or "").casefold()
            return "spotify" in app_id
        except Exception:
            return False

    @staticmethod
    async def _get_spotify_session():
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        manager = await MediaManager.request_async()
        sessions = manager.get_sessions()

        # Try to find Spotify first
        for session in sessions:
            if SpotifyMediaController._is_spotify_session(session):
                return session

        # Fallback: Just return whatever media is currently active!
        return manager.get_current_session()

    @staticmethod
    async def _read_thumbnail(thumbnail):
        if thumbnail is None:
            return None

        try:
            from winrt.windows.storage.streams import DataReader
            
            readable_stream = await thumbnail.open_read_async()
            size = readable_stream.size
            
            reader = DataReader(readable_stream)
            await reader.load_async(size)
            
            # Create an empty bytearray of the exact size needed
            byte_buffer = bytearray(size)
            
            # The modern winrt way to extract image bytes
            reader.read_bytes(byte_buffer)
            
            return bytes(byte_buffer)

        except Exception as error:
            print(f"[media] Could not read album art: {error}")
            return None
    
    @staticmethod
    async def _get_info_async():
        session = await SpotifyMediaController._get_spotify_session()

        if session is None:
            return None

        try:
            properties = await session.try_get_media_properties_async()
            playback = session.get_playback_info()
            
            # 1. Determine playing state first
            playback_status = playback.playback_status
            is_playing = int(playback_status) == 4

            # 2. Calculate live timeline
            timeline = session.get_timeline_properties()
            position = 0
            duration = 0
            
            if timeline:
                try:
                    from datetime import datetime, timezone
                    pos_sec = timeline.position.total_seconds()
                    duration = timeline.end_time.total_seconds()
                    
                    if is_playing:
                        # Add the elapsed time since the last Windows snapshot
                        now = datetime.now(timezone.utc)
                        elapsed = (now - timeline.last_updated_time).total_seconds()
                        position = pos_sec + elapsed
                    else:
                        position = pos_sec
                except Exception:
                    pass

            thumbnail_data = None
            if properties is not None and properties.thumbnail is not None:
                thumbnail_data = await SpotifyMediaController._read_thumbnail(properties.thumbnail)

            if properties is None:
                return None

            return {
                "title": properties.title or "Unknown Song",
                "artist": properties.artist or "Unknown Artist",
                "album": properties.album_title or "",
                "status": str(playback_status),
                "is_playing": is_playing,
                "thumbnail": thumbnail_data,
                "position": position,
                "duration": duration,
            }

        except Exception as error:
            print(f"[spotify] Could not get media information: {error}")
            return None

    @staticmethod
    def get_info():
        try:
            return asyncio.run(
                SpotifyMediaController._get_info_async()
            )
        except Exception as error:
            print(f"[spotify] Media query failed: {error}")
            return None

    @staticmethod
    async def _command_async(command, position_sec=None):
        session = await SpotifyMediaController._get_spotify_session()

        if session is None:
            return False

        try:
            if command == "play":
                return await session.try_play_async()
            if command == "pause":
                return await session.try_pause_async()
            if command == "toggle":
                return await session.try_toggle_play_pause_async()
            if command == "next":
                return await session.try_skip_next_async()
            if command == "previous":
                return await session.try_skip_previous_async()
            if command == "seek" and position_sec is not None:
                # Windows Media API requires time in 100-nanosecond ticks
                ticks = int(position_sec * 10_000_000)
                return await session.try_change_playback_position_async(ticks)

        except Exception as error:
            print(f"[media] Command '{command}' failed: {error}")

        return False

    @staticmethod
    def command(command, position_sec=None):
        try:
            return asyncio.run(
                SpotifyMediaController._command_async(command, position_sec)
            )
        except Exception as error:
            print(f"[spotify] Command failed: {error}")
            return False

# ---------------- Custom Popup Windows ----------------

POPUP_AUTO_CLOSE_DELAY_MS = 3_000
POPUP_AUTO_CLOSE_POLL_MS = 250


class BasePopup(ctk.CTkToplevel):
    def __init__(self, master, width=240, height=140, x=0, y=0, auto_close=True):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#141414")
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Auto-dismiss once the cursor has been away from the popup for a
        # few seconds, so it doesn't have to be explicitly closed - same
        # idea as the status bar's own edge-triggered auto-hide.
        self._away_since = None
        self._auto_close_job = None
        if auto_close:
            self._auto_close_job = self.after(POPUP_AUTO_CLOSE_POLL_MS, self._tick_auto_close)

    def _tick_auto_close(self):
        try:
            if not self.winfo_exists():
                return
            px, py = win32api.GetCursorPos()
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            x1, y1 = x0 + self.winfo_width(), y0 + self.winfo_height()
            inside = x0 <= px <= x1 and y0 <= py <= y1

            if inside:
                self._away_since = None
            else:
                if self._away_since is None:
                    self._away_since = time.monotonic()
                elif (time.monotonic() - self._away_since) * 1000 >= POPUP_AUTO_CLOSE_DELAY_MS:
                    self.close()
                    return

            self._auto_close_job = self.after(POPUP_AUTO_CLOSE_POLL_MS, self._tick_auto_close)
        except Exception:
            pass

    def close(self):
        if self._auto_close_job is not None:
            try:
                self.after_cancel(self._auto_close_job)
            except Exception:
                pass
            self._auto_close_job = None
        try:
            self.destroy()
        except Exception:
            pass

class SpotifyPopup(BasePopup):
    WIDTH = 290
    HEIGHT = 115

    def __init__(self, master, x: int, y: int, on_leave=None):
        super().__init__(
            master, width=self.WIDTH, height=self.HEIGHT, x=x, y=y, auto_close=False,
        )

        self._on_leave_callback = on_leave
        self._hover_job = None
        self._refresh_job = None
        self._away_since = None
        self._thumbnail_image = None
        self._last_thumbnail = None
        self._loading = False

        self.configure(fg_color="#212121")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=10, pady=10)

        # Album artwork
        self.cover_label = ctk.CTkLabel(
            self.content, text="♪", width=72, height=72,
            fg_color="#242424", text_color="#888888", font=(FONT_FAMILY, 28, "bold"),
        )
        self.cover_label.pack(side="left", padx=(0, 10))

        # Right side info
        self.info_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.info_frame.pack(side="left", fill="both", expand=True)

        self.title_label = ctk.CTkLabel(
            self.info_frame, text="Media", anchor="w",
            font=(FONT_FAMILY, 13, "bold"), text_color="white",
        )
        self.title_label.pack(fill="x", pady=(5, 0))

        self.artist_label = ctk.CTkLabel(
            self.info_frame, text="Not playing", anchor="w",
            font=(FONT_FAMILY, 11), text_color="#999999",
        )
        self.artist_label.pack(fill="x", pady=(0, 0))

        # Playback buttons
  
        self.controls = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        self.controls.pack(fill="x", pady=(0, 0))

        self.previous_btn = ctk.CTkButton(
            self.controls, text="⏮", width=34, height=24,
            fg_color="transparent", hover_color="#292929", text_color="white",
            font=("Segoe UI Symbol", 12), command=lambda: self._send_command("previous"),
        )
        self.previous_btn.pack(side="left", padx=(0, 3))

        self.play_btn = ctk.CTkButton(
            self.controls, text="▶", width=42, height=24,
            fg_color="#2b2b2b", hover_color="#3a3a3a", text_color="white",
            font=("Segoe UI Symbol", 12), command=self._toggle_play,
        )
        self.play_btn.pack(side="left", padx=3)

        self.next_btn = ctk.CTkButton(
            self.controls, text="⏭", width=34, height=24,
            fg_color="transparent", hover_color="#292929", text_color="white",
            font=("Segoe UI Symbol", 12), command=lambda: self._send_command("next"),
        )
        self.next_btn.pack(side="left", padx=(3, 0))

        self._refresh_media()
        self._tick_hover()
        self.focus_set() 
        self.bind("<space>", lambda event: self._toggle_play())

    def _tick_hover(self):
        """Replaces buggy tkinter hover events with a smooth area bounds check."""
        if not self.winfo_exists():
            return
        try:
            px, py = win32api.GetCursorPos()
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            x1, y1 = x0 + self.winfo_width(), y0 + self.winfo_height()

            # Expand the bounding box downwards to cover the gap + taskbar button
            if (x0 - 15) <= px <= (x1 + 15) and (y0 - 15) <= py <= (y1 + 60):
                self._away_since = None
            else:
                if self._away_since is None:
                    self._away_since = time.monotonic()
                elif (time.monotonic() - self._away_since) > 0.35: # 350ms delay
                    self.close()
                    if self._on_leave_callback:
                        self._on_leave_callback()
                    return
        except Exception:
            pass

        self._hover_job = self.after(100, self._tick_hover)

    def _refresh_media(self):
        if not self.winfo_exists():
            return
        if self._loading:
            self._schedule_refresh()
            return
        self._loading = True

        def worker():
            info = SpotifyMediaController.get_info()
            try:
                self.after(0, lambda: self._apply_media_info(info))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _schedule_refresh(self):
        # Assign to a local variable to satisfy strict type checkers
        current_job = self._refresh_job
        if current_job is not None:
            try:
                self.after_cancel(current_job)
            except Exception:
                pass
        self._refresh_job = self.after(1_000, self._refresh_media)

    def _apply_media_info(self, info):
        self._loading = False

        if not info:
            # If Spotify closes or the session dies, kill the popup
            self.close()
            return

        if not info:
            self.title_label.configure(text="Media")
            self.artist_label.configure(text="Not playing")
            self.play_btn.configure(text="▶")
            self.cover_label.configure(image=None, text="♪")
            self._thumbnail_image = None
            self._schedule_refresh()
            return

        is_playing = bool(info.get("is_playing", False))

        self.title_label.configure(text=info.get("title") or "Unknown Song")
        self.artist_label.configure(text=info.get("artist") or "Unknown Artist")
        self.play_btn.configure(text="⏸" if is_playing else "▶")

        thumbnail = info.get("thumbnail")
        if thumbnail and thumbnail != self._last_thumbnail:
            try:
                from io import BytesIO
                from PIL import Image
                image = Image.open(BytesIO(thumbnail)).convert("RGB")
                image.thumbnail((72, 72))
                self._thumbnail_image = ctk.CTkImage(light_image=image, dark_image=image, size=(72, 72))
                self.cover_label.configure(image=self._thumbnail_image, text="")
                self._last_thumbnail = thumbnail
            except Exception as error:
                print(f"[media] Could not display album art: {error}")

        self._schedule_refresh()

    def _send_command(self, command):
        def worker():
            SpotifyMediaController.command(command)
            time.sleep(0.15)
            try:
                self.after(0, self._refresh_media)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_play(self):
        # Instantly flip the button visual for immediate user feedback
        current_icon = self.play_btn.cget("text")
        self.play_btn.configure(text="⏸" if current_icon == "▶" else "▶")

        def worker():
            SpotifyMediaController.command("toggle")
            # Wait a beat for Windows to register the change
            time.sleep(0.15)
            try:
                self.after(0, self._refresh_media)
            except Exception:
                pass
                
        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        # Assign to local variables so the linter knows they are definitely strings
        hover_job = getattr(self, "_hover_job", None)
        if hover_job is not None:
            try:
                self.after_cancel(hover_job)
            except Exception:
                pass
                
        refresh_job = getattr(self, "_refresh_job", None)
        if refresh_job is not None:
            try:
                self.after_cancel(refresh_job)
            except Exception:
                pass
                
        super().close()

class LauncherPopup(BasePopup):
    WIDTH = 620
    HEIGHT = 460

    def __init__(self, master, x: int, y: int):
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, x=x, y=y, auto_close=False)
        self._all_apps = get_all_apps()
        self._query = ctk.StringVar()
        self._selected_index = 0
        self._last_query = ""
        self._debounce_job = None
        
        # Debounce query changes to prevent typing flicker
        self._query.trace_add("write", self._on_query_changed)

        self.search_entry = ctk.CTkEntry(
            self, textvariable=self._query, placeholder_text="Search apps...",
            height=42, fg_color="#1a1a1a", border_color="#3a3a3a",
            text_color="white", font=(FONT_FAMILY, 15),
        )
        self.search_entry.pack(fill="x", padx=18, pady=(18, 10))
        self.search_entry.bind("<Escape>", lambda _event: self.close())

        self.bind("<FocusOut>", lambda _event: self.close())

        # Keyboard navigation bindings
        self.search_entry.bind("<Down>", lambda e: self._change_selection(1))
        self.search_entry.bind("<Up>", lambda e: self._change_selection(-1))
        self.search_entry.bind("<Return>", self._launch_selected)

        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Mouse wheel support over buttons
        canvas = getattr(self.results_frame, "_parent_canvas", None)
        if canvas is not None:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind(sequence, lambda e, c=canvas: c.yview_scroll(int(-1 * (e.delta / 120)), "units"), add="+")

        self._matching_apps = []
        self._render_results()
        self.after(10, self._take_keyboard_focus)

    def _take_keyboard_focus(self):
        """The global hotkey may be pressed over another app; take focus from it."""
        try:
            self.lift()
            win32gui.SetForegroundWindow(self.winfo_id())
            self.focus_force()
            self.search_entry.focus_force()
            self.grab_set()
        except Exception:
            self.search_entry.focus_set()

    def _on_query_changed(self, *args):
        if self._debounce_job is not None:
            self.after_cancel(self._debounce_job)
        self._debounce_job = self.after(150, self._perform_search)

    def _perform_search(self):
        self._debounce_job = None
        # CTkEntry's placeholder-text handling can write to the bound
        # StringVar on focus changes even when the visible text hasn't
        # actually changed (e.g. focus flicker from rebuilding the results
        # list on every arrow-key press). Only reset the selection when the
        # query text genuinely changed, so navigating with Up/Down doesn't
        # get silently snapped back to the top a moment later.
        current_query = self._query.get()
        if current_query != self._last_query:
            self._last_query = current_query
            self._selected_index = 0
        self._render_results()

    def _change_selection(self, delta):
        if not self._matching_apps:
            return "break"
        self._selected_index = max(0, min(self._selected_index + delta, len(self._matching_apps) - 1))
        self._render_results()
        self._scroll_to_selected()
        return "break"

    def _scroll_to_selected(self):
        try:
            canvas = getattr(self.results_frame, "_parent_canvas", None)
            if not canvas or not self._matching_apps:
                return
            # Keep the active selection within the viewable window
            fraction = self._selected_index / len(self._matching_apps)
            canvas.yview_moveto(max(0.0, min(1.0, fraction - 0.15)))
        except Exception:
            pass

    def _render_results(self):
        for child in self.results_frame.winfo_children():
            child.destroy()

        query = self._query.get().strip().casefold()
        
        # --- HARD CAP AT 15 ITEMS ---
        # By slicing the list here, the arrow-key navigation logic 
        # naturally stops at 15 because the 16th item doesn't exist!
        self._matching_apps = [
            app for app in self._all_apps if not query or query in app["name"].casefold()
        ][:15]  
        # ----------------------------
        
        if self._matching_apps:
            self._selected_index = max(0, min(self._selected_index, len(self._matching_apps) - 1))
        else:
            self._selected_index = 0

        for idx, app in enumerate(self._matching_apps):
            is_selected = (idx == self._selected_index)
            ctk.CTkButton(
                self.results_frame, text=app["name"], anchor="w", height=34,
                fg_color="#2b2b2b" if is_selected else "transparent", 
                hover_color="#252525", text_color="white",
                font=(FONT_FAMILY, 13), 
                command=lambda i=idx, item=app: self._on_item_clicked(i, item),
            ).pack(fill="x", pady=1)

        if not self._matching_apps:
            ctk.CTkLabel(
                self.results_frame, text="No matching apps", text_color="gray55",
                font=(FONT_FAMILY, 13),
            ).pack(pady=24)

    def _on_item_clicked(self, idx: int, app: dict):
        # Sync selection index on mouse click
        self._selected_index = idx
        self._launch(app)

    def _launch_selected(self, _event=None):
        if self._matching_apps and 0 <= self._selected_index < len(self._matching_apps):
            self._launch(self._matching_apps[self._selected_index])
        return "break"

    def _launch(self, app: dict):
        try:
            os.startfile(app["target"])
        except OSError as error:
            print(f"[launcher] Could not open {app['name']}: {error}")
        self.close()

    

class VolumePopup(BasePopup):
    def __init__(self, master, x: int, y: int, on_change_callback=None):
        super().__init__(master, width=220, height=100, x=x, y=y)
        self._on_change_callback = on_change_callback

        vol, muted = sysinfo.get_volume()

        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=12, pady=(10, 4))

        self.label = ctk.CTkLabel(
            title_frame, text=f"Volume: {vol}%" if not muted else "Volume: Muted",
            font=(FONT_FAMILY, 12, "bold"), text_color="white"
        )
        self.label.pack(side="left")

        self.mute_btn = ctk.CTkButton(
            title_frame, text="Mute" if not muted else "Unmute", width=60, height=24,
            fg_color="#2b2b2b", hover_color="#3a3a3a", text_color="white",
            font=(FONT_FAMILY, 11), command=self._toggle_mute
        )
        self.mute_btn.pack(side="right")

        self.slider = ctk.CTkSlider(
            self, from_=0, to=100, number_of_steps=100, height=16,
            progress_color="#ebebeb", button_color="white", button_hover_color="#e0e0e0",
            command=self._on_slider_change
        )
        self.slider.set(vol)
        self.slider.pack(fill="x", padx=12, pady=(6, 10))
        self.focus_set()

    def _on_slider_change(self, val):
        percent = int(val)
        sysinfo.set_volume(percent)
        self.label.configure(text=f"Volume: {percent}%")
        self.mute_btn.configure(text="Mute")
        if self._on_change_callback:
            self._on_change_callback()

    def _toggle_mute(self):
        sysinfo.toggle_volume_mute()
        vol, muted = sysinfo.get_volume()
        self.label.configure(text=f"Volume: {vol}%" if not muted else "Volume: Muted")
        self.mute_btn.configure(text="Unmute" if muted else "Mute")
        if self._on_change_callback:
            self._on_change_callback()


class BrightnessPopup(BasePopup):
    def __init__(self, master, x: int, y: int, on_change_callback=None):
        super().__init__(master, width=220, height=100, x=x, y=y)
        self._on_change_callback = on_change_callback
        self._apply_job = None
        brightness = sysinfo.get_brightness()

        self.label = ctk.CTkLabel(
            self,
            text=(f"Brightness: {brightness}%" if brightness is not None else "Brightness unavailable"),
            font=(FONT_FAMILY, 12, "bold"), text_color="white",
        )
        self.label.pack(anchor="w", padx=12, pady=(12, 6))

        if brightness is not None:
            self.slider = ctk.CTkSlider(
                self, from_=0, to=100, number_of_steps=100, height=16,
                progress_color="#ebebeb", button_color="white", button_hover_color="#e0e0e0",
                command=self._on_slider_change,
            )
            self.slider.set(brightness)
            self.slider.pack(fill="x", padx=12, pady=(6, 10))
        self.focus_set()

    def _on_slider_change(self, value):
        percent = int(value)
        # Unlike volume, brightness goes through a PowerShell/WMI request.
        # Keep that expensive work out of the Tk event loop and only submit
        # the final value after the user pauses the drag briefly.
        self.label.configure(text=f"Brightness: {percent}%")
        if self._apply_job is not None:
            self.after_cancel(self._apply_job)
        self._apply_job = self.after(150, lambda: self._apply_brightness(percent))

    def _apply_brightness(self, percent: int):
        self._apply_job = None
        threading.Thread(
            target=sysinfo.set_brightness, args=(percent,), daemon=True,
        ).start()

class CalendarPopup(BasePopup):
    def __init__(self, master, x: int, y: int):
        super().__init__(master, width=250, height=220, x=x, y=y)
        now = datetime.now()

        ctk.CTkLabel(
            self, text=now.strftime("%B %Y"), font=(FONT_FAMILY, 14, "bold"), text_color="white"
        ).pack(pady=(8, 4))

        grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        grid_frame.pack(padx=8, pady=4)

        headers = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, h in enumerate(headers):
            ctk.CTkLabel(
                grid_frame, text=h, font=(FONT_FAMILY, 11, "bold"),
                text_color="gray60", width=30
            ).grid(row=0, column=col, padx=1, pady=1)

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(now.year, now.month)
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    t, tc, bg = "", "gray20", "transparent"
                else:
                    t = str(day)
                    is_today = (day == now.day)
                    tc = "black" if is_today else "white"
                    bg = "#e0e0e0" if is_today else "transparent"

                ctk.CTkLabel(
                    grid_frame, text=t, font=(FONT_FAMILY, 10, "bold"),
                    text_color=tc, fg_color=bg, corner_radius=6, width=30, height=24
                ).grid(row=row, column=col, padx=1, pady=1)

        self.focus_set()


class TrayMenuPopup(BasePopup):
    """Custom stand-in for Windows' native 'show hidden icons' flyout,
    featuring hidden apps and system actions unified in a single scrollable list."""

    WIDTH = 230
    HEIGHT = 210
    ROW_HEIGHT = 30
    MAX_VISIBLE_ROWS = 5

    def __init__(self, master, x: int, y: int, on_quit=None):
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, x=x, y=y)
        self._on_quit = on_quit

        ctk.CTkLabel(
            self, text="System & Hidden Icons", font=(FONT_FAMILY, 12, "bold"), text_color="white"
        ).pack(anchor="w", padx=12, pady=(8, 2))

        # Gather hidden apps
        items = self._get_hidden_apps()

        # Append system actions into the same list so they share the scroll view
        items.append({
            "name": "Task Manager",
            "action": self._open_task_manager,
            "is_action": True,
        })
        items.append({
            "name": "Quit Minimalistic Desktop",
            "action": self._quit,
            "is_action": True,
        })

        list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            width=self.WIDTH - 24,
            height=min(len(items), self.MAX_VISIBLE_ROWS) * self.ROW_HEIGHT,
        )
        list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Mouse wheel bind so scrolling works smoothly over rows
        canvas = getattr(list_frame, "_parent_canvas", None)
        if canvas is not None:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind(sequence, lambda e, c=canvas: c.yview_scroll(int(-1 * (e.delta / 120)), "units"), add="+")

        for item in items:
            self._make_row(list_frame, item)

        self.focus_set()

    @staticmethod
    def _get_hidden_apps() -> list[dict]:
        try:
            all_apps = sysinfo.get_all_notify_icon_apps()
        except Exception:
            return []

        hidden = []
        for app in all_apps:
            if app.get("promoted"):
                continue
            try:
                if not running_apps.is_running(app["exe"]):
                    continue
            except Exception:
                pass
            hidden.append(app)
        return hidden

    def _make_row(self, parent, item: dict):
        if item.get("is_action"):
            # Render system action row (Task Manager, Quit & Restore)
            ctk.CTkButton(
                parent, text=f"  {item['name']}", anchor="w",
                fg_color="transparent", hover_color="#1f1f1f", text_color="white",
                font=(FONT_FAMILY, 11), height=26,
                command=item["action"],
            ).pack(fill="x", pady=1)
        else:
            # Render hidden running app row with executable icon.
            # Note: unlike Windows' own hidden-icons flyout, we can't forward
            # a right-click to open that app's own tray context menu - the
            # registry data sysinfo.get_all_notify_icon_apps() reads only
            # gives us the exe path/name, not the icon's real hwnd/uID needed
            # to send it a WM_RBUTTONUP. Right-click here does the same
            # focus-or-launch as left-click instead of doing nothing.
            img = _extract_icon_image(item["exe"], size=18)
            btn = ctk.CTkButton(
                parent, text=f"  {item['name']}", image=img, anchor="w",
                fg_color="transparent", hover_color="#1f1f1f", text_color="white",
                font=(FONT_FAMILY, 11), height=26,
                command=lambda p=item["exe"]: running_apps.focus_or_launch(p),
            )
            btn.pack(fill="x", pady=1)
            btn.bind(
                "<Button-3>",
                lambda e, p=item["exe"]: running_apps.focus_or_launch(p),
            )

    def _open_task_manager(self):
        self.close()
        try:
            os.startfile("taskmgr.exe")
        except Exception as e:
            print(f"[statusbar] Could not open Task Manager: {e}")

    def _quit(self):
        self.close()
        if self._on_quit:
            self._on_quit()

# ---------------- Status Bar ----------------

class StatusBar(ctk.CTkToplevel):
    def __init__(self, master, auto_hide: bool = True, on_quit=None):
        super().__init__(master)
        self.title("MinimalisticDesktopStatusBar")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#0d0d0d")

        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()

        self._auto_hide = auto_hide
        self._visible = True
        self._hide_job = None
        self._active_popup = None
        self._on_quit = on_quit

        # Spotify hover popup
        self._spotify_popup = None

        # App single/double click
        self._app_click_job = None

        self._show_bar()

        self._pinned_paths = pins.load_pins()
        self._apps_by_path = {a["path"]: a for a in get_all_apps()}
        self._app_widgets: dict[str, tuple[ctk.CTkButton, ctk.CTkFrame]] = {}

        self._build_ui()
        self.after(200, self._pin_topmost)
        self._global_hotkeys = GlobalHotkey({
            VK_S: lambda: self.after(0, self.open_launcher),
            VK_M: lambda: self.after(0, self._on_mic_toggle),
        })
        self._global_hotkeys.start()

        self._tick_clock()
        self._tick_running_indicators()
        self._tick_battery()
        self._tick_wifi()
        self._tick_mic()
        self._tick_volume()
        self._tick_brightness()

        if self._auto_hide:
            self.after(AUTOHIDE_POLL_MS, self._tick_autohide)

    def _build_ui(self):
        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.place(relx=0.01, rely=0.5, anchor="w")

        self.center_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.center_frame.place(relx=0.5, rely=0.5, anchor="center")

        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.place(relx=0.99, rely=0.5, anchor="e")

        self._render_apps()
        self._render_clock()
        self._render_right_widgets()

    def _render_apps(self):
        for w in self.left_frame.winfo_children():
            w.destroy()
        self._app_widgets = {}

        ordered = [p for p in sorted(self._pinned_paths) if p in self._apps_by_path]
        for path in ordered:
            self._make_app_button(self._apps_by_path[path])

    def _make_app_button(self, item: dict):
        
        container = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        container.pack(side="left", padx=3)

        img = _extract_icon_image(item["target"])
        btn = ctk.CTkButton(
            container,
            text="" if img else item["name"][:2].upper(),
            image=img,
            width=BAR_HEIGHT - 10,
            height=BAR_HEIGHT - 16,
            fg_color="transparent",
            hover_color="#1f1f1f",
            text_color="white",
        )
        btn.bind(
            "<Button-1>",
            lambda e, p=item["target"]: self._app_click(e, p)
        )
        if self._is_spotify_app(item):
            btn.bind(
                "<Enter>",
                lambda e, b=btn, p=item["target"]: self._spotify_mouse_enter(e, b, p),
                add="+",
            )
        btn.pack(side="top")

        indicator = ctk.CTkFrame(
            container, fg_color="transparent", height=3,
            width=BAR_HEIGHT - 10, corner_radius=2,
        )
        indicator.pack(side="top", pady=(2, 0))
        indicator.pack_propagate(False)

        self._app_widgets[item["target"]] = (btn, indicator)

    def _app_click(self, event, path):
        """Single click focuses existing app; double click opens another instance."""
        if getattr(self, "_app_click_job", None) is not None:
            if self._app_click_job is not None:
                self.after_cancel(self._app_click_job)
            self._app_click_job = None

            # Double click: open another instance/window
            try:
                os.startfile(path)
            except OSError as error:
                print(f"[statusbar] Could not open another instance: {error}")

            return

        # Delay single-click action briefly so we can detect a double click.
        self._app_click_job = self.after(
            200,
            lambda: self._app_single_click(path)
        )

    def _app_single_click(self, path):
        """Focus the existing app, or launch it if it isn't running."""
        self._app_click_job = None

        if running_apps.is_running(path):
            running_apps.focus_or_launch(path)
        else:
            try:
                os.startfile(path)
            except OSError as error:
                print(f"[statusbar] Could not open app: {error}")

    def _is_spotify_app(self, item: dict) -> bool:
        """Return True when this pinned app is Spotify."""

        name = str(item.get("name", "")).casefold()
        target = str(item.get("target", "")).casefold()

        return (
            "spotify" in name
            or os.path.basename(target) == "spotify.exe"
            or "spotify.exe" in target
        )

    def _spotify_mouse_enter(self, event, trigger_widget, target_path):
        """Show Media popup when hovering over the button."""

        if not running_apps.is_running(target_path):
            return
        
        # Already open — just keep it alive.
        if self._spotify_popup is not None and self._spotify_popup.winfo_exists():
            return

        self._close_active_popup()

        x = (trigger_widget.winfo_rootx() + trigger_widget.winfo_width() // 2 - SpotifyPopup.WIDTH // 2)
        y = self._screen_h - BAR_HEIGHT - SpotifyPopup.HEIGHT - 8
        
        # Keep popup on screen limits.
        x = max(5, min(x, self._screen_w - SpotifyPopup.WIDTH - 5))

        self._spotify_popup = SpotifyPopup(
            self, x=x, y=y, on_leave=self._on_spotify_closed,
        )
        self._active_popup = self._spotify_popup

    def _on_spotify_closed(self):
        """Fired by the popup when it successfully closes itself."""
        if self._active_popup is self._spotify_popup:
            self._active_popup = None
        self._spotify_popup = None

    def _render_clock(self):
        self.clock_label = ctk.CTkLabel(
            self.center_frame, text="", font=(FONT_FAMILY, 14, "bold"),
            text_color="white", cursor="hand2"
        )
        self.clock_label.pack()
        self.clock_label.bind("<Button-1>", self._on_clock_click)

    def _render_right_widgets(self):
        self.menu_label = ctk.CTkLabel(
            self.right_frame, text="\u22ef", font=(FONT_FAMILY, 14, "bold"),
            text_color="white", cursor="hand2"
        )
        self.menu_label.pack(side="left", padx=(4, 10))
        self.menu_label.bind("<Button-1>", self._on_menu_click)

# Removed cursor="hand2" and deleted the bind command
        self.wifi_label = ctk.CTkLabel(
            self.right_frame, text="Wi-Fi", font=(FONT_FAMILY, 12),
            text_color="white"
        )
        self.wifi_label.pack(side="left", padx=8)

        self.volume_label = ctk.CTkLabel(
            self.right_frame, text="Vol", font=(FONT_FAMILY, 12),
            text_color="white", cursor="hand2"
        )
        self.volume_label.pack(side="left", padx=8)
        self.volume_label.bind("<Button-1>", self._on_volume_click)

        self.brightness_label = ctk.CTkLabel(
            self.right_frame, text="Bri", font=(FONT_FAMILY, 12),
            text_color="white", cursor="hand2"
        )
        self.brightness_label.pack(side="left", padx=8)
        self.brightness_label.bind("<Button-1>", self._on_brightness_click)

        self.mic_label = ctk.CTkLabel(
            self.right_frame, text="Mic On", font=(FONT_FAMILY, 12),
            text_color="white", cursor="hand2"
        )
        self.mic_label.pack(side="left", padx=8)
        self.mic_label.bind("<Button-1>", lambda e: self._on_mic_toggle())

        self.battery_label = ctk.CTkLabel(
            self.right_frame, text="", font=(FONT_FAMILY, 12), text_color="white"
        )
        self.battery_label.pack(side="left", padx=(8, 4))

    # ---------- Refresh Loops ----------

    def _tick_clock(self):
        self.clock_label.configure(text=datetime.now().strftime("%a %d %b   %H:%M:%S"))
        self.after(CLOCK_REFRESH_MS, self._tick_clock)

    def _tick_running_indicators(self):
        for target, (btn, indicator) in self._app_widgets.items():
            running = running_apps.is_running(target)
            indicator.configure(fg_color=RUNNING_COLOR if running else "transparent")
        self.after(RUNNING_REFRESH_MS, self._tick_running_indicators)

    def _tick_battery(self):
        try:
            percent, charging = sysinfo.get_battery()
        except Exception:
            percent, charging = None, False
        self.battery_label.configure(text="" if percent is None else f"{'⚡' if charging else ''}{percent}%")
        self.after(BATTERY_REFRESH_MS, self._tick_battery)

    def _tick_wifi(self):
        self._update_wifi_label()
        self.after(WIFI_REFRESH_MS, self._tick_wifi)

    def _tick_mic(self):
        self._update_mic_label()
        self.after(2_000, self._tick_mic)

    def _tick_volume(self):
        self._update_volume_label()
        self.after(VOLUME_REFRESH_MS, self._tick_volume)

    def _tick_brightness(self):
        self._update_brightness_label()
        self.after(BRIGHTNESS_REFRESH_MS, self._tick_brightness)

    def _update_wifi_label(self):
        try:
            connected, ssid = sysinfo.get_wifi_status()
        except Exception:
            connected, ssid = False, None

        if connected:
            self.wifi_label.configure(
                text=ssid or "Wi-Fi",
                text_color="white"
            )
        else:
            self.wifi_label.configure(
                text="No Wi-Fi",
                text_color="#787878"  # Matches the muted gray style used by the mic
            )

    def _update_mic_label(self):
        try:
            muted = sysinfo.is_mic_muted()
            self.mic_label.configure(
                text="Mic Muted" if muted else "Mic On",
                text_color="#787878" if muted else "white"
            )
        except Exception:
            self.mic_label.configure(text="No Mic", text_color="gray50")

    def _update_volume_label(self):
        try:
            percent, muted = sysinfo.get_volume()
            if muted:
                text = "Vol Muted"
                color = "#787878"
            else:
                text = f"Vol {percent}%"
                color = "white"
            self.volume_label.configure(text=text, text_color=color)
        except Exception:
            self.volume_label.configure(text="Vol", text_color="white")

    def _update_brightness_label(self):
        brightness = sysinfo.get_brightness()
        if brightness is None:
            self.brightness_label.configure(text="Bri —", text_color="#787878")
        else:
            self.brightness_label.configure(text=f"Bri {brightness}%", text_color="white")

    def _on_mic_toggle(self, event=None):
        sysinfo.toggle_mic_mute()
        self._update_mic_label()

        try:
            muted = sysinfo.is_mic_muted()
            text = "Mic Muted" if muted else "Mic Active"
            color = "#fcccb4" if muted else "#befec0"  # Red for muted, green for active
            self._show_toast(text, color)
        except Exception:
            pass

    def _show_toast(self, text, color):
        """Displays a temporary, rounded popup notification on the bottom right."""
        if getattr(self, "_active_toast", None) and self._active_toast.winfo_exists():
            self._active_toast.destroy()

        width = 160
        height = 42
        x = self._screen_w - width - 20
        y = self._screen_h - BAR_HEIGHT - height - 15

        self._active_toast = ctk.CTkToplevel(self)
        self._active_toast.overrideredirect(True)
        self._active_toast.attributes("-topmost", True)
        
        # 1. Turn the actual window invisible using a "chroma key" color
        self._active_toast.configure(fg_color="#000001")
        self._active_toast.attributes("-transparentcolor", "#000001")
        self._active_toast.geometry(f"{width}x{height}+{x}+{y}")

        # 2. Pack a rounded frame inside the invisible window
        bg_frame = ctk.CTkFrame(self._active_toast, fg_color="#1a1a1a", corner_radius=12)
        bg_frame.pack(fill="both", expand=True)

        # Draw a sleek colored indicator line (padded slightly so it fits inside the curve)
        indicator = ctk.CTkFrame(bg_frame, width=4, fg_color=color, corner_radius=4)
        indicator.pack(side="left", fill="y", pady=6, padx=(6, 0))

        # Add the notification text
        ctk.CTkLabel(
            bg_frame, text=text, font=(FONT_FAMILY, 12, "bold"), text_color="white"
        ).pack(side="left", padx=10)

        self._active_toast.after(2500, self._active_toast.destroy)

    # ---------- Custom Popup Actions ----------

    def _close_active_popup(self):
        if self._active_popup is not None:
            self._active_popup.close()
            self._active_popup = None

    def _toggle_popup(self, popup_cls, trigger_widget, y_offset: int, x_offset: int = -80, **kwargs):
        """Opens popup_cls anchored above trigger_widget - or, if that same
        popup is already open, closes it instead. This is what makes a
        second click on a button (e.g. Volume) dismiss its popup rather
        than closing it and immediately reopening a fresh one."""
        already_open = (
            self._active_popup is not None
            and isinstance(self._active_popup, popup_cls)
            and self._active_popup.winfo_exists()
        )
        self._close_active_popup()
        if already_open:
            return

        x = trigger_widget.winfo_rootx() + x_offset
        y = self._screen_h - BAR_HEIGHT - y_offset
        self._active_popup = popup_cls(self, x=x, y=y, **kwargs)

    def _on_volume_click(self, event=None):
        self._toggle_popup(
            VolumePopup, self.volume_label, y_offset=110,
            on_change_callback=self._update_volume_label,
        )

    def _on_brightness_click(self, event=None):
        self._toggle_popup(
            BrightnessPopup, self.brightness_label, y_offset=110,
            on_change_callback=self._update_brightness_label,
        )

    def _on_clock_click(self, event=None):
        self._toggle_popup(CalendarPopup, self.clock_label, y_offset=230)

    def _on_menu_click(self, event=None):
        self._toggle_popup(
            TrayMenuPopup, self.menu_label,
            y_offset=TrayMenuPopup.HEIGHT + 10, x_offset=-10,
            on_quit=self._on_quit,
        )

    def open_tray_menu(self):
        """Called by the Windows notification-area icon when it's clicked.
        Rather than spawning a separate window elsewhere on screen, this
        just brings the status bar into view (in case it's auto-hidden)
        and opens the exact same on-bar menu popup you'd get from clicking
        the Menu button directly."""
        if self._hide_job is not None:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        if not self._visible:
            self._show_bar()
        self._on_menu_click()

    def open_launcher(self):
        """Opens the centered app launcher invoked by the global Ctrl+S hotkey."""
        if self._hide_job is not None:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        if not self._visible:
            self._show_bar()

        already_open = (
            self._active_popup is not None
            and isinstance(self._active_popup, LauncherPopup)
            and self._active_popup.winfo_exists()
        )
        self._close_active_popup()
        if already_open:
            return

        x = (self._screen_w - LauncherPopup.WIDTH) // 2
        y = (self._screen_h - LauncherPopup.HEIGHT) // 2
        self._active_popup = LauncherPopup(self, x=x, y=y)

    def destroy(self):
        if hasattr(self, "_launcher_hotkey"):
            self._global_hotkeys.stop()
        super().destroy()

    # ---------- Auto-Hide Behavior ----------

    def _show_bar(self):
        self.geometry(f"{self._screen_w}x{BAR_HEIGHT}+0+{self._screen_h - BAR_HEIGHT}")
        self._visible = True
        self._pin_topmost()

    def _hide_bar(self):
        self.geometry(f"{self._screen_w}x{BAR_HEIGHT}+0+{self._screen_h - 1}")
        self._visible = False
        self._hide_job = None
        self._close_active_popup()
        self._pin_topmost()

    def _tick_autohide(self):
        try:
            try:
                _cursor_x, cursor_y = win32api.GetCursorPos()
            except Exception:
                cursor_y = self._screen_h

            bar_top = self._screen_h - BAR_HEIGHT
            cursor_over_bar = self._visible and cursor_y >= bar_top
            near_bottom_edge = cursor_y >= self._screen_h - EDGE_TRIGGER_PX

            popup_active = self._active_popup is not None and self._active_popup.winfo_exists()

            if cursor_over_bar or near_bottom_edge or popup_active:
                if self._hide_job is not None:
                    self.after_cancel(self._hide_job)
                    self._hide_job = None
                if not self._visible:
                    self._show_bar()
            elif self._visible and self._hide_job is None:
                self._hide_job = self.after(HIDE_DELAY_MS, self._hide_bar)

            if self._visible:
                self._pin_topmost()
        finally:
            self.after(AUTOHIDE_POLL_MS, self._tick_autohide)

    # ---------- Misc ----------

    def _pin_topmost(self):
        try:
            hwnd = self.winfo_id()
            win32gui.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0,  # -1 is HWND_TOPMOST
                0x0002 | 0x0001 | 0x0010,  # SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
        except Exception:
            pass

    def refresh_pins(self):
        self._pinned_paths = pins.load_pins()
        self._render_apps()