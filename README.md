# Minimalistic Desktop

A Python + CustomTkinter overlay application for Windows that transforms your desktop into a minimal, text-only environment with a black wallpaper, dark mode, live clock/calendar, and keyboard-friendly application shortcuts.

## Overview

This application creates a distraction-free desktop experience by:

- **Text-only shortcuts** - Replace desktop icons with a searchable, text-based app launcher
- **Black wallpaper** - Minimal, clean visual foundation
- **Live clock & calendar** - Always visible time and date on the overlay
- **Dark mode** - System-wide dark theme for taskbar, Start Menu, and compatible apps
- **Keyboard navigation** - Quick access to apps via keyboard shortcuts and search

## How It Works

Windows doesn't allow external applications to directly modify Explorer's rendering (icons, taskbar, Start Menu) without DLL injection, which is fragile and breaks on Windows updates. Instead of attempting to modify Explorer, this app:

- **Hides the real desktop icons** using Windows' built-in toggle
- **Draws a fullscreen overlay window** behind all other app windows, displaying text shortcuts, clock, and calendar
- **Leaves the taskbar intact** (icons remain colored - see "Known limitations" for why full monochrome isn't included)

This approach is **non-destructive and fully reversible** - Explorer.exe itself is never modified. Only your wallpaper, a theme registry key, and the icon-visibility toggle are changed (all things Windows Settings can undo).

## Installation & Setup

### Prerequisites

- Python 3.8 or higher
- Windows 10 or Windows 11
- [Explorer Patcher](https://github.com/valinet/ExplorerPatcher/releases) (almost a must for proper taskbar window positioning)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the Application

```bash
python main.py
```

The app registers itself to start automatically at Windows sign-in for the current user.

## Usage & Controls

### Launch Options

When running the app, you can pass optional flags to customize behavior:

| Flag | Description |
|------|-------------|
| `--restore` | Revert to your previous desktop state without launching the app |

**Example:**
```bash
python main.py --keep-icons --show-start-search
```

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Alt + S** | Open the app search/filter dialog |
| **Ctrl + M** | Mute/unmute microphone |
| **Right-click app** | Pin or unpin app to the top of the list |
| **Letter key** (when search is closed) | Jump to apps starting with that letter; filter clears after ~2 seconds of inactivity |

### Overlay Features

- **App List** - Pinned apps float to the top (separated by a divider) while keeping the list as one scrollable view
- **Auto-scroll reset** - If you leave the list scrolled down for 10 seconds, it automatically snaps back to the top
- **Tray icon** - Right-click the system tray icon (usually in the hidden icons area under the `^` arrow) and select **"Quit & Restore"** to cleanly exit

## Restoring Your Original Desktop

The app automatically creates a snapshot of your wallpaper and theme settings in `state.json` (located next to `main.py`) before making any changes. To return to your original desktop setup:

### Option 1: Clean Exit from Tray Icon (Recommended)
1. Right-click the app's icon in the system tray's **hidden icons area** (click the `^` arrow next to the clock)
2. Select **"Quit & Restore"**
3. The app will revert your wallpaper, theme, and icon visibility, then close

### Option 2: Terminal Exit
- Press **Ctrl+C** in the terminal where the app is running
- This triggers a restore before the process exits

### Option 3: Manual Restore After Crash
If the app crashes or is force-closed via Task Manager, restoration doesn't happen automatically, but your `state.json` snapshot is preserved. To restore:

```bash
python main.py --restore
```

This reverts your settings from the saved snapshot and exits.

### Notes
- Restoring is safe to run multiple times - if there's no `state.json`, it informs you and exits
- If `pystray` isn't installed, the tray icon won't appear but you can still close the terminal or kill the process; the rest of the app functions normally

## Features Breakdown

### 1. Black Wallpaper
- Generates a black PNG and sets it via `SystemParametersInfoW`
- No admin privileges required

### 2. Text-Only Application List
- Real desktop icons are hidden; the overlay displays Start Menu shortcuts as clickable text
- Search with **Ctrl+S** to filter apps by name
- Quick-jump to apps by pressing a letter/number key (when search is closed)
- Pin/unpin apps via right-click to keep frequently-used apps at the top

### 3. Live Clock & Calendar
- Real-time display on the overlay
- Updates every second

### 4. Dark Mode
- Flips `AppsUseLightTheme` and `SystemUsesLightTheme` registry keys
- Darkens taskbar, Start Menu chrome, and compatible apps
- This is a practical alternative to monochrome taskbar icons (see limitations below)

### 5. Taskbar Search Hiding
- Hidden by default; passes the setting through to automatic startup
- Restores the exact previous setting on exit
- Cannot hide the search field inside the opened Start Menu itself

### 6. System Tray Icon
- Small icon in the notification area (often tucked under the hidden icons flyout on first run)
- Right-click for "Quit & Restore" option

## Known Limitations

Be aware of these limitations before adopting this app:

### Monochrome Taskbar Icons
Taskbar icons are rendered by Explorer.exe from each app's own resources. Recoloring them system-wide would require injecting code into Explorer.exe, which is unstable and can trigger antivirus warnings. Dark mode (Feature 4) achieves most of the visual effect without the risk.

### Desktop Icon Visibility Toggle
Icon hiding works via a Windows toggle rather than an explicit on/off switch. If you run the app twice without restarting, icons will flip back on. The current version doesn't persist this state across runs, but it's a good candidate for a future improvement.

### Tray Icon Placement
New tray icons typically start collapsed in the hidden-icons flyout rather than pinned on the taskbar. This is standard Windows behavior, not specific to this app.

### Multi-Monitor Support
Multi-monitor configurations haven't been fully tested. For optimal window positioning across multiple displays, consider using [Explorer Patcher](https://github.com/valinet/ExplorerPatcher/releases).

### Keyboard Bindings
Keyboard shortcuts are currently hardcoded. If you'd like to customize them, you'll need to edit `main.py` directly.

## Project Structure

```
minimalistic_desktop/
├── main.py                 # Entry point - orchestrates all components
├── modules/
│   ├── wallpaper.py        # Black wallpaper generation and setup
│   ├── theme.py            # Dark mode registry changes and Explorer restart
│   ├── desktop_icons.py    # Toggle native icon visibility
│   ├── shortcuts.py        # Read Start Menu application shortcuts
│   ├── overlay.py          # CustomTkinter overlay window UI
│   ├── pins.py             # Persist pinned apps to top of list
│   ├── tray.py             # System tray icon with quit/restore menu
│   └── startup.py          # Register app for Windows sign-in
├── assets/                 # Generated black.png wallpaper
├── requirements.txt        # Python package dependencies
├── state.json              # Backup of original wallpaper and theme (auto-created)
└── pins.json               # Pinned apps list (auto-created)
```

## Troubleshooting

### Windows Positioning Issues on Multi-Monitor Setups
If the overlay window appears on the wrong monitor or doesn't position correctly:
1. Install [Explorer Patcher](https://github.com/valinet/ExplorerPatcher/releases)
2. Restart your computer
3. Run the app again

### Missing Tray Icon
If the tray icon doesn't appear and you see a warning about `pystray`:
- The app still functions, but you'll need to close the terminal or kill the process to quit
- To restore your desktop, open a terminal and run: `python main.py --restore`

### Icons Not Hiding
- Try restarting your computer. Icon visibility is a toggle, so running the app twice can flip the state.
- Use `python main.py --keep-icons` if you want to skip the icon-hiding step

### Tray Icon Hidden
New tray icons often appear in the hidden-icons flyout (click the `^` arrow next to the system clock) rather than on the main taskbar. Drag it out if you want it always visible.

## Roadmap (Future Features)

- Custom Start Menu launcher overlay (Win-key hook)
- Custom folder browser UI
- Persistent desktop icon state across runs
- Customizable keyboard bindings UI
