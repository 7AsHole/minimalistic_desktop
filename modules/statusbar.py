import calendar
import ctypes
import asyncio
import os
import threading
import time
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
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
    def __init__(self, bindings: dict):
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
            ico_x = win32api.GetSystemMetrics(0)
            ico_y = win32api.GetSystemMetrics(1)

            hDC = win32gui.GetDC(0)
            hdc = win32ui.CreateDCFromHandle(hDC)
            
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
            
            hdc_mem.DeleteDC()
            win32gui.DeleteObject(hbmp.GetHandle())
            hdc.DeleteDC()
            win32gui.ReleaseDC(0, hDC)

        for h in handles:
            win32gui.DestroyIcon(h)
    except Exception as e:
        print(f"[statusbar] Icon extraction error for {path}: {e}")
        img = None

    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size)) if img else None
    _icon_cache[path] = ctk_img
    return ctk_img


class SpotifyMediaController:
    _loop: "asyncio.AbstractEventLoop | None" = None
    _thread: "threading.Thread | None" = None
    _manager = None
    _cache_lock = threading.Lock()
    _cached_info = None
    _last_track_key = None
    _last_thumbnail_bytes = None
    POLL_INTERVAL_SEC = 1.2


    @classmethod
    def _ensure_running(cls):
        if cls._thread is not None:
            return
        cls._loop = asyncio.new_event_loop()
        cls._thread = threading.Thread(target=cls._run_loop, daemon=True)
        cls._thread.start()

    @classmethod
    def _run_loop(cls):
        loop = asyncio.new_event_loop()
        cls._loop = loop
        asyncio.set_event_loop(loop)
        loop.create_task(cls._poll_forever())
        loop.run_forever()

    @classmethod
    async def _poll_forever(cls):
        while True:
            try:
                info = await cls._get_info_async()
                with cls._cache_lock:
                    cls._cached_info = info
            except Exception as error:
                print(f"[spotify] Poll failed: {error}")
            await asyncio.sleep(cls.POLL_INTERVAL_SEC)


    @staticmethod
    def _is_spotify_session(session) -> bool:
        try:
            app_id = (session.source_app_user_model_id or "").casefold()
            return "spotify" in app_id
        except Exception:
            return False

    @classmethod
    async def _get_manager(cls):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
        if cls._manager is None:
            cls._manager = await MediaManager.request_async()
        return cls._manager

    @classmethod
    async def _get_spotify_session(cls):
        manager = await cls._get_manager()
        sessions = manager.get_sessions()

        for session in sessions:
            if cls._is_spotify_session(session):
                return session

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

            byte_buffer = bytearray(size)

            reader.read_bytes(byte_buffer)

            return bytes(byte_buffer)

        except Exception as error:
            print(f"[media] Could not read album art: {error}")
            return None

    @classmethod
    async def _get_info_async(cls):
        session = await cls._get_spotify_session()

        if session is None:
            cls._last_track_key = None
            return None

        try:
            properties = await session.try_get_media_properties_async()
            playback = session.get_playback_info()

            playback_status = playback.playback_status
            is_playing = int(playback_status) == 4

            timeline = session.get_timeline_properties()
            position = 0
            duration = 0

            if timeline:
                try:
                    from datetime import datetime, timezone
                    pos_sec = timeline.position.total_seconds()
                    duration = timeline.end_time.total_seconds()

                    if is_playing:
                        now = datetime.now(timezone.utc)
                        elapsed = (now - timeline.last_updated_time).total_seconds()
                        position = pos_sec + elapsed
                    else:
                        position = pos_sec
                except Exception:
                    pass

            if properties is None:
                cls._last_track_key = None
                return None

            title = properties.title or "Unknown Song"
            artist = properties.artist or "Unknown Artist"

            track_key = (title, artist)
            if track_key == cls._last_track_key:
                thumbnail_data = cls._last_thumbnail_bytes
            else:
                thumbnail_data = None
                if properties.thumbnail is not None:
                    thumbnail_data = await cls._read_thumbnail(properties.thumbnail)
                cls._last_track_key = track_key
                cls._last_thumbnail_bytes = thumbnail_data

            return {
                "title": title,
                "artist": artist,
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


    @classmethod
    def get_info(cls):
        cls._ensure_running()
        with cls._cache_lock:
            return cls._cached_info

    @classmethod
    def refresh_now(cls):
        cls._ensure_running()
        try:
            if cls._loop is None:
                raise RuntimeError("Event loop is not running")
            future = asyncio.run_coroutine_threadsafe(cls._get_info_async(), cls._loop)
            info = future.result(timeout=5)
            with cls._cache_lock:
                cls._cached_info = info
            return info
        except Exception as error:
            print(f"[spotify] Refresh failed: {error}")
            return cls.get_info()

    @classmethod
    async def _command_async(cls, command, position_sec=None):
        session = await cls._get_spotify_session()

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
                ticks = int(position_sec * 10_000_000)
                return await session.try_change_playback_position_async(ticks)

        except Exception as error:
            print(f"[media] Command '{command}' failed: {error}")

        return False

    @classmethod
    def command(cls, command, position_sec=None):
        cls._ensure_running()
        try:
            if cls._loop is None:
                raise RuntimeError("Event loop is not running")
            future = asyncio.run_coroutine_threadsafe(
                cls._command_async(command, position_sec), cls._loop
            )
            return future.result(timeout=5)
        except Exception as error:
            print(f"[spotify] Command failed: {error}")
            return False


POPUP_AUTO_CLOSE_DELAY_MS = 3_000
POPUP_AUTO_CLOSE_POLL_MS = 250


class BasePopup(ctk.CTkToplevel):
    def __init__(self, master, width=240, height=140, x=0, y=0, auto_close=True):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#141414")
        self.geometry(f"{width}x{height}+{x}+{y}")

        self._away_since = None
        self._auto_close_job = None
        self._auto_close_enabled = auto_close
        self._closed = False
        if auto_close:
            self._auto_close_job = self.after(POPUP_AUTO_CLOSE_POLL_MS, self._tick_auto_close)

    def show(self, x: int, y: int):
        self._closed = False
        self._away_since = None
        self._anchor_x = x
        self._anchor_y = y
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()
        if self._auto_close_enabled and self._auto_close_job is None:
            self._auto_close_job = self.after(POPUP_AUTO_CLOSE_POLL_MS, self._tick_auto_close)
        self.refresh_content()

    def refresh_content(self):
        pass

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
        if self._closed:
            return
        self._closed = True
        if self._auto_close_job is not None:
            try:
                self.after_cancel(self._auto_close_job)
            except Exception:
                pass
            self._auto_close_job = None
        try:
            self.withdraw()
        except Exception:
            pass

class SpotifyPopup(BasePopup):
    WIDTH = 315
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

        self._optimistic_playing = None
        self._optimistic_until = 0.0

        self.bind("<space>", lambda e: self._popup_media_cmd("toggle"))
        self.bind("<period>", lambda e: self._popup_media_cmd("next"))
        self.bind("<comma>", lambda e: self._popup_media_cmd("previous"))

        self.attributes("-topmost", True)
        self.bind("<Enter>", lambda e: self.focus_force(), add="+")

        self.configure(fg_color="#212121")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=10, pady=10)

        self.cover_label = ctk.CTkLabel(
            self.content, text="♪", width=72, height=72,
            fg_color="#242424", text_color="#888888", font=(FONT_FAMILY, 28, "bold"),
        )
        self.cover_label.pack(side="left", padx=(0, 10))

        self.vol_slider = ctk.CTkSlider(
            self.content, from_=0, to=1, orientation="vertical",
            height=72, width=12, progress_color="white",
            fg_color="#333333", button_color="white", button_hover_color="#e0e0e0",
            command=self._set_spotify_volume
        )
        self.vol_slider.set(self._get_spotify_volume())
        self.vol_slider.pack(side="right", fill="y", padx=(5, 0))

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

    def refresh_content(self):
        self._refresh_media()
        self._tick_hover()

    def _popup_media_cmd(self, command):
        if command == "toggle" and hasattr(self, "play_btn"):
            self._set_optimistic_playing(self.play_btn.cget("text") != "⏸")

        threading.Thread(
            target=lambda: SpotifyMediaController.command(command), daemon=True
        ).start()

    def _tick_hover(self):
        if not self.winfo_exists():
            return
        try:
            px, py = win32api.GetCursorPos()
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            x1, y1 = x0 + self.winfo_width(), y0 + self.winfo_height()

            if (x0 - 15) <= px <= (x1 + 15) and (y0 - 15) <= py <= (y1 + 60):
                self._away_since = None
            else:
                if self._away_since is None:
                    self._away_since = time.monotonic()
                elif (time.monotonic() - self._away_since) > 0.35:
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
        self._apply_media_info(SpotifyMediaController.get_info())

    def _schedule_refresh(self):
        current_job = self._refresh_job
        if current_job is not None:
            try:
                self.after_cancel(current_job)
            except Exception:
                pass
        self._refresh_job = self.after(1_000, self._refresh_media)

    def _set_optimistic_playing(self, playing: bool):
        self.play_btn.configure(text="⏸" if playing else "▶")
        self._optimistic_playing = playing
        self._optimistic_until = time.monotonic() + 2.0

    def _apply_media_info(self, info):
        self._loading = False

        if not info:
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
        if self._optimistic_playing is not None:
            if time.monotonic() < self._optimistic_until:
                is_playing = self._optimistic_playing
            else:
                self._optimistic_playing = None

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
        threading.Thread(
            target=lambda: SpotifyMediaController.command(command), daemon=True
        ).start()

    def _toggle_play(self):
        self._set_optimistic_playing(self.play_btn.cget("text") != "⏸")
        threading.Thread(
            target=lambda: SpotifyMediaController.command("toggle"), daemon=True
        ).start()

    def _get_spotify_volume(self):
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        for session in AudioUtilities.GetAllSessions():
            if session.Process and session.Process.name().lower() == "spotify.exe":
                return session._ctl.QueryInterface(ISimpleAudioVolume).GetMasterVolume()
        return 1.0

    def _set_spotify_volume(self, val):
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        for session in AudioUtilities.GetAllSessions():
            if session.Process and session.Process.name().lower() == "spotify.exe":
                session._ctl.QueryInterface(ISimpleAudioVolume).SetMasterVolume(val, None)

    def close(self):
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

    def __init__(self, master, x: int, y: int, on_close=None):
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, x=x, y=y, auto_close=False)
        self._all_apps = get_all_apps()
        self._query = ctk.StringVar()
        self._selected_index = 0
        self._last_query = ""
        self._debounce_job = None
        self._on_close_callback = on_close
        
        self._query.trace_add("write", self._on_query_changed)

        self.search_entry = ctk.CTkEntry(
            self, textvariable=self._query, placeholder_text="Search apps...",
            height=42, fg_color="#1a1a1a", border_color="#3a3a3a",
            text_color="white", font=(FONT_FAMILY, 15),
        )
        self.search_entry.pack(fill="x", padx=18, pady=(18, 10))
        self.search_entry.bind("<Escape>", lambda _event: self.close())

        self.bind("<FocusOut>", lambda _event: self.close())

        self.search_entry.bind("<Down>", lambda e: self._change_selection(1))
        self.search_entry.bind("<Up>", lambda e: self._change_selection(-1))
        self.search_entry.bind("<Return>", self._launch_selected)

        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        canvas = getattr(self.results_frame, "_parent_canvas", None)
        if canvas is not None:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind(sequence, lambda e, c=canvas: c.yview_scroll(int(-1 * (e.delta / 120)), "units"), add="+")

        self._matching_apps = []
        self._render_results()
        self.after(10, self._take_keyboard_focus)

    def _take_keyboard_focus(self):
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
            fraction = self._selected_index / len(self._matching_apps)
            canvas.yview_moveto(max(0.0, min(1.0, fraction - 0.15)))
        except Exception:
            pass

    def _render_results(self):
        for child in self.results_frame.winfo_children():
            child.destroy()

        query = self._query.get().strip().casefold()
        
        self._matching_apps = [
            app for app in self._all_apps if not query or query in app["name"].casefold()
        ][:15]  
        
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

    def close(self):
        already_closed = self._closed
        super().close()
        if not already_closed and self._on_close_callback:
            try:
                self._on_close_callback()
            except Exception:
                pass

    

