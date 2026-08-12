"""
The desktop overlay: a borderless fullscreen CustomTkinter window pinned to
the bottom of the z-order (so real windows still sit on top of it, and
Win+D / "show desktop" still works normally).

It shows:
  - a big clock + date
  - a small calendar
  - your real desktop shortcuts, as plain text (no icons)

Folders keep a tiny glyph prefix since rule #2 exempts folders/img/vid.
"""
import calendar
import os
from datetime import datetime

import customtkinter as ctk
import win32con
import win32gui

from .shortcuts import get_desktop_items

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Segoe UI"


class DesktopOverlay(ctk.CTk):
    def __init__(self, on_quit=None):
        """on_quit: optional callback fired right before the window is destroyed,
        e.g. to trigger the restore-previous-settings logic in main.py."""
        super().__init__()
        self.title("MinimalisticDesktop")
        self.overrideredirect(True)  # no titlebar/border
        self.configure(fg_color="black")
        self._on_quit = on_quit

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")

        self._build_ui()
        self.after(200, self._pin_to_desktop)  # give the window time to get an HWND
        self._bind_quit_controls()
        self._tick()
        self._fast_poll()  # keeps the Tk event loop ticking fast so Ctrl+C gets noticed promptly

    def _bind_quit_controls(self):
        # No titlebar means no "X" button, so give explicit ways to exit + restore.
        self.bind("<Escape>", lambda e: self.request_quit())

        quit_btn = ctk.CTkButton(
            self, text="\u2715  Quit & Restore", width=140, height=28,
            fg_color="#1a1a1a", hover_color="#2a2a2a", text_color="gray70",
            font=(FONT_FAMILY, 11), command=self.request_quit,
        )
        quit_btn.place(relx=0.98, rely=0.02, anchor="ne")

        hint = ctk.CTkLabel(
            self, text="Esc or the button above to quit and restore your original desktop",
            font=(FONT_FAMILY, 10), text_color="gray30",
        )
        hint.place(relx=0.5, rely=0.98, anchor="s")

    def request_quit(self):
        if self._on_quit:
            self._on_quit()
        self.destroy()

    def _fast_poll(self):
        # Empty tick, just here so the interpreter gets control often enough
        # for KeyboardInterrupt (Ctrl+C) to actually land on Windows.
        self.after(100, self._fast_poll)

    # ---------- UI ----------

    def _build_ui(self):
        # Clock + date, centered
        self.clock_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 72, "bold"), text_color="white"
        )
        self.clock_label.place(relx=0.5, rely=0.38, anchor="center")

        self.date_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 18), text_color="gray70"
        )
        self.date_label.place(relx=0.5, rely=0.46, anchor="center")

        # Mini calendar, below the date
        self.calendar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.calendar_frame.place(relx=0.5, rely=0.62, anchor="n")
        self._render_calendar()

        # Shortcuts list, top-left, plain text
        self.shortcuts_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", width=220, height=500,
        )
        self.shortcuts_frame.place(relx=0.02, rely=0.04, anchor="nw")
        self._render_shortcuts()

    def _render_calendar(self):
        for w in self.calendar_frame.winfo_children():
            w.destroy()

        now = datetime.now()
        cal = calendar.Calendar(firstweekday=0)  # Monday first
        weeks = cal.monthdayscalendar(now.year, now.month)

        headers = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, h in enumerate(headers):
            ctk.CTkLabel(
                self.calendar_frame, text=h, font=(FONT_FAMILY, 11, "bold"),
                text_color="gray50", width=32,
            ).grid(row=0, column=col, padx=2, pady=2)

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    text = ""
                    color = "gray20"
                else:
                    text = str(day)
                    color = "white" if day == now.day else "gray60"
                ctk.CTkLabel(
                    self.calendar_frame, text=text, font=(FONT_FAMILY, 12),
                    text_color=color, width=32,
                ).grid(row=row, column=col, padx=2, pady=2)

    def _render_shortcuts(self):
        for w in self.shortcuts_frame.winfo_children():
            w.destroy()

        try:
            items = get_desktop_items()
        except Exception:
            items = []

        for item in items:
            prefix = "\U0001F4C1  " if item["is_folder"] else ""  # folder glyph exempt per rule #2
            btn = ctk.CTkButton(
                self.shortcuts_frame,
                text=f"{prefix}{item['name']}",
                fg_color="transparent",
                hover_color="#1a1a1a",
                text_color="white",
                anchor="w",
                font=(FONT_FAMILY, 13),
                command=lambda p=item["target"]: os.startfile(p),
            )
            btn.pack(fill="x", pady=1)

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
        """Call this if you add/remove desktop shortcuts and want the overlay to update."""
        self._render_shortcuts()

    def _pin_to_desktop(self):
        """Pushes this window to the bottom of the z-order so real app windows
        always render on top of it, like a true desktop background layer."""
        hwnd = self.winfo_id()
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
