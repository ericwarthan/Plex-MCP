import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "plex-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"
CHANGES_LOG = CONFIG_DIR / "changes.log"

DEFAULT_CONFIG: dict = {
    "plex_host": "192.168.1.x",
    "plex_port": 32400,
    "token": None,
}


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE) as f:
        return {**DEFAULT_CONFIG, **json.load(f)}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)


def get_plex_url(config: dict) -> str:
    if config.get("plex_url"):
        return config["plex_url"]
    return f"http://{config['plex_host']}:{config['plex_port']}"
