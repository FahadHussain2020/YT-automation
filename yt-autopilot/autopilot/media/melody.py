"""Our own backing music: traditional public-domain melodies played on a synthesised music
box or xylophone, rendered locally (no samples, nothing to license).

The voice can't sing, so the song is laid out around the narration instead: every spoken
line gets one melodic phrase, stretched to fit that line, so the words land on the tune
like a sing-along. A soft chord sits under each phrase.
"""
import math
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000

# (midi note, beats). Middle C = 60. All traditional melodies in the public domain.
MELODIES = {
    "twinkle": {"title": "Twinkle Twinkle Little Star", "phrases": [
        [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2)],
        [(65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)],
        [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)],
        [(67, 1), (67, 1), (65, 1), (65, 1), (64, 1), (64, 1), (62, 2)],
    ]},
    "rain": {"title": "Rain Rain Go Away", "phrases": [
        [(67, 1), (64, 1), (67, .5), (67, .5), (64, 1)],
        [(67, .5), (67, .5), (64, .5), (67, .5), (67, .5), (64, .5), (64, 1)],
        [(69, .5), (69, .5), (67, .5), (67, .5), (64, .5), (67, .5), (64, 1)],
    ]},
    "ducks": {"title": "Five Little Ducks", "phrases": [
        [(67, .5), (64, .5), (64, .5), (64, .5), (62, .5), (60, .5), (62, .5), (64, 1.5)],
        [(67, .5), (67, .5), (64, .5), (67, .5), (69, .5), (67, .5), (64, 1.5)],
        [(65, .5), (65, .5), (64, .5), (62, .5), (67, .5), (67, .5), (67, .5), (67, .5)],
        [(64, .5), (62, .5), (60, .5), (62, .5), (64, .5), (62, .5), (60, 1.5)],
    ]},
    "mulberry": {"title": "Here We Go Round the Mulberry Bush", "phrases": [
        [(60, .75), (60, .25), (60, .5), (64, .5), (67, .75), (67, .25), (64, .5), (60, .5)],
        [(62, .75), (62, .25), (62, .5), (59, .5), (55, .75), (55, .25), (59, .5), (62, .5)],
        [(60, .75), (60, .25), (60, .5), (64, .5), (67, .75), (67, .25), (64, .5), (60, .5)],
        [(62, .5), (67, .5), (62, .5), (59, .5), (60, 1.5)],
    ]},
    "brahms": {"title": "Brahms' Lullaby (Wiegenlied)", "phrases": [
        [(64, .5), (64, .5), (67, 1.5)],
        [(64, .5), (64, .5), (67, 1.5)],
        [(64, .5), (67, .5), (72, 1), (71, 1), (69, .5), (69, .5), (67, 1)],
        [(62, .5), (64, .5), (65, 1), (62, .5), (64, .5), (65, 1.5)],
        [(62, .5), (65, .5), (71, .5), (69, .5), (67, 1), (71, 1), (72, 2)],
    ]},
}


def freq(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def tone(note: int, dur: float, timbre: str) -> np.ndarray:
    """One note. Music box: bright inharmonic partials, quick decay. Xylophone: woody, short."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    f = freq(note)
    partials = {"musicbox": [(1, 1.0, 2.2), (2.76, 0.35, 5.0), (5.4, 0.12, 9.0)],
                "xylophone": [(1, 1.0, 6.0), (3.93, 0.3, 14.0), (9.5, 0.08, 25.0)]}[timbre]
    out = sum(a * np.sin(2 * math.pi * f * m * t) * np.exp(-d * t) for m, a, d in partials)
    attack = np.minimum(1, t / 0.003)
    return (out * attack).astype("float32")


def chord(root: int, dur: float) -> np.ndarray:
    """Soft sustained triad (sine pad) under a phrase."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    env = np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.6).clip(0, 1)
    notes = [root - 12, root - 12 + 4, root - 12 + 7]
    return (sum(np.sin(2 * math.pi * freq(x) * t) for x in notes) / 3 * env).astype("float32")


def chord_root(phrase: list) -> int:
    last = phrase[-1][0] % 12
    return {2: 55, 7: 55, 11: 55, 5: 53, 9: 53}.get(last, 60)  # G, F or C


def render(timeline: list[dict], total: float, name: str, out: Path, timbre: str = "musicbox",
           fill: float = 0.92) -> Path:
    """Backing track as long as the narration: phrase k under timeline line k."""
    phrases = MELODIES[name]["phrases"]
    mix = np.zeros(int((total + 1) * SR), dtype="float32")
    for k, t in enumerate(timeline):
        start = t["start"]
        end = timeline[k + 1]["start"] if k + 1 < len(timeline) else total
        span = max(0.4, end - start)
        phrase = phrases[k % len(phrases)]
        beats = sum(b for _, b in phrase)
        beat = span * fill / beats
        pos = start
        for note, b in phrase:
            dur = b * beat
            sound = tone(note, min(dur * 1.6, 2.5), timbre) * 0.5  # let notes ring a little
            i = int(pos * SR)
            mix[i:i + len(sound)] += sound[:len(mix) - i]
            pos += dur
        pad = chord(chord_root(phrase), span) * 0.12
        i = int(start * SR)
        mix[i:i + len(pad)] += pad[:len(mix) - i]
    peak = float(np.abs(mix).max()) or 1.0
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, (mix / peak * 0.8)[:int(total * SR)], SR)
    return out


def licence(name: str, timbre: str, path: Path) -> dict:
    return {"kind": "audio", "source": "local", "title": f"{MELODIES[name]['title']} (traditional melody, our own "
            f"{timbre} arrangement)", "author": "channel", "licence": "Own work by channel", "licence_url": "",
            "page_url": "", "path": str(path)}
