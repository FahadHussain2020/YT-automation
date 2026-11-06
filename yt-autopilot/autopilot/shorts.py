"""Stage 6: cut vertical Shorts from a published long video.

Picks self-contained moments (the hook, then the sections with the most concrete
facts), renders 1080x1920 with the original framed over a blurred background
and captions burned in, and uploads them private, scheduled after the main video,
linking back to it.
"""
import datetime as dt
import re

from . import publish, render
from .config import section
from .store import Video


def pick_moments(timeline: list[dict], count: int, max_s: float) -> list[tuple[float, float, str]]:
    sections: dict[str, list[dict]] = {}
    for t in timeline:
        sections.setdefault(t["section"], []).append(t)
    scored = []
    for name, lines in sections.items():
        facts = sum(len(re.findall(r"\b\d{2,4}\b", l["text"])) + (l["kind"] == "fact") for l in lines)
        scored.append((facts, name, lines))
    first = list(sections)[0] if sections else None
    scored.sort(key=lambda s: (s[1] == first, s[0]), reverse=True)  # hook first, then densest
    out = []
    for _, name, lines in scored[:count]:
        start, end = lines[0]["start"], lines[0]["start"]
        for l in lines:
            if l["end"] - start > max_s:
                break
            end = l["end"]
        if end - start >= 15:
            out.append((start, end + 0.3, name))
    return out


def cut(v: Video, start: float, end: float, n: int, lang: str = "en"):
    timeline = v.read(f"timeline_{lang}.json")
    sub = [{**t, "start": max(t["start"], start) - start, "end": min(t["end"], end) - start}
           for t in timeline if t["end"] > start and t["start"] < end]
    srt = v.path(f"shorts/short_{n}.srt")
    srt.parent.mkdir(exist_ok=True)
    srt.write_text(render.captions(sub, max_chars=24), encoding="utf-8")
    out = v.path(f"shorts/short_{n}.mp4")
    fc = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];"
          "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
          f"subtitles={srt.name}:force_style='FontSize=14,Alignment=2,MarginV=180,Outline=2'[v]")
    import subprocess

    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                    "-i", f"../final_{lang}.mp4", "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
                    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "160k",
                    out.name], check=True, cwd=srt.parent)
    return out


def run(v: Video, upload: bool = True) -> list[str]:
    cfg = section("shorts")
    timeline = v.read("timeline_en.json") or []
    moments = pick_moments(timeline, cfg.get("per_video", 2), cfg.get("max_seconds", 58))
    ids = []
    main_at = dt.datetime.fromisoformat(v.state["publish_at"]) if v.state.get("publish_at") else None
    for n, (start, end, name) in enumerate(moments, 1):
        path = cut(v, start, end, n)
        v.log(f"short {n}: {name} ({end - start:.0f}s)")
        if upload and v.state.get("youtube_id"):
            at = (main_at or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(days=n)
            desc = f"Full story: https://youtu.be/{v.state['youtube_id']}\n\n#Shorts"
            ids.append(publish.upload(v, file_name=f"shorts/{path.name}", title=f"{name}: {v.state.get('title', v.state['topic'])}"[:90] + " #Shorts",
                                      description=desc, publish_at=at))
    if ids:
        v.update(shorts=ids)
    return ids