class VolumePopup(BasePopup):
    BASE_HEIGHT = 100
    ROW_HEIGHT = 35

    def __init__(self, master, x: int, y: int, on_change_callback=None):
        sessions = [s for s in AudioUtilities.GetAllSessions() if s.Process]
        height, adjusted_y = self._layout_for_sessions(sessions, y)

        super().__init__(master, width=220, height=height, x=x, y=adjusted_y)
        self._on_change_callback = on_change_callback
        self._anchor_x = x
        self._anchor_y = y

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

        self.mixer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.mixer_frame.pack(fill="x")
        self._build_volume_mixer(sessions)

        self.focus_set()

    @classmethod
    def _layout_for_sessions(cls, sessions, y):
        added_height = 20 + (cls.ROW_HEIGHT * len(sessions)) if sessions else 0
        return cls.BASE_HEIGHT + added_height, y - added_height

    def refresh_content(self):
        vol, muted = sysinfo.get_volume()
        self.label.configure(text=f"Volume: {vol}%" if not muted else "Volume: Muted")
        self.mute_btn.configure(text="Unmute" if muted else "Mute")
        self.slider.set(vol)

        for child in self.mixer_frame.winfo_children():
            child.destroy()
        sessions = [s for s in AudioUtilities.GetAllSessions() if s.Process]
        self._build_volume_mixer(sessions)

        height, adjusted_y = self._layout_for_sessions(sessions, self._anchor_y)
        self.geometry(f"220x{height}+{self._anchor_x}+{adjusted_y}")

    def _build_volume_mixer(self, valid_sessions):
        if not valid_sessions:
            return

        divider = ctk.CTkFrame(self.mixer_frame, height=2, fg_color="#333333")
        divider.pack(fill="x", pady=10, padx=15)

        for session in valid_sessions:
            app_name = session.Process.name()
            display_name = app_name.replace(".exe", "").capitalize()

            volume_interface = session._ctl.QueryInterface(ISimpleAudioVolume)
            current_vol = volume_interface.GetMasterVolume()

            row_frame = ctk.CTkFrame(self.mixer_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=5, padx=15)

            ctk.CTkLabel(
                row_frame, text=display_name, width=70, 
                anchor="w", font=("Bahnschrift", 11)
            ).pack(side="left")

            app_slider = ctk.CTkSlider(
                row_frame, from_=0, to=1, height=12,
                progress_color="#ebebeb", 
                fg_color="#333333", button_color="white", button_hover_color="#e0e0e0"
            )
            app_slider.set(current_vol)
            app_slider.pack(side="left", fill="x", expand=True, padx=(10, 0))
            
            app_slider.configure(
                command=lambda val, vol_int=volume_interface: vol_int.SetMasterVolume(val, None)
            )

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

        items = self._get_hidden_apps()

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
        snapshot = running_apps.get_running_snapshot()
        for app in all_apps:
            if app.get("promoted"):
                continue
            try:
                if not running_apps.is_running(app["exe"], snapshot):
                    continue
            except Exception:
                pass
            hidden.append(app)
        return hidden

    def _make_row(self, parent, item: dict):
        if item.get("is_action"):
            ctk.CTkButton(
                parent, text=f"  {item['name']}", anchor="w",
                fg_color="transparent", hover_color="#1f1f1f", text_color="white",
                font=(FONT_FAMILY, 11), height=26,
                command=item["action"],
            ).pack(fill="x", pady=1)
        else:
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
        self._popup_instances = {}
        self._on_quit = on_quit

        self._spotify_popup = None

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
        if getattr(self, "_app_click_job", None) is not None:
            if self._app_click_job is not None:
                self.after_cancel(self._app_click_job)
            self._app_click_job = None

            try:
                os.startfile(path)
            except OSError as error:
                print(f"[statusbar] Could not open another instance: {error}")

            return

        self._app_click_job = self.after(
            200,
            lambda: self._app_single_click(path)
        )

    def _app_single_click(self, path):
        self._app_click_job = None

        if running_apps.is_running(path):
            running_apps.focus_or_launch(path)
        else:
            try:
                os.startfile(path)
            except OSError as error:
                print(f"[statusbar] Could not open app: {error}")

    def _is_spotify_app(self, item: dict) -> bool:
        name = str(item.get("name", "")).casefold()
        target = str(item.get("target", "")).casefold()

        return (
            "spotify" in name
            or os.path.basename(target) == "spotify.exe"
            or "spotify.exe" in target
        )

    def _spotify_mouse_enter(self, event, trigger_widget, target_path):
        if not running_apps.is_running(target_path):
            return

        if (
            self._spotify_popup is not None
            and self._spotify_popup.winfo_exists()
            and self._spotify_popup.winfo_ismapped()
        ):
            return

        self._close_active_popup()

        x = (trigger_widget.winfo_rootx() + trigger_widget.winfo_width() // 2 - SpotifyPopup.WIDTH // 2)
        y = self._screen_h - BAR_HEIGHT - SpotifyPopup.HEIGHT - 8
        
        x = max(5, min(x, self._screen_w - SpotifyPopup.WIDTH - 5))

        if self._spotify_popup is not None and self._spotify_popup.winfo_exists():
            self._spotify_popup.show(x, y)
        else:
            self._spotify_popup = SpotifyPopup(
                self, x=x, y=y, on_leave=self._on_spotify_closed,
            )

        self._active_popup = self._spotify_popup
        self._spotify_popup.focus_force()

    def _on_spotify_closed(self):
        if self._active_popup is self._spotify_popup:
            self._active_popup = None

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


    def _tick_clock(self):
        self.clock_label.configure(text=datetime.now().strftime("%a %d %b   %H:%M:%S"))
        self.after(CLOCK_REFRESH_MS, self._tick_clock)

    def _tick_running_indicators(self):
        snapshot = running_apps.get_running_snapshot()
        for target, (btn, indicator) in self._app_widgets.items():
            running = running_apps.is_running(target, snapshot)
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
        def worker():
            try:
                connected, ssid = sysinfo.get_wifi_status()
            except Exception:
                connected, ssid = False, None
            if self.winfo_exists():
                self.after(0, lambda: self._apply_wifi_label(connected, ssid))
        threading.Thread(target=worker, daemon=True).start()
        self.after(WIFI_REFRESH_MS, self._tick_wifi)

    def _tick_mic(self):
        self._update_mic_label()
        self.after(2_000, self._tick_mic)

    def _tick_volume(self):
        self._update_volume_label()
        self.after(VOLUME_REFRESH_MS, self._tick_volume)

    def _tick_brightness(self):
        def worker():
            brightness = sysinfo.get_brightness()
            if self.winfo_exists():
                self.after(0, lambda: self._apply_brightness_label(brightness))
        threading.Thread(target=worker, daemon=True).start()
        self.after(BRIGHTNESS_REFRESH_MS, self._tick_brightness)

    def _update_wifi_label(self):
        try:
            connected, ssid = sysinfo.get_wifi_status()
        except Exception:
            connected, ssid = False, None
        self._apply_wifi_label(connected, ssid)

    def _apply_wifi_label(self, connected: bool, ssid):
        if connected:
            self.wifi_label.configure(
                text=ssid or "Wi-Fi",
                text_color="white"
            )
        else:
            self.wifi_label.configure(
                text="No Wi-Fi",
                text_color="#787878"
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
        self._apply_brightness_label(brightness)

    def _apply_brightness_label(self, brightness):
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
            color = "#fcccb4" if muted else "#befec0"
            self._show_toast(text, color)
        except Exception:
            pass

    def _show_toast(self, text, color):
        if getattr(self, "_active_toast", None) is None or not self._active_toast.winfo_exists():
            width = 160
            height = 42
            x = self._screen_w - width - 20
            y = self._screen_h - BAR_HEIGHT - height - 15

            self._active_toast = ctk.CTkToplevel(self)
            self._active_toast.overrideredirect(True)
            self._active_toast.attributes("-topmost", True)
            
            self._active_toast.configure(fg_color="#000001")
            self._active_toast.attributes("-transparentcolor", "#000001")
            self._active_toast.geometry(f"{width}x{height}+{x}+{y}")

            bg_frame = ctk.CTkFrame(self._active_toast, fg_color="#1a1a1a", corner_radius=12)
            bg_frame.pack(fill="both", expand=True)

            self._toast_indicator = ctk.CTkFrame(bg_frame, width=4, corner_radius=4)
            self._toast_indicator.pack(side="left", fill="y", pady=6, padx=(6, 0))

            self._toast_label = ctk.CTkLabel(
                bg_frame, font=(FONT_FAMILY, 12, "bold"), text_color="white"
            )
            self._toast_label.pack(side="left", padx=10)
            
            self._toast_hide_job = None
            self._active_toast.withdraw()

        toast_hide_job = getattr(self, "_toast_hide_job", None)
        if toast_hide_job is not None:
            self.after_cancel(toast_hide_job)
            self._toast_hide_job = None

        self._toast_indicator.configure(fg_color=color)
        self._toast_label.configure(text=text)

        self._active_toast.deiconify()
        self._active_toast.lift()
        self._toast_hide_job = self.after(2500, self._active_toast.withdraw)


    def _close_active_popup(self):
        popup = self._active_popup
        if popup is not None:
            self._active_popup = None
            popup.close()

    def _toggle_popup(self, popup_cls, trigger_widget, y_offset: int, x_offset: int = -80, **kwargs):
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

        popup = self._popup_instances.get(popup_cls)
        if popup is None or not popup.winfo_exists():
            popup = popup_cls(self, x=x, y=y, **kwargs)
            self._popup_instances[popup_cls] = popup
        else:
            popup.show(x, y)

        self._active_popup = popup

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
        if self._hide_job is not None:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        if not self._visible:
            self._show_bar()
        self._on_menu_click()

    def open_launcher(self):
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
        self._active_popup = LauncherPopup(self, x=x, y=y, on_close=self._maybe_hide_immediately)

    def destroy(self):
        if hasattr(self, "_launcher_hotkey"):
            self._global_hotkeys.stop()
        super().destroy()


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

    def _maybe_hide_immediately(self):
        if not self._visible:
            return
        if self._hide_job is not None:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        try:
            _cursor_x, cursor_y = win32api.GetCursorPos()
        except Exception:
            cursor_y = self._screen_h

        bar_top = self._screen_h - BAR_HEIGHT
        cursor_over_bar = cursor_y >= bar_top
        near_bottom_edge = cursor_y >= self._screen_h - EDGE_TRIGGER_PX
        if not (cursor_over_bar or near_bottom_edge):
            self._hide_bar()

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


    def _pin_topmost(self):
        try:
            hwnd = self.winfo_id()
            win32gui.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0,
                0x0002 | 0x0001 | 0x0010,
            )
        except Exception:
            pass

    def refresh_pins(self):
        self._pinned_paths = pins.load_pins()
        self._render_apps()  