"""Narration, one audio file per script line, then joined into narration.wav.

Voices:
  kokoro      English, free, runs locally (kokoro-onnx).
  elevenlabs  Any language incl. Urdu (paid API).
  own         Your own recordings. Put recordings/line_007.wav etc. in the video folder.

voice_mode in channel.yaml decides which lines must be your own voice:
  ai          none
  commentary  every line of kind opinion/commentary
  own         every line
The stage writes recordings/TO_RECORD.md listing exactly what to record.
"""
import subprocess
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from .checks import lines as script_lines
from .config import env, env_path, section
from .llm import WaitingForHuman
from .store import Video

SR = 24000
GAP = 0.28  # seconds of silence between lines


def _kokoro():
    from kokoro_onnx import Kokoro

    if not hasattr(_kokoro, "model"):
        _kokoro.model = Kokoro(str(env_path("KOKORO_MODEL", "models/kokoro-v1.0.onnx")),
                               str(env_path("KOKORO_VOICES", "models/voices-v1.0.bin")))
    return _kokoro.model


def kokoro_tts(text: str, voice: str, speed: float, out: Path) -> None:
    samples, sr = _kokoro().create(text, voice=voice, speed=speed, lang="en-us")
    sf.write(out, samples, sr)


def elevenlabs_tts(text: str, voice_id: str, out: Path) -> None:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
        json={"text": text, "model_id": env("ELEVENLABS_MODEL", "eleven_multilingual_v2")},
        timeout=180,
    )
    r.raise_for_status()
    mp3 = out.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    to_wav(mp3, out)


def to_wav(src: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(SR), str(out)], check=True)


def load_mono(path: Path) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    data = data.mean(axis=1)
    if sr != SR:
        tmp = path.with_name(path.stem + f".{SR}.wav")
        to_wav(path, tmp)
        data, _ = sf.read(tmp, dtype="float32")
    return data


def needs_own_voice(kind: str, mode: str) -> bool:
    return mode == "own" or (mode == "commentary" and kind in ("opinion", "commentary"))


def run(v: Video, lang: str = "en") -> list[dict]:
    script = v.read("script.json" if lang == "en" else f"script_{lang}.json")
    lcfg = section("languages").get(lang, {})
    mode = section("originality").get("voice_mode", "ai")
    voice_dir, rec_dir = v.path(f"voice_{lang}"), v.path("recordings")
    voice_dir.mkdir(exist_ok=True)

    todo, items = [], list(script_lines(script))
    for i, (sec, line) in enumerate(items):
        if needs_own_voice(line.get("kind", "fact"), mode) and not (rec_dir / f"line_{i:03d}.wav").exists():
            todo.append(f"- line_{i:03d}.wav: {line['text']}")
    if todo:
        rec_dir.mkdir(exist_ok=True)
        (rec_dir / "TO_RECORD.md").write_text(
            "# Record these lines in your own voice\nSave each as a WAV file in this folder with the name shown.\n"
            "Quiet room, phone or USB mic is fine. Speak naturally; you can rephrase a little.\n\n" + "\n".join(todo))
        raise WaitingForHuman(f"{len(todo)} line(s) need your voice: see {rec_dir / 'TO_RECORD.md'}")

    timeline, chunks, t = [], [], 0.0
    gap = np.zeros(int(SR * GAP), dtype="float32")
    for i, (sec, line) in enumerate(items):
        own = rec_dir / f"line_{i:03d}.wav"
        out = voice_dir / f"line_{i:03d}.wav"
        if own.exists() and needs_own_voice(line.get("kind", "fact"), mode):
            to_wav(own, out)
            voice = "own"
        elif not out.exists():
            if lcfg.get("voice") == "elevenlabs":
                elevenlabs_tts(line["text"], env(f"ELEVENLABS_VOICE_ID_{lang.upper()}"), out)
            else:
                kokoro_tts(line["text"], lcfg.get("kokoro_voice", "am_michael"),
                           v.state.get("voice_speed", lcfg.get("speed", 1.0)), out)  # lullabies: slower
            voice = lcfg.get("voice", "kokoro")
        else:
            voice = lcfg.get("voice", "kokoro")
        audio = load_mono(out)
        dur = len(audio) / SR
        timeline.append({"i": i, "section": sec["heading"], "text": line["text"], "kind": line.get("kind", "fact"),
                         "shot": line.get("shot", ""), "search": line.get("search", ""), "voice": voice,
                         "start": round(t, 3), "end": round(t + dur, 3)})
        # kids mode: a pause after a question gives the child time to answer
        wait = np.zeros(int(SR * min(max(float(line.get("pause") or 0), 0), 3)), dtype="float32")
        chunks += [audio, gap, wait]
        t += dur + GAP + len(wait) / SR
    sf.write(v.path(f"narration_{lang}.wav"), np.concatenate(chunks), SR)
    v.write(f"timeline_{lang}.json", timeline)
    own_share = sum(1 for x in timeline if x["voice"] == "own") / max(len(timeline), 1)
    v.update(own_voice_share=round(own_share, 3))
    v.log(f"narration {lang}: {t:.0f}s, {own_share:.0%} your own voice")
    return timeline
