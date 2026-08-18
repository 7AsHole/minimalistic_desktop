import json
import os

PINS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pins.json")


def load_pins() -> set[str]:
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
    pins = load_pins()
    if path in pins:
        pins.discard(path)
    else:
        pins.add(path)
    save_pins(pins)
    return pins
