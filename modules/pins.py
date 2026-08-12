"""
Tracks which apps you've pinned to the top of the overlay's list.

Pins are keyed by shortcut path (stable per .lnk/.url file) and stored in
pins.json next to main.py, so they survive restarts. This mirrors state.py's
pattern of a small JSON snapshot on disk.
"""
import json
import os

PINS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pins.json")


def load_pins() -> set[str]:
    """Returns the set of pinned shortcut paths. Empty set if nothing pinned yet."""
    if not os.path.exists(PINS_PATH):
        return set()
    try:
        with open(PINS_PATH) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_pins(pins: set[str]) -> None:
    with open(PINS_PATH, "w") as f:
        json.dump(sorted(pins), f, indent=2)


def toggle_pin(path: str) -> set[str]:
    """Flips the pinned state of a single shortcut and persists the result."""
    pins = load_pins()
    if path in pins:
        pins.discard(path)
    else:
        pins.add(path)
    save_pins(pins)
    return pins
