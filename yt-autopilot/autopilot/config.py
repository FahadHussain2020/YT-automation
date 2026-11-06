"""Settings: config/channel.yaml for the channel, .env for secrets."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VIDEOS = DATA / "videos"
CACHE = DATA / "cache"
ASSETS = ROOT / "assets"


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


load_env()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_path(name: str, default: str = "") -> Path:
    p = Path(env(name, default))
    return p if p.is_absolute() else ROOT / p


@lru_cache(maxsize=1)
def channel() -> dict:
    path = Path(os.environ.get("YT_CHANNEL_CONFIG", ROOT / "config" / "channel.yaml"))
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def section(name: str) -> dict:
    return channel().get(name, {}) or {}
