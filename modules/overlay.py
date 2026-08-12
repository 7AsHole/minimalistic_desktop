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

from .shortcuts import get_all_apps

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
        self.bind("<Escape>", lambda e: self._handle_escape())
        self.bind("<Control-s>", lambda e: self._toggle_search())
        self.bind("<Control-S>", lambda e: self._toggle_search())  # shift/capslock variant

        quit_btn = ctk.CTkButton(
            self, text="\u2715  Quit & Restore", width=140, height=28,
            fg_color="#1a1a1a", hover_color="#2a2a2a", text_color="gray70",
            font=(FONT_FAMILY, 11), command=self.request_quit,
        )
        quit_btn.place(relx=0.98, rely=0.02, anchor="ne")

        hint = ctk.CTkLabel(
            self, text="Ctrl+S to search  \u00b7  Esc to close search / quit and restore",
            font=(FONT_FAMILY, 10), text_color="gray30",
        )
        hint.place(relx=0.5, rely=0.98, anchor="s")

    def _handle_escape(self):
        """First Esc closes an open search bar; Esc with no search open quits."""
        if self._search_visible:
            self._hide_search()
        else:
            self.request_quit()

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
        self.clock_label.place(relx=0.5, rely=0.32, anchor="center")

        self.date_label = ctk.CTkLabel(
            self, text="", font=(FONT_FAMILY, 18), text_color="gray70"
        )
        self.date_label.place(relx=0.5, rely=0.4, anchor="center")

        # Mini calendar, below the date
        self.calendar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.calendar_frame.place(relx=0.5, rely=0.48, anchor="n")
        self._render_calendar()

        # Search bar - hidden until Ctrl+S is pressed, filters the app list below
        self._search_visible = False
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._render_shortcuts())
        self.search_entry = ctk.CTkEntry(
            self, textvariable=self.search_var, placeholder_text="Search apps... (Esc to close)",
            width=220, height=30, fg_color="#111111", border_color="#333333",
            text_color="white", font=(FONT_FAMILY, 13),
        )
        self.search_entry.bind("<Escape>", lambda e: (self._hide_search(), "break"))

        # Shortcuts list, top-left, plain text. Sourced from every app in the
        # Start Menu (not just the desktop), so it's scrollable and searchable.
        self.shortcuts_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", width=220, height=480,
        )
        self.shortcuts_frame.place(relx=0.02, rely=0.2, anchor="nw")

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
                self.calendar_frame, text=h, font=(FONT_FAMILY, 11, "bold"),
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
                    bg_color = "white" if is_today else "transparent"

                ctk.CTkLabel(
                    self.calendar_frame,
                    text=text,
                    font=(FONT_FAMILY, 12, "bold"),
                    text_color=text_color,
                    fg_color=bg_color,
                    corner_radius=8,
                    width=32,
                    height=32,
                ).grid(row=row, column=col, padx=2, pady=2)

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

        query = self.search_var.get().strip().lower()
        items = self._all_apps
        if query:
            items = [i for i in items if query in i["name"].lower()]

        if not items:
            msg = "No matches" if query else "No apps found"
            ctk.CTkLabel(
                self.shortcuts_frame, text=msg, text_color="gray40", font=(FONT_FAMILY, 12)
            ).pack(pady=10)
            return

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
        """Call this if you install/remove apps and want the overlay's list to update."""
        self._refresh_apps()

    def _toggle_search(self):
        if self._search_visible:
            self._hide_search()
        else:
            self._show_search()

    def _show_search(self):
        self._search_visible = True
        self.search_entry.place(relx=0.02, rely=0.2, anchor="nw")
        self.shortcuts_frame.place(relx=0.02, rely=0.265, anchor="nw")  # shift list down
        self.search_entry.focus_set()

    def _hide_search(self):
        self._search_visible = False
        self.search_var.set("")  # clears the filter too, so the full list shows again
        self.search_entry.place_forget()
        self.shortcuts_frame.place(relx=0.02, rely=0.2, anchor="nw")
        self.focus_set()  # return keyboard focus to the window so Esc/Ctrl+S still fire

    def _pin_to_desktop(self):
        """Pushes this window to the bottom of the z-order so real app windows
        always render on top of it, like a true desktop background layer."""
        hwnd = self.winfo_id()
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
