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

Optional flags:

| Flag | What it does |
|---|---|
| `--keep-icons` | Don't hide the real desktop icons |
| `--lockscreen` | Also try to set a black lockscreen image (see limitation below) |
| `--skip-system-changes` | Only launch the overlay, skip wallpaper/theme/icon changes |
| `--restore` | Don't launch anything - just revert to your last saved snapshot and exit |

## Reverting back to your original desktop

Before touching anything, the app snapshots your current wallpaper path and
theme settings into `state.json` (next to `main.py`). To go back to how
things were:

- **Normal exit:** press **Esc**, or click the small "Quit & Restore" button
  in the top-right of the overlay. Either one reverts wallpaper/theme/icons
  and closes.
- **Ctrl+C in the terminal:** also triggers a restore before the process exits.
- **Crash / killed via Task Manager:** nothing gets auto-restored in this
  case, but `state.json` survives, so just run `python main.py --restore`
  afterward and it'll revert from that saved snapshot.

Restoring is safe to run more than once - if there's nothing to restore
(no `state.json`), it just tells you so and exits.

## What each step does

1. **Black wallpaper** - generates a black PNG and sets it via
   `SystemParametersInfoW`. No admin needed.
2. **Text-only shortcuts** - real desktop icons are hidden; the overlay
   reads your actual `.lnk` files and folders from
   `C:\Users\<you>\Desktop` and lists them as plain clickable text.
   Clicking launches the real target via `os.startfile()`.
3. **Clock + calendar** - live on the overlay, updates every second.
4. **Dark mode** - flips `AppsUseLightTheme` / `SystemUsesLightTheme` in
   the registry, which darkens the taskbar/Start Menu chrome and most
   apps. This is the practical substitute for "monochrome taskbar" (see
   below for why true icon recoloring isn't in scope).

## Known limitations (be aware of these before you rely on this)

- **Lockscreen black background** only works on **Windows Pro /
  Enterprise / Education**, and only if you run the script as
  **Administrator**. Windows Home ignores the policy key entirely -
  `--lockscreen` will just print a failure message and move on.
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
- The overlay currently only reads shortcuts sitting **directly on your
  Desktop folder** (not the shared "Public Desktop" or Start Menu). Easy
  to extend in `modules/shortcuts.py` if you want more sources.
- Closing the overlay window does **not** restore your icons/wallpaper
  automatically. Add a "restore" script if you want a clean undo button
  (good candidate for a v1.1 feature).

## Project layout

```
minimalistic_desktop/
  main.py                  entry point - wires everything together
  modules/
    wallpaper.py            black wallpaper generation + set
    theme.py                dark mode registry + explorer restart
    desktop_icons.py        toggle native icon visibility
    shortcuts.py            reads .lnk/folders from Desktop
    overlay.py              the CustomTkinter overlay window
    lockscreen.py           optional, admin + Pro/Enterprise only
  assets/                   generated black.png lives here
  requirements.txt
```

## Next up (v2, not built yet)

- Custom Start Menu launcher overlay (Win-key hook)
- Custom folder browser UI
- A "restore defaults" command
