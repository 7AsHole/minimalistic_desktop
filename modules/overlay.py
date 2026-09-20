import calendar
import os
import concurrent.futures
import win32con
import win32gui
import threading
import time
from datetime import datetime
import re
import math

import customtkinter as ctk
from io import BytesIO
from PIL import Image
from .statusbar import SpotifyMediaController
from . import pins
from .shortcuts import get_all_apps

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Bahnschrift"  

SCROLL_RESET_MS = 10_000
QUICK_FILTER_CLEAR_MS = 10_000
class DesktopOverlay(ctk.CTk):
    def __init__(self, on_quit=None, on_pins_changed=None, on_background_click=None):
        super().__init__()
        self.title("MinimalisticDesktop")
        self.overrideredirect(True)
        self.configure(fg_color="black")
        self._on_quit = on_quit
        self._on_pins_changed = on_pins_changed
        self._on_background_click = on_background_click

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
        self.text_box = TextBox(self)
        self.text_box.place(relx=0.98, rely=0.35, anchor="ne")
        self.text_box.match_width(self.media_player)
        self._tick()

        self.bind("<Enter>", self._delayed_focus, add="+")

    def _delayed_focus(self, e=None):
        self.after(500, self._focus_self_if_idle)

    def _focus_self_if_idle(self):
        if not self.text_box.is_editing():
            self.focus_set()

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
        self.bind("<Button-1>", self._on_background_click_event, add="+")
        self.bind("<Button-1>", self._release_textbox_on_click, add="+")

    def _release_textbox_on_click(self, event):
        tb = getattr(self, "text_box", None)
        if tb is not None and tb.is_editing() and not tb.owns(event.widget):
            tb.release_focus()

    def _on_background_click_event(self, event):
        if event.widget is not self:
            return
        if self._on_background_click:
            self._on_background_click()

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
                    continue

                is_today = (day == now.day)              
                text_color = "white" if is_today else "gray60"
                bg_color = "#0E0E0E" if is_today else "transparent"
                hover_text = "white" if is_today else "white"

                date = ctk.CTkLabel(
                    self.calendar_frame,
                    text=str(day),
                    font=(FONT_FAMILY, 12, "bold"),
                    text_color=text_color,
                    fg_color=bg_color,
                    corner_radius=8,
                    width=32,
                    height=32
                )
                date.grid(row=row, column= col, padx=2, pady=2)
                date.bind("<Enter>", lambda e, label=date, h_t=hover_text: label.configure(text_color=h_t))
                date.bind("<Leave>", lambda e, label=date, ori_color=text_color: label.configure(text_color=ori_color))

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
        self.vol_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.vol_frame.pack(side="right", fill="y", padx=(0, 15), pady=12)

        self.vol_value_label = ctk.CTkLabel(
            self.vol_frame, text="100", font=(FONT_FAMILY, 9), text_color="#AAAAAA", width=18
        )
        self.vol_value_label.pack(side="top", pady=(0, 0))

        self.vol_slider = ctk.CTkSlider(
            self.vol_frame, from_=0, to=1, orientation="vertical",
            height=90, width=12, progress_color="#ebebeb",
            fg_color="#333333", button_color="white", button_hover_color="#e0e0e0",
            command=self._set_spotify_volume
        )
        initial_vol = self._get_spotify_volume()
        self.vol_slider.set(initial_vol)
        self.vol_value_label.configure(text=str(int(round(initial_vol * 100))))
        self.vol_slider.pack(side="top", fill="y", expand=True)
        
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=(5, 15), pady=(10, 5))
        
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

    def _apply_fetched_volume(self, vol):
        self.vol_slider.set(vol)
        if hasattr(self, "vol_value_label"):
            self.vol_value_label.configure(text=str(int(round(float(vol) * 100))))

    def _set_spotify_volume(self, val):
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        for session in AudioUtilities.GetAllSessions():
            if session.Process and session.Process.name().lower() == "spotify.exe":
                session._ctl.QueryInterface(ISimpleAudioVolume).SetMasterVolume(val, None)
        if hasattr(self, "vol_value_label"):
            self.vol_value_label.configure(text=str(int(round(float(val) * 100))))

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
                    self.after(0, lambda: self._apply_fetched_volume(vol))

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

class TextBox(ctk.CTkFrame):
    EXPR_CHARS = set("0123456789.+-*/xX")
    MATH_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s*[-+xX*/]\s*\d+(?:\.\d+)?)+)$")
    CORNER = 6
    INNER_PAD = 4
    MIN_BOX_H = 44
    MAX_LINES = 20
    PAD = 6  # frame padding around the textbox

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0A0A0A", corner_radius=14,
                         height=self.MIN_BOX_H + 2 * self.PAD, **kwargs)
        self.pack_propagate(False)  # width/height are set from code, not by contents
        self._box_h = self.MIN_BOX_H
        self._dismissed = None
        self.text_entry = ctk.CTkTextbox(
            self, height=self.MIN_BOX_H, fg_color="#060606", text_color="#c1c1c1",
            font=(FONT_FAMILY, 12), wrap="word", corner_radius=self.CORNER, activate_scrollbars=False
        )
        self.text_entry.pack(fill="x", padx=self.PAD, pady=self.PAD, expand=True)
        inner = self.text_entry._textbox
        inner.configure(selectbackground="#000000", selectforeground="#ffffff",
                        inactiveselectbackground="#202020")
        inner.configure(pady=self.INNER_PAD)
        # Keys typed here must not reach the overlay's <Key>/<space>/... handlers.
        root_tag = str(self.winfo_toplevel())
        inner.bindtags(tuple(t for t in inner.bindtags() if t != root_tag))

        # Placeholder (CTkTextbox has none built in)
        self._placeholder_on = False
        self.PLACEHOLDER = "Click to Type...."
        inner.tag_configure("placeholder", foreground="gray50")
        inner.tag_configure("mathlive", foreground="gray50")
        inner.bind("<KeyPress>", self._on_key)
        # Enter = save + release focus, Shift+Enter = newline
        inner.bind("<Return>", self._on_return)
        inner.bind("<Shift-Return>", self._on_shift_return)
        inner.bind("<FocusIn>", lambda e: self._update_placeholder(), add="+")
        inner.bind("<FocusOut>", self._on_focus_out, add="+")
        inner.bind("<<Modified>>", self._on_modified)
        inner.bind("<Configure>", lambda e: self._resize(), add="+")

        try:
            with open("saved_note.txt", "r") as f:
                self.text_entry.insert("1.0", f.read())
        except OSError:
            pass
        inner.edit_modified(False)
        self._update_placeholder()

    # ---------- sizing ----------
    def _get_text(self) -> str:
        """Real note text (empty while the placeholder is showing)."""
        if self._placeholder_on:
            return ""
        return self.text_entry.get("1.0", "end-1c")
    def _cancel_math(self):
        tb = self.text_entry._textbox
        live = tb.tag_ranges("mathlive")
        if not live:
            return
        start, end = str(live[0]), str(live[1])
        self._dismissed = (start, tb.get(f"{start} linestart", start))
        tb.delete(start, end)
        tb.mark_set("insert", start)

    def match_width(self, widget):
        """Keep this box the same width as `widget` (the media player)."""
        def _sync(_event=None):
            w = widget.winfo_reqwidth()
            if w > 1:
                unscale = getattr(widget, "_reverse_widget_scaling", lambda v: v)
                self.configure(width=unscale(w))
        widget.bind("<Configure>", _sync, add="+")
        self.after(100, _sync)

    def _resize(self):
        inner = self.text_entry._textbox
        if inner.winfo_width() <= 1:
            return
        inner.update_idletasks()
        res = inner.count("1.0", "end", "displaylines")
        lines = min(max(1, res[0] if res else 1), self.MAX_LINES)

        line_h = int(inner.tk.call("font", "metrics", inner.cget("font"), "-linespace"))
        unscale = getattr(self.text_entry, "_reverse_widget_scaling", lambda v: v)
        # text + CTkTextbox's 8px top/bottom padding + Tk's own 1px top/bottom
        text_area = lines * line_h + 2 * self.INNER_PAD   # real px
        box_h = math.ceil(unscale(text_area)) + 2 * self.CORNER + 1

        if box_h == self._box_h:
            return
        self._box_h = box_h
        self.text_entry.configure(height=box_h)
        self.configure(height=box_h + 2 * self.PAD)

    # ---------- events ----------

    def _on_modified(self, event=None):
        inner = self.text_entry._textbox
        if inner.edit_modified():
            inner.edit_modified(False)
            self._update_math()
            self._update_placeholder()
            self.after_idle(self._resize)

    def _on_return(self, event=None):
        self.release_focus()
        return "break"  # stop Tk from inserting a newline

    def _on_shift_return(self, event=None):
        self._commit_math()
        self.text_entry._textbox.insert("insert", "\n")
        self.text_entry._textbox.see("insert")
        return "break"

    def _on_focus_out(self, event=None):
        self._save_content()
        self._update_placeholder()

    def _update_placeholder(self):
        tb = self.text_entry._textbox
        editing = self.is_editing()
        if self._placeholder_on:
            if editing:                       # user clicked in: clear it
                tb.delete("1.0", "end-1c")
                self._placeholder_on = False
        elif not editing and not tb.get("1.0", "end-1c"):
            tb.insert("1.0", self.PLACEHOLDER, "placeholder")
            self._placeholder_on = True

    # ---------- focus / save ----------

    def is_editing(self) -> bool:
        try:
            return self.focus_get() is self.text_entry._textbox
        except Exception:
            return False

    def owns(self, widget) -> bool:
        return widget in (
            self.text_entry._textbox,
            getattr(self.text_entry, "_canvas", None),
        )

    def release_focus(self):
        self._save_content()
        self.winfo_toplevel().focus_set()

        # ---------- live math ----------

    def _on_key(self, event):
        tb = self.text_entry._textbox
        live = tb.tag_ranges("mathlive")
        if not live:
            return
        at_start = tb.compare(tb.index("insert"), "==", str(live[0]))

        if event.keysym == "Escape" and at_start:
            self._cancel_math()          # drop the result, keep the expression
            return "break"
        if event.keysym == "Left" and at_start:
            self._cancel_math()          # then Left moves as normal
            return

        if not at_start:
            self._commit_math(move_cursor=False)   # cursor left the result: it's plain text now
            return
        if event.keysym == "Right":
            self._commit_math(move_cursor=False)   # keep the result as text, then Right moves normally
            return

        if not event.char:
            return
        if event.char in self.EXPR_CHARS or event.char in ("\x08", "\x7f"):
            return
        self._commit_math()

    def _commit_math(self, move_cursor=True):
        tb = self.text_entry._textbox
        live = tb.tag_ranges("mathlive")
        if live:
            start, end = str(live[0]), str(live[1])
            tb.tag_remove("mathlive", start, end)
            if move_cursor:
                tb.mark_set("insert", end)

    def _update_math(self):
        tb = self.text_entry._textbox
        if not self.is_editing():
            return
        live = tb.tag_ranges("mathlive")
        cursor = tb.index("insert")

        # cursor wandered off, so the old result is final
        if live and not tb.compare(cursor, "==", str(live[0])):
            self._commit_math(move_cursor=False)
            live = ()

        pos = str(live[0]) if live else cursor
        before = tb.get(f"{pos} linestart", pos)

        # cursor is inside a number/expression, not at its end
        if not live and tb.get(pos, f"{pos}+1c") in self.EXPR_CHARS:
            return

        if self._dismissed is not None:
            if not live and self._dismissed == (pos, before):
                return  # user cancelled this one, leave it alone
            self._dismissed = None

        result = self._math_result(before)
        desired = f" = {result}" if result is not None else None
        current = tb.get(str(live[0]), str(live[1])) if live else None
        if desired == current:
            return  # already correct (this is what stops edit loops)

        if live:
            tb.delete(str(live[0]), str(live[1]))
        if desired:
            tb.insert(pos, desired, "mathlive")
        tb.mark_set("insert", pos)  # keep the cursor before the result

    def _math_result(self, before: str):
        m = self.MATH_RE.search(before)
        if not m:
            return None
        expr = m.group(1)
        ops = re.findall(r"[-+xX*/]", expr)
        if len(ops) >= 2 and set(ops) == {"-"}:  # dates, phone numbers
            return None

        tokens = re.findall(r"\d+(?:\.\d+)?|[-+xX*/]", expr)
        vals = [float(tokens[0])]
        ops = []
        for i in range(1, len(tokens), 2):
            ops.append(tokens[i])
            vals.append(float(tokens[i + 1]))

        # pass 1: multiply / divide
        out_vals, out_ops = [vals[0]], []
        for op, v in zip(ops, vals[1:]):
            if op in "xX*":
                out_vals[-1] *= v
            elif op == "/":
                if v == 0:
                    return None
                out_vals[-1] /= v
            else:
                out_ops.append(op)
                out_vals.append(v)

        # pass 2: add / subtract
        total = out_vals[0]
        for op, v in zip(out_ops, out_vals[1:]):
            total = total + v if op == "+" else total - v

        if total.is_integer() and abs(total) < 1e15:
            return str(int(total))
        return f"{total:.10g}"

    def _save_content(self, event=None):
        self._commit_math()
        try:
            with open("saved_note.txt", "w") as f:
                f.write(self._get_text())
        except OSError as e:
            print(f"[textbox] Could not save note: {e}")
    