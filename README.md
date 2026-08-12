# Minimalistic Desktop (v1: steps 1-4)

A Python + CustomTkinter shell overlay for Windows that gives you a
minimal, text-only desktop: black wallpaper, dark mode, a clock/calendar,
and your shortcuts shown as plain text instead of icons.

## How it actually works (read this first)

Windows doesn't let outside apps reach into Explorer and restyle its
rendering (icons, taskbar, Start Menu) directly - that would require DLL
injection, which is fragile and breaks on every Windows update. So instead
of *modifying* Explorer, this app:

- Hides the **real** desktop icons
- Draws its **own** fullscreen window behind all your other app windows,
  showing a text-only shortcut list, clock, and calendar
- Leaves the taskbar itself alone (icons stay colored - see "Known
  limitations" below for why full monochrome isn't included here)

This means it's non-destructive and fully reversible - nothing about
Explorer.exe itself is modified, only your wallpaper, a theme registry
key, and the icon-visibility toggle (all things Windows' own Settings
app can undo).

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The app registers itself to start automatically for the current user at
Windows sign-in. It launches with taskbar search hidden by default.

Optional flags:

| Flag | What it does |
|---|---|
| `--keep-icons` | Don't hide the real desktop icons |
| `--hide-start-search` / `--hide-search-bar` | Hide the taskbar search control (the default) |
| `--show-start-search` | Keep the taskbar search control visible for this run |
| `--skip-system-changes` | Only launch the overlay, skip wallpaper/theme/icon changes |
| `--restore` | Don't launch anything - just revert to your last saved snapshot and exit |

## Reverting back to your original desktop

Before touching anything, the app snapshots your current wallpaper path and
theme settings into `state.json` (next to `main.py`). To go back to how
things were:

- **Normal exit:** right-click the app's icon in the
  system tray's **hidden icons flyout** (the `^` arrow next to the clock)
  and choose **"Quit & Restore"**. There's no on-screen quit button
  anymore - this route reverts wallpaper/theme/icons and closes the overlay.
- **Ctrl+C in the terminal:** also triggers a restore before the process exits.
- **Crash / killed via Task Manager:** nothing gets auto-restored in this
  case, but `state.json` survives, so just run `python main.py --restore`
  afterward and it'll revert from that saved snapshot.

Restoring is safe to run more than once - if there's nothing to restore
(no `state.json`), it just tells you so and exits.

If `pystray` isn't installed, the tray icon is skipped with a warning and
you must close the terminal or kill the process to quit; the rest of the
app still works.

## What each step does

1. **Black wallpaper** - generates a black PNG and sets it via
   `SystemParametersInfoW`. No admin needed.
2. **Text-only app list** - real desktop icons are hidden; the overlay reads
   the current-user and shared Start Menu program shortcuts and lists them as
   plain clickable text.
   - Press **Ctrl+S** to open search and filter by typing.
   - When search is **closed**, just press a letter/number key (e.g. `b`)
     to jump the list to apps starting with it. The filter clears itself
     a couple seconds after you stop typing.
   - **Right-click** any app to pin/unpin it. Pinned apps float to the top
     of the list (separated by a thin divider) but the list stays one
     single scrollable view - they're not frozen in place.
   - If you leave the list scrolled down and stop scrolling for **10
     seconds**, it automatically snaps back to the top.
   - Use the tray icon to quit and restore.
3. **Clock + calendar** - live on the overlay, updates every second.
4. **Dark mode** - flips `AppsUseLightTheme` / `SystemUsesLightTheme` in
   the registry, which darkens the taskbar/Start Menu chrome and most
   apps. This is the practical substitute for "monochrome taskbar" (see
   below for why true icon recoloring isn't in scope).
5. **Taskbar search hiding** - enabled by default (and passed on automatic
   startup) hides the
   separate taskbar search icon/box and restores its exact prior setting on
   exit. It cannot remove the search field inside the opened Start Menu.
6. **Tray icon** - a small icon appears in the notification area (often
   tucked under the "hidden icons" `^` chevron on first run - drag it out
   if you want it always visible). Right-click for "Quit & Restore".

## Known limitations (be aware of these before you rely on this)

- **Monochrome taskbar icons** are *not* implemented. Taskbar icons are
  rendered by Explorer.exe itself from each app's own resources -
  recoloring them system-wide would require injecting code into
  Explorer, which is unstable and can get flagged as malicious behavior
  by antivirus software. Dark mode (step 4) gets you most of the visual
  effect without that risk.
- **Desktop icon hiding is a toggle**, not an explicit on/off switch
  (that's how Windows exposes it). If you run the app twice without
  restarting, icons will flip back on. `main.py` doesn't currently
  persist this state across runs - worth adding if you find it annoying.
- **Tray icon placement** is up to Windows - new tray icons usually start
  collapsed into the hidden-icons flyout rather than pinned on the
  taskbar; that's normal Windows behavior, not a bug here.

## Project layout

```
minimalistic_desktop/
  main.py                  entry point - wires everything together
  modules/
    wallpaper.py            black wallpaper generation + set
    theme.py                dark mode registry + explorer restart
    desktop_icons.py        toggle native icon visibility
    shortcuts.py            reads Start Menu app shortcuts
    overlay.py              the CustomTkinter overlay window
    pins.py                 persists which apps are pinned to the top
    tray.py                 system tray icon (quit & restore)
    startup.py              current-user sign-in registration
  assets/                   generated black.png lives here
  requirements.txt
```

## Next up (v2, not built yet)

- Custom Start Menu launcher overlay (Win-key hook)
- Custom folder browser UI
- A "restore defaults" command
