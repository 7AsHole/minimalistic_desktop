# config.py
import os
import tomllib  # Python 3.11+; if older, use 'tomli' (pip install tomli)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.toml")

DEFAULT_CONFIG = {
    "hotkey": "Ctrl+S",
}

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()