"""Every video lives in its own folder under data/videos/<id>/ with a state.json.

A video moves through these stages, in order. Each stage only picks up videos
that the previous stage finished, so you can stop and resume at any point.
"""
import json
import re
import time
from pathlib import Path

from .config import DATA, VIDEOS

STAGES = ["idea", "scripted", "produced", "reviewed", "approved", "published"]


def slugify(text: str, max_len: int = 50) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "video"


class Video:
    def __init__(self, folder: Path):
        self.dir = folder
        self.state_file = folder / "state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    @property
    def id(self) -> str:
        return self.dir.name

    @property
    def stage(self) -> str:
        return self.state.get("stage", "idea")

    def path(self, name: str) -> Path:
        return self.dir / name

    def read(self, name: str, default=None):
        p = self.path(name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else p.read_text(encoding="utf-8")

    def write(self, name: str, content) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".json":
            p.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            p.write_text(content, encoding="utf-8")
        return p

    def set_stage(self, stage: str, **extra) -> None:
        assert stage in STAGES, stage
        self.state["stage"] = stage
        self.state.setdefault("history", []).append({"stage": stage, "at": int(time.time())})
        self.state.update(extra)
        self.save()

    def update(self, **extra) -> None:
        self.state.update(extra)
        self.save()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def log(self, msg: str) -> None:
        with open(self.path("log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        print(f"[{self.id}] {msg}")


def create(topic: str, **extra) -> Video:
    VIDEOS.mkdir(parents=True, exist_ok=True)
    vid = f"{time.strftime('%Y%m%d')}-{slugify(topic)}"
    n, folder = 1, VIDEOS / vid
    while folder.exists():
        n += 1
        folder = VIDEOS / f"{vid}-{n}"
    v = Video(folder)
    v.state = {"topic": topic, "created": int(time.time()), **extra}
    v.set_stage("idea")
    return v


def all_videos() -> list[Video]:
    if not VIDEOS.exists():
        return []
    return [Video(p) for p in sorted(VIDEOS.iterdir()) if (p / "state.json").exists()]


def at_stage(stage: str) -> list[Video]:
    return [v for v in all_videos() if v.stage == stage]


def get(video_id: str) -> Video:
    folder = VIDEOS / video_id
    if not (folder / "state.json").exists():
        raise SystemExit(f"No video called {video_id}. Run: python run.py status")
    return Video(folder)


def lessons_file() -> Path:
    return DATA / "lessons.json"


def load_lessons() -> list[dict]:
    p = lessons_file()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
