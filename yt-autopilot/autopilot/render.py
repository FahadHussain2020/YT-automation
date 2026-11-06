"""ffmpeg render: shots -> segments -> video, narration + music mixed and
loudness-normalised, captions (SRT) and chapters from the timeline."""
import json
import random
import re
import subprocess
from pathlib import Path

from .config import ASSETS, section
from .store import Video

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".ogv", ".mpeg", ".mpg")


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True, timeout=1800)


def usable(path: Path | None) -> bool:
    """A broken download must never reach ffmpeg: a looped bad image hangs it."""
    if path is None or not path.exists():
        return False
    if path.suffix.lower() in VIDEO_EXT:
        try:
            return probe_duration(path) > 0
        except (subprocess.CalledProcessError, ValueError, KeyError):
            return False
    from .media.footage import usable_image

    return usable_image(path)


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"].get("duration", 0) or 0)


def segment(src: Path | None, dur: float, out: Path, w: int, h: int, fps: int, n: int) -> None:
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    enc = ["-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]
    if src is None:
        ff("-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}", "-t", f"{dur:.3f}", *enc, str(out))
    elif src.suffix.lower() in VIDEO_EXT:
        length = probe_duration(src)
        start = max(0.0, min(length * 0.2, length - dur)) if length > dur else 0.0
        loop = ["-stream_loop", "-1"] if length < dur else []
        ff(*loop, "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.3f}", "-vf", f"{cover},fps={fps}", *enc, str(out))
    else:
        frames = max(1, int(dur * fps))
        # gentle, varied movement; never the same slow zoom on every still
        zin = n % 2 == 0
        z = "min(zoom+0.0005,1.08)" if zin else "if(eq(on,0),1.08,max(zoom-0.0005,1.0))"
        x = ["iw/2-(iw/zoom/2)", "0", "iw-iw/zoom"][n % 3]
        vf = (f"{cover},scale={w * 2}:{h * 2},zoompan=z='{z}':d={frames}:x='{x}':y='ih/2-(ih/zoom/2)'"
              f":s={w}x{h}:fps={fps}")
        ff("-loop", "1", "-i", str(src), "-t", f"{dur:.3f}", "-vf", vf, *enc, str(out))


def layered_segment(bg: Path, overlay: Path, dur: float, offset: float, out: Path, w: int, h: int, fps: int) -> None:
    """An animated place (seamless loop) with the shot's characters on a transparent layer on top.
    The loop is entered at the shot's own time, so consecutive shots in one place move continuously."""
    length = probe_duration(bg)
    start = offset % length if length else 0.0
    enc = ["-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]
    ff("-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", str(bg), "-loop", "1", "-i", str(overlay),
       "-filter_complex", f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps}[b];"
       "[b][1:v]overlay=0:0:format=auto[v]", "-map", "[v]", "-t", f"{dur:.3f}", *enc, str(out))


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def captions(timeline: list[dict], max_chars: int = 42) -> str:
    """Splits each line into short caption chunks timed by word share."""
    cues = []
    for t in timeline:
        ws = t["text"].split()
        chunks, cur = [], []
        for w in ws:
            if cur and len(" ".join(cur + [w])) > max_chars:
                chunks.append(cur)
                cur = []
            cur.append(w)
        if cur:
            chunks.append(cur)
        total = sum(len(c) for c in chunks) or 1
        start = t["start"]
        for c in chunks:
            end = start + (t["end"] - t["start"]) * len(c) / total
            cues.append((start, end, " ".join(c)))
            start = end
    return "\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(cues, 1))


def ass_captions(srt_text: str, w: int, h: int) -> str:
    """Captions as ASS with the real frame size (libass misplaces SRT captions on a tall frame):
    big words, top centre, clear of the characters standing at the bottom."""
    def t(ts: str) -> str:
        hh, mm, rest = ts.split(":")
        sec, ms = rest.split(",")
        return f"{int(hh)}:{mm}:{sec}.{ms[:2]}"

    events = []
    for block in srt_text.strip().split("\n\n"):
        rows = block.splitlines()
        if len(rows) >= 3:
            a, b = rows[1].split(" --> ")
            events.append(f"Dialogue: 0,{t(a)},{t(b)},Kids,,0,0,0,,{' '.join(rows[2:])}")
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Kids,DejaVu Sans,{int(min(w, h) * (0.085 if h > w else 0.062))},&H00FFFFFF,&H00FFFFFF,&H00502832,"
            f"&H64000000,-1,0,0,0,100,100,0,0,1,{int(min(w, h) * 0.008)},2,8,60,60,{int(h * (0.09 if h > w else 0.04))},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            + "\n".join(events) + "\n")


def chapters(timeline: list[dict]) -> list[dict]:
    """YouTube needs: first at 0:00, at least 3, each at least 10 seconds."""
    out = []
    for t in timeline:
        if not out or t["section"] != out[-1]["title"]:
            if out and t["start"] - out[-1]["start"] < 10:
                continue
            out.append({"start": 0.0 if not out else t["start"], "title": t["section"]})
    return out if len(out) >= 3 else []


def chapter_text(chs: list[dict]) -> str:
    return "\n".join(f"{int(c['start'] // 60)}:{int(c['start'] % 60):02d} {c['title']}" for c in chs)


def pick_music(v: Video) -> Path | None:
    """Your own tracks in assets/music/ first; otherwise a free licensed one, credited."""
    own = sorted((ASSETS / "music").glob("*.mp3")) + sorted((ASSETS / "music").glob("*.wav"))
    if own:
        return random.choice(own)
    if not section("format").get("auto_music", True):
        return None
    from .media import music

    item = music.pick(v.id)
    if not item:
        return None
    items = [i for i in (v.read("licences.json") or []) if i.get("kind") != "audio"]
    items.append({k: item[k] for k in ("kind", "source", "title", "author", "licence", "licence_url", "page_url", "path")})
    v.write("licences.json", items)
    v.log(f"music: {item['title']} ({item['licence']}, {item['source']})")
    return Path(item["path"])


def mix_audio(narration: Path, total: float, out: Path, lufs: float, music_db: float, track: Path | None = None) -> None:
    if track:
        fc = (f"[1:a]volume={music_db}dB,afade=t=in:d=2,afade=t=out:st={max(total - 4, 0):.2f}:d=4[m];"
              f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        ff("-i", str(narration), "-stream_loop", "-1", "-i", str(track), "-filter_complex", fc, "-map", "[a]",
           "-t", f"{total:.3f}", "-ar", "48000", str(out.with_suffix(".pre.wav")))
    else:
        ff("-i", str(narration), "-ar", "48000", str(out.with_suffix(".pre.wav")))
    pre = out.with_suffix(".pre.wav")
    # two-pass loudnorm: measure, then apply with the measured values
    res = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af",
                          f"loudnorm=I={lufs}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True)
    m = json.loads(re.findall(r"\{[^{}]+\}", res.stderr)[-1])
    ff("-i", str(pre), "-af",
       f"loudnorm=I={lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
       f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
       "-ar", "48000", str(out))


def run(v: Video, plan: list[dict], timeline: list[dict], lang: str = "en") -> Path:
    fmt = {**section("format"), **{k: v.state[k] for k in ("resolution",) if v.state.get(k)}}
    w, h = fmt.get("resolution", [1920, 1080])
    vertical = h > w
    fps = fmt.get("fps", 30)
    segdir = v.path("segments")
    segdir.mkdir(exist_ok=True)
    narration = v.path(f"narration_{lang}.wav")
    total = probe_duration(narration)

    # times come from this language's timeline; shots are matched by line number,
    # so one visual plan serves every language version
    shots_by_line = {p["i"]: p["shots"] for p in plan}
    seg_files, last, n = [], None, 0
    for k, t in enumerate(timeline):
        start = t["start"]
        end = timeline[k + 1]["start"] if k + 1 < len(timeline) else total  # include the gap after each line
        layered = [s for s in shots_by_line.get(t["i"], []) if s.get("bg_video") and Path(s["bg_video"]).exists()
                   and Path(s.get("overlay", "")).exists()]
        if layered:  # kids mode: moving background, characters on top
            out = segdir / f"seg_{n:04d}.mp4"
            layered_segment(Path(layered[0]["bg_video"]), Path(layered[0]["overlay"]), end - start, start, out, w, h, fps)
            seg_files.append(out)
            last, n = Path(layered[0]["path"]), n + 1
            continue
        shots = [p for p in (Path(s["path"]) for s in shots_by_line.get(t["i"], [])) if usable(p)] or [last]
        each = (end - start) / len(shots)
        for src in shots:
            out = segdir / f"seg_{n:04d}.mp4"
            segment(src, each, out, w, h, fps, n)
            seg_files.append(out)
            last, n = src, n + 1
    listing = segdir / "list.txt"
    listing.write_text("".join(f"file '{f.name}'\n" for f in seg_files))
    silent = v.path("video_silent.mp4")
    ff("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent))

    audio = v.path(f"audio_{lang}.wav")
    if v.state.get("melody"):  # our own arrangement of a public-domain tune, phrase by phrase under the words
        from .media import melody

        track = melody.render(timeline, total, v.state["melody"], v.path("music_backing.wav"),
                              v.state.get("timbre", "musicbox"))
        items = [i for i in (v.read("licences.json") or []) if i.get("kind") != "audio"]
        v.write("licences.json", items + [melody.licence(v.state["melody"], v.state.get("timbre", "musicbox"), track)])
    else:
        track = pick_music(v)
    mix_audio(narration, total, audio, v.state.get("loudness_lufs", fmt.get("loudness_lufs", -14)),
              v.state.get("music_db", fmt.get("music_volume_db", -24)), track)

    srt = v.path(f"captions_{lang}.srt")
    srt.write_text(captions(timeline, max_chars=18 if vertical else 42), encoding="utf-8")
    chs = chapters(timeline)
    v.write("chapters.json", chs)

    final = v.path(f"final_{lang}.mp4")
    from . import kids

    if vertical or kids.enabled():  # top of the frame: kids-mode characters stand at the bottom
        burn = v.path(f"captions_{lang}.ass")
        burn.write_text(ass_captions(srt.read_text(encoding="utf-8"), w, h), encoding="utf-8")
        sub = f"subtitles={burn.name}"
    else:
        sub = f"subtitles={srt.name}:force_style='FontName=DejaVu Sans,FontSize=17,Bold=1,Outline=2,Shadow=1,MarginV=28'"
    vf = ["-vf", sub] if fmt.get("burn_captions") else []
    vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if vf else ["-c:v", "copy"]
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", silent.name, "-i", audio.name, *vf,
                    "-map", "0:v", "-map", "1:a", *vcodec, "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", final.name], check=True, cwd=v.dir)
    v.log(f"rendered {final.name} ({total:.0f}s, {len(seg_files)} shots, {len(chs)} chapters)")
    return final
