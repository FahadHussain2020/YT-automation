"""Background music when assets/music/ is empty: a CC0 or CC BY track from Openverse
(Freesound, Wikimedia and others), credited in the description when the licence asks."""
import json
import random
from pathlib import Path

import requests

from ..config import CACHE, section
from . import footage, licences

LICENCES = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY"}


def find(query: str, min_seconds: int = 60) -> list[dict]:
    r = requests.get("https://api.openverse.org/v1/audio/", headers=footage.UA, timeout=30, params={
        "q": query, "license_type": "commercial,modification", "page_size": 20, "mature": "false"})
    r.raise_for_status()
    out = []
    for d in r.json().get("results", []):
        lic = LICENCES.get(d.get("license", ""))
        if not lic or (d.get("duration") or 0) < min_seconds * 1000:
            continue
        if d.get("license_version") and lic == "CC BY":
            lic += f" {d['license_version']}"
        out.append({"kind": "audio", "url": d["url"], "page_url": d.get("foreign_landing_url", ""),
                    "title": d.get("title") or "Music", "author": d.get("creator") or "", "licence": lic,
                    "licence_url": d.get("license_url", ""), "source": f"Openverse ({d.get('source', '')})"})
    return out


def pick(seed: str) -> dict | None:
    """Returns a licence record with "path" set, or None when nothing could be fetched."""
    fmt = section("format")
    queries = fmt.get("music_query", "ambient cinematic background")
    artist = fmt.get("music_artist", "").lower()  # optional: only this composer's tracks
    tracks = []
    for query in [queries] if isinstance(queries, str) else queries:
        try:
            tracks += [t for t in find(query) if licences.allowed(t["licence"]) and artist in t["author"].lower()]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  music search failed for {query!r}: {e}")
    random.Random(seed).shuffle(tracks)
    for t in tracks[:4]:
        try:
            path: Path = footage.download(t, CACHE / "music")
        except Exception as e:
            print(f"  music download failed {t['url']}: {e}")
            continue
        path.with_suffix(".json").write_text(json.dumps(t, ensure_ascii=False))  # licence, for offline reuse
        return {**t, "path": str(path)}
    # search or downloads failed: a track fetched before, with its licence record
    cached = []
    for meta in sorted((CACHE / "music").glob("*.json")):
        t = json.loads(meta.read_text())
        audio = next((p for p in meta.parent.glob(meta.stem + ".*") if p.suffix != ".json"), None)
        if audio and licences.allowed(t.get("licence", "")) and artist in t.get("author", "").lower() and \
                (not isinstance(queries, list) or any(q.lower() in t.get("title", "").lower() for q in queries)):
            cached.append({**t, "path": str(audio)})
    random.Random(seed).shuffle(cached)
    return cached[0] if cached else None
