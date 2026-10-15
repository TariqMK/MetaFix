"""Runtime configuration and shared desktop session state."""
import json
import sys
from pathlib import Path

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CONFIG = APP_DIR / "data" / "config.json"
state = {"files": [], "last_batch": [], "config": {}}

def load_config():
    if CONFIG.exists():
        try:
            with CONFIG.open("r", encoding="utf-8") as config_file:
                return json.load(config_file)
        except (OSError, ValueError):
            pass
    return {}


def save_config(cfg):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG.open("w", encoding="utf-8") as config_file:
        json.dump(cfg, config_file, indent=2)


state["config"] = load_config()
