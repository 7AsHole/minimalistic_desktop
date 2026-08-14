"""
The desktop overlay: a borderless fullscreen CustomTkinter window pinned to
the bottom of the z-order (so real windows still sit on top of it, and
Win+D / "show desktop" still works normally).

It shows:
  - a big clock + date
  - a small calendar
  - your real desktop shortcuts, as plain text (no icons)

Folders keep a tiny glyph prefix since rule #2 exempts folders/img/vid.

Quit and restore from the tray icon in the notification area's "hidden icons"
flyout (see modules/tray.py, wired up from main.py).
"""
import calendar
import os
from datetime import datetime

import customtkinter as ctk
import win32con
import win32gui

from . import pins
from .shortcuts import get_all_apps

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Bahnschrift"  

# How long the list waits after the last scroll before snapping back to top.
SCROLL_RESET_MS = 5_000
# How long a quick-letter jump filter stays active before clearing itself.
QUICK_FILTER_CLEAR_MS = 3_000


class DesktopOverlay(ctk.CTk):
    def __init__(self, on_quit=None, on_pins_changed=None):
        """on_quit: optional callback fired right before the window is destroyed,
        e.g. to trigger the restore-previous-settings logic in main.py.
        on_pins_changed: optional callback fired whenever a pin is toggled here,
        e.g. so modules/statusbar.py can refresh its own pinned-app buttons."""
        super().__init__()
        self.title("MinimalisticDesktop")
        self.overrideredirect(True)  # no titlebar/border
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
        self.after(200, self._pin_to_desktop)  # give the window time to get an HWND
        self._bind_controls()
        self._tick()

    def _launch_app(self, path: str):
        try:
            os.startfile(path)
        except Exception as e:
            # Optionally show an error label here, or just silently ignore it
            print(f"Failed to open {path}: {e}") # keeps the Tk event loop ticking fast so Ctrl+C gets noticed promptly

    def _bind_controls(self):
        # Type-ahead: press any letter/number (while search is closed) to
        # jump the list to apps starting with it.
        self.bind("<Key>", self._on_quick_filter_key)

    def request_quit(self):
        if self._on_quit:
            self._on_quit()
        self.destroy()


    # ---------- UI ----------

    def _build_ui(self):
        # Clock + date, centered
        self.clock_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 88, "bold"), text_color="white"
        )
        self.clock_label.place(relx=0.5, rely=0.3, anchor="center")

        self.date_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 18), text_color="gray70"
        )
        self.date_label.place(relx=0.5, rely=0.38, anchor="center")

        # Mini calendar, below the date
        self.calendar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.calendar_frame.place(relx=0.5, rely=0.44, anchor="n")
        self._render_calendar()

        # Shortcuts list, top-left, plain text. The complete searchable app
        # launcher lives in the status-bar layer and opens with Ctrl+S.
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
        cal = calendar.Calendar(firstweekday=0)  # Monday first
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
                    
                    # Set colors based on whether it's today
                    text_color = "black" if is_today else "gray60"
                    
                    # Highlight today's date with a background color
                    bg_color = "#e0e0e0" if is_today else "transparent"  # #1f538d is CTk default blue

                ctk.CTkLabel(
                    self.calendar_frame,
                    text=text,
                    font=(FONT_FAMILY, 12, "bold"),
                    text_color=text_color,
                    fg_color=bg_color,        # <--- Sets background color for the shape
                    corner_radius=8,          # <--- Roundness of the corners (use 16 for a full circle)
                    width=32,
                    height=32                 # <--- Added height so it forms a square/circle shape
                ).grid(row=row, column= col, padx=2, pady=2)

    def _refresh_apps(self):
        """Re-scans the Start Menu for the full app list, then re-renders."""
        try:
            self._all_apps = get_all_apps()
        except Exception:
            self._all_apps = []
        self._render_shortcuts()

    def _render_shortcuts(self):
        for w in self.shortcuts_frame.winfo_children():
            w.destroy()

        items = self._all_apps
        if self._quick_filter:
            items = [i for i in items if i["name"].lower().startswith(self._quick_filter)]

        if not items:
            msg = "No matches" if self._quick_filter else "No apps found"
            ctk.CTkLabel(
                self.shortcuts_frame, text=msg, text_color="gray40", font=(FONT_FAMILY, 12)
            ).pack(pady=10)
            return

        # Pinned apps first (still inside the same scrollable list), then everything else.
        pinned_items = [i for i in items if i["path"] in self._pinned]
        rest_items = [i for i in items if i["path"] not in self._pinned]

        for item in pinned_items:
            self._make_shortcut_row(item, pinned=True)

        if pinned_items and rest_items:
            ctk.CTkLabel(
                self.shortcuts_frame, text="\u2500" * 16, text_color="gray15", font=(FONT_FAMILY, 8)
            ).pack(pady=(2, 4))

        for item in rest_items:
            self._make_shortcut_row(item, pinned=False)

    def _make_shortcut_row(self, item: dict, pinned: bool):
        folder_prefix = "\U0001F4C1  " if item["is_folder"] else ""  # folder glyph exempt per rule #2
        pin_prefix = "\U0001F4CC  " if pinned else ""
        btn = ctk.CTkButton(
            self.shortcuts_frame,
            text=f"{pin_prefix}{folder_prefix}{item['name']}",
            fg_color="transparent",
            hover_color="#1a1a1a",
            text_color="white",
            anchor="w",
            font=(FONT_FAMILY, 13),
            command=lambda p=item["target"]: self._launch_app(p),
        )
        btn.pack(fill="x", pady=1)
        # Right-click toggles pin, since left-click already launches the app.
        btn.bind("<Button-3>", lambda e, p=item["path"]: self._toggle_pin(p))

    def _toggle_pin(self, path: str):
        self._pinned = pins.toggle_pin(path)
        self._render_shortcuts()
        if self._on_pins_changed:
            self._on_pins_changed()

    # ---------- behavior ----------

    def _tick(self):
        now = datetime.now()
        self.clock_label.configure(text=now.strftime("%H:%M"))
        self.date_label.configure(text=now.strftime("%A, %d %B %Y"))

        # Re-render the calendar once a day (cheap check, avoids doing it every second)
        if now.strftime("%H:%M:%S") == "00:00:01":
            self._render_calendar()

        self.after(1000, self._tick)

    def refresh_shortcuts(self):
        """Call this if you install/remove apps and want the overlay's list to update."""
        self._refresh_apps()

    # ---------- quick-letter jump ----------

    def _on_quick_filter_key(self, event):
        """Pressing a letter/number while search is closed jumps the list to
        apps whose name starts with it (e.g. press 'b' to see everything
        starting with B). Clears itself a couple seconds after the last
        keypress, or immediately if you open real search instead."""
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

    # ---------- scroll auto-reset ----------

    def _init_scroll_reset(self):
        """After SCROLL_RESET_MS of no scrolling, snap the app list back to
        the top. add='+' so this rides alongside CTkScrollableFrame's own
        internal mousewheel handling instead of replacing it."""
        
        # Bind to 'self' (the whole window) instead of the canvas. 
        # This prevents the buttons from blocking the scroll event!
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
        """Pushes this window to the bottom of the z-order so real app windows
        always render on top of it, like a true desktop background layer."""
        hwnd = self.winfo_id()
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
