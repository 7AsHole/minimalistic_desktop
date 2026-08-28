import calendar
import os
import concurrent.futures
import win32con
import win32gui
import threading
import time
from datetime import datetime

import customtkinter as ctk
from io import BytesIO
from PIL import Image
from .statusbar import SpotifyMediaController
from . import pins
from .shortcuts import get_all_apps

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Bahnschrift"  

SCROLL_RESET_MS = 5_000
QUICK_FILTER_CLEAR_MS = 5_000
class DesktopOverlay(ctk.CTk):
    def __init__(self, on_quit=None, on_pins_changed=None):
        super().__init__()
        self.title("MinimalisticDesktop")
        self.overrideredirect(True)
        self.configure(fg_color="black")
        self._on_quit = on_quit
        self._on_pins_changed = on_pins_changed

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")

        self._pinned = pins.load_pins()
        self._quick_filter = ""
        self._quick_filter_job = None
        self._scroll_reset_job = None

        self._build_ui()
        self.after(200, self._pin_to_desktop)
        self._bind_controls()
        self.media_player = OverlayMediaPlayer(self, width=280)
        self.media_player.place(relx=0.98, rely=0.15, anchor="ne")
        self._tick()

        self.bind("<Enter>", self._delayed_focus, add="+")

    def _delayed_focus(self, e=None):
        self.after(500, self.focus_set)

    def _launch_app(self, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Failed to open {path}: {e}")

    def _bind_controls(self):
        self.bind("<Key>", self._on_quick_filter_key)
        
        self.bind("<space>", lambda e: self._overlay_media_cmd("toggle"))
        self.bind("<period>", lambda e: self._overlay_media_cmd("next"))
        self.bind("<comma>", lambda e: self._overlay_media_cmd("previous"))

    def _overlay_media_cmd(self, command):
        if command == "toggle" and hasattr(self, "media_player"):
            self.media_player._cmd("toggle")
            return

        threading.Thread(
            target=lambda: SpotifyMediaController.command(command), 
            daemon=True
        ).start()
    def request_quit(self):
        if self._on_quit:
            self._on_quit()
        self.destroy()



    def _build_ui(self):
        self.clock_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 88, "bold"), text_color="white"
        )
        self.clock_label.place(relx=0.5, rely=0.3, anchor="center")

        self.date_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 18), text_color="gray70"
        )
        self.date_label.place(relx=0.5, rely=0.38, anchor="center")

        self.calendar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.calendar_frame.place(relx=0.5, rely=0.44, anchor="n")
        self._render_calendar()

        self.shortcuts_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", width=220, height=480,
        )
        self.shortcuts_frame.place(relx=0.02, rely=0.15, anchor="nw")
        self._init_scroll_reset()
        self.quick_jump_badge = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 20, "bold"),
            fg_color="#333333", text_color="white", corner_radius=8,
            width=40, height=40
        )
        self._all_apps = []
        self._refresh_apps()

    def _render_calendar(self):
        for w in self.calendar_frame.winfo_children():
            w.destroy()

        now = datetime.now()
        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(now.year, now.month)

        headers = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, h in enumerate(headers):
            ctk.CTkLabel(
                self.calendar_frame, text=h, font=(FONT_FAMILY, 12, "bold"),
                text_color="gray50", width=32,
            ).grid(row=0, column=col, padx=2, pady=2)

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    text = ""
                    text_color = "gray20"
                    bg_color = "transparent"
                else:
                    text = str(day)
                    is_today = (day == now.day)
                    
                    text_color = "black" if is_today else "gray60"
                    
                    bg_color = "#e0e0e0" if is_today else "transparent"

                ctk.CTkLabel(
                    self.calendar_frame,
                    text=text,
                    font=(FONT_FAMILY, 12, "bold"),
                    text_color=text_color,
                    fg_color=bg_color,
                    corner_radius=8,
                    width=32,
                    height=32
                ).grid(row=row, column= col, padx=2, pady=2)

    def _refresh_apps(self):
        try:
            self._all_apps = get_all_apps()
        except Exception:
            self._all_apps = []
        self._render_shortcuts()

    def _render_shortcuts(self):
        if not hasattr(self, "_shortcut_widgets"):
            self._shortcut_widgets = {}
            self._no_matches_label = ctk.CTkLabel(
                self.shortcuts_frame, text="", text_color="gray40", font=(FONT_FAMILY, 12)
            )
            self._separator_label = ctk.CTkLabel(
                self.shortcuts_frame, text="\u2500" * 16, text_color="gray15", font=(FONT_FAMILY, 8)
            )

        self._no_matches_label.pack_forget()
        self._separator_label.pack_forget()
        for btn in self._shortcut_widgets.values():
            btn.pack_forget()

        items = self._all_apps
        if self._quick_filter:
            items = [i for i in items if i["name"].lower().startswith(self._quick_filter)]

        if not items:
            msg = "No matches" if self._quick_filter else "No apps found"
            self._no_matches_label.configure(text=msg)
            self._no_matches_label.pack(pady=10)
            return

        pinned_items = [i for i in items if i["path"] in self._pinned]
        rest_items = [i for i in items if i["path"] not in self._pinned]

        for item in pinned_items:
            self._pack_shortcut_row(item, pinned=True)

        if pinned_items and rest_items:
            self._separator_label.pack(pady=(2, 4))

        for item in rest_items:
            self._pack_shortcut_row(item, pinned=False)

    def _pack_shortcut_row(self, item: dict, pinned: bool):
        path = item["path"]
        
        if path not in self._shortcut_widgets:
            btn = ctk.CTkButton(
                self.shortcuts_frame,
                text="",
                fg_color="transparent",
                hover_color="#1a1a1a",
                text_color="white",
                anchor="w",
                font=(FONT_FAMILY, 13),
                command=lambda p=item["target"]: self._launch_app(p),
            )
            btn.bind("<Button-3>", lambda e, p=path: self._toggle_pin(p))
            self._shortcut_widgets[path] = btn
            
        btn = self._shortcut_widgets[path]
        
        folder_prefix = "\U0001F4C1  " if item["is_folder"] else ""
        pin_prefix = "\U0001F4CC  " if pinned else ""
        btn.configure(text=f"{pin_prefix}{folder_prefix}{item['name']}")
        
        btn.pack(fill="x", pady=1)

    def _toggle_pin(self, path: str):
        self._pinned = pins.toggle_pin(path)
        self._render_shortcuts()
        if self._on_pins_changed:
            self._on_pins_changed()

    def _tick(self):
        now = datetime.now()
        self.clock_label.configure(text=now.strftime("%H:%M"))
        self.date_label.configure(text=now.strftime("%A, %d %B %Y"))

        if now.strftime("%H:%M:%S") == "00:00:01":
            self._render_calendar()

        self.after(1000, self._tick)

    def refresh_shortcuts(self):
        self._refresh_apps()


    def _on_quick_filter_key(self, event):
        char = event.char
        if not char or not char.isalnum():
            return

        self._quick_filter = char.lower()
        self.quick_jump_badge.configure(text=char.upper())
        self.quick_jump_badge.place(relx=0.02, rely=0.10, anchor="nw")
        self._render_shortcuts()

        if self._quick_filter_job is not None:
            self.after_cancel(self._quick_filter_job)
        self._quick_filter_job = self.after(QUICK_FILTER_CLEAR_MS, self._clear_quick_filter)

    def _clear_quick_filter(self):
        self._quick_filter_job = None
        self.quick_jump_badge.place_forget()
        if self._quick_filter:
            self._quick_filter = ""
            self._render_shortcuts()


    def _init_scroll_reset(self):        
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, self._on_list_scrolled, add="+")

    def _on_list_scrolled(self, event=None):
        if self._scroll_reset_job is not None:
            self.after_cancel(self._scroll_reset_job)
        self._scroll_reset_job = self.after(SCROLL_RESET_MS, self._scroll_list_to_top)

    def _scroll_list_to_top(self):
        self._scroll_reset_job = None
        canvas = getattr(self.shortcuts_frame, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(0)

    def _pin_to_desktop(self):
        hwnd = self.winfo_id()
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )

class OverlayMediaPlayer(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0A0A0A", corner_radius=14, **kwargs)
        
        self._last_thumbnail = None

        self._optimistic_playing = None
        self._optimistic_until = 0.0
        self._current_track_key = None  # (title, artist) - tracks song changes
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.vol_slider = ctk.CTkSlider(
            self, from_=0, to=1, orientation="vertical",
            height=90, width=12, progress_color="white",
            fg_color="#333333", button_color="white", button_hover_color="#e0e0e0",
            command=self._set_spotify_volume
        )
        self.vol_slider.set(self._get_spotify_volume())
        self.vol_slider.pack(side="right", fill="y", padx=(0, 15), pady=12) 
        
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=15, pady=(10, 5))
        
        self.cover_label = ctk.CTkLabel(
            top_frame, text="♪", width=75, height=75,
            fg_color="#242424", corner_radius=10,text_color="#888888", font=(FONT_FAMILY, 24, "bold")
        )
        self.cover_label.pack(side="left", padx=(0, 15))
        
        info_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True)
        
        self.title_label = ctk.CTkLabel(
            info_frame, text="Media", anchor="w", font=(FONT_FAMILY, 15, "bold"), text_color="white"
        )
        self.title_label.pack(fill="x", pady=(0, 0))
        
        self.artist_label = ctk.CTkLabel(
            info_frame, text="Not playing", anchor="w", font=(FONT_FAMILY, 12), text_color="gray60"
        )
        self.artist_label.pack(fill="x", pady=(0, 0))
        
        ctrl_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        ctrl_frame.pack(fill="x")
        
        inner_ctrl = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        inner_ctrl.pack(anchor="w")
        
        ctk.CTkButton(
            inner_ctrl, text="⏮", width=30, height=24, fg_color="transparent", 
            hover_color="#2b2b2b", font=("Segoe UI Symbol", 15), 
            command=lambda: self._cmd("previous")
        ).pack(side="left")
        
        self.play_btn = ctk.CTkButton(
            inner_ctrl, text="▶", width=36, height=24, fg_color="transparent", 
            hover_color="#2b2b2b", font=("Segoe UI Symbol", 15), 
            command=lambda: self._cmd("toggle")
        )
        self.play_btn.pack(side="left", padx=4)
        
        ctk.CTkButton(
            inner_ctrl, text="⏭", width=30, height=24, fg_color="transparent", 
            hover_color="#2b2b2b", font=("Segoe UI Symbol", 15), 
            command=lambda: self._cmd("next")
        ).pack(side="left")

        time_frame = ctk.CTkFrame(self, fg_color="transparent")
        time_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.time_current = ctk.CTkLabel(time_frame, text="0:00", font=(FONT_FAMILY, 10), text_color="gray50", width=35, anchor="e")
        self.time_current.pack(side="left")
        
        self.progress = ctk.CTkSlider(
            time_frame, height=12, progress_color="white", fg_color="#333333", 
            button_color="white", button_hover_color="#e0e0e0", command=self._on_seek
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.progress.set(0)
        
        self.time_total = ctk.CTkLabel(time_frame, text="0:00", font=(FONT_FAMILY, 10), text_color="gray50", width=35, anchor="w")
        self.time_total.pack(side="right")

        self._user_dragging = False
        self.progress.bind("<ButtonPress-1>", lambda e: setattr(self, '_user_dragging', True), add="+")
        self.progress.bind("<ButtonRelease-1>", lambda e: self.after(200, lambda: setattr(self, '_user_dragging', False)), add="+")
        
        self._last_dur = 0
        self._seek_job = None
        self._refresh_loop()

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

    def _on_seek(self, value):
        if self._last_dur <= 0:
            return
            
        target_sec = value * self._last_dur
        self.time_current.configure(text=self._fmt_time(target_sec))
        
        if self._seek_job is not None:
            self.after_cancel(self._seek_job)
        self._seek_job = self.after(150, lambda: threading.Thread(
            target=lambda: SpotifyMediaController.command("seek", target_sec), daemon=True
        ).start())

    def _fmt_time(self, seconds):
        if seconds <= 0: return "0:00"
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

    def _cmd(self, command):
        if command == "toggle":
            currently_playing = self.play_btn.cget("text") == "⏸"
            new_playing = not currently_playing
            self.play_btn.configure(text="⏸" if new_playing else "▶")
            self._optimistic_playing = new_playing
            self._optimistic_until = time.monotonic() + 2.0

        threading.Thread(
            target=lambda: SpotifyMediaController.command(command), daemon=True
        ).start()

    def _refresh_loop(self):
        if self.winfo_exists():
            self._update_ui(SpotifyMediaController.get_info())
        self.after(1000, self._refresh_loop)

    def _update_ui(self, info):
        if not info:
            if self.winfo_ismapped():
                self.place_forget()
            return
            
        if not self.winfo_ismapped():
            self.place(relx=0.98, rely=0.15, anchor="ne")

        if hasattr(self, "vol_slider") and not getattr(self, "_vol_fetch_in_flight", False):
            self._vol_fetch_in_flight = True

            def fetch_volume():
                try:
                    vol = self._get_spotify_volume()
                except Exception:
                    vol = None
                self._vol_fetch_in_flight = False
                if vol is not None and self.winfo_exists():
                    self.after(0, lambda: self.vol_slider.set(vol))

            self._thread_pool.submit(fetch_volume)
            
        raw_title = info.get("title") or "Unknown"
        raw_artist = info.get("artist") or "Unknown"

        title = raw_title
        artist = raw_artist
        
        if len(title) > 26:
            title = title[:24] + "..."
        if len(artist) > 26:
            artist = artist[:24] + "..."
            
        self.title_label.configure(text=title)
        self.artist_label.configure(text=artist)

        is_playing = bool(info.get("is_playing"))
        if self._optimistic_playing is not None:
            if time.monotonic() < self._optimistic_until:
                is_playing = self._optimistic_playing
            else:
                self._optimistic_playing = None
        self.play_btn.configure(text="⏸" if is_playing else "▶")

        pos = info.get("position", 0)
        dur = info.get("duration", 0)
        self._last_dur = dur
        self.time_total.configure(text=self._fmt_time(dur))
        
        if not getattr(self, "_user_dragging", False):
            self.time_current.configure(text=self._fmt_time(pos))
            if dur > 0:
                self.progress.set(pos / dur)
            else:
                self.progress.set(0)

        thumb = info.get("thumbnail")
        if thumb and thumb != self._last_thumbnail:
            try:
                from io import BytesIO
                from PIL import Image
                
                img = Image.open(BytesIO(thumb)).convert("RGB")
                
                img = img.resize((75, 75), Image.Resampling.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(75, 75))
                
                self.cover_label.configure(image=ctk_img, text="", fg_color="transparent")
                self._last_thumbnail = thumb
            except Exception:
                pass