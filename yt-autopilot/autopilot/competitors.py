"""Competitor research: learn what works on other kids channels, never copy it.

    python run.py competitors @ChuChuTV @LittleBabyBum --hours 72

Writes data/competitors/<channel>/<date>/{dataset.json, videos.csv, thumbs/, report.md, strategy.md}
and data/competitors/insights.json (latest strategy per channel, read by scout / make).
Data comes from the YouTube Data API when YOUTUBE_API_KEY is set, otherwise yt-dlp.
Titles, tags and transcripts go to the writer as untrusted data, and the top videos become
reference_videos so the copy check fails any script that echoes them.
"""
import csv
import datetime as dt
import json
import re
import shutil
import statistics
import subprocess
from collections import Counter
from pathlib import Path

import requests

from .config import DATA, env

OUT = DATA / "competitors"
TRANSCRIPTS = OUT / "transcripts"
SHORT_MAX_SECONDS = 180  # Shorts can be up to 3 minutes
LONG_SHORTS_SINCE = dt.datetime(2024, 10, 15, tzinfo=dt.timezone.utc)  # before this, Shorts were 60 s max
STOPWORDS = set("""a an and the of for to in on with is are be by at from your you our my me it this that
 kids kid children child baby babies nursery rhymes rhyme song songs video videos new full episode
 compilation more minutes min hour hours learning learn tv official""".split())


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_channel(ref: str) -> dict:
    """@handle, a youtube.com URL, or a UC... id -> {"handle": ...} or {"id": ...}."""
    ref = ref.strip()
    m = re.search(r"(UC[\w-]{22})", ref)
    if m:
        return {"id": m.group(1)}
    m = re.search(r"youtube\.com/(@[\w.\-]+)", ref) or re.match(r"^(@[\w.\-]+)$", ref)
    if m:
        return {"handle": m.group(1)}
    m = re.search(r"youtube\.com/(?:c|user)/([\w.\-]+)", ref)
    if m:
        return {"legacy": m.group(1)}
    if re.match(r"^[\w.\-]+$", ref):
        return {"handle": "@" + ref}
    raise ValueError(f"Not a channel: {ref!r}. Use @handle, a channel URL or a UC... id.")


def iso_duration(s: str) -> int:
    """PT1H2M3S -> 3723 seconds."""
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:40] or "channel"


class ApiSource:
    name = "youtube-api"

    def __init__(self, key: str):
        self.key = key

    def _get(self, endpoint: str, **params) -> dict:
        r = requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}",
                         params={**params, "key": self.key}, timeout=30)
        r.raise_for_status()
        return r.json()

    def channel(self, ref: dict) -> dict:
        params = {"id": ref["id"]} if "id" in ref else {"forHandle": ref.get("handle")} if "handle" in ref \
            else {"forUsername": ref["legacy"]}
        items = self._get("channels", part="snippet,statistics,contentDetails", **params).get("items", [])
        if not items:
            raise RuntimeError(f"Channel not found: {ref}")
        c = items[0]
        st = c.get("statistics", {})
        return {"id": c["id"], "title": c["snippet"]["title"], "handle": c["snippet"].get("customUrl", ""),
                "description": c["snippet"].get("description", "")[:1500], "country": c["snippet"].get("country", ""),
                "created": c["snippet"].get("publishedAt", ""), "subs": int(st.get("subscriberCount", 0) or 0),
                "views": int(st.get("viewCount", 0) or 0), "video_count": int(st.get("videoCount", 0) or 0),
                "uploads_playlist": c["contentDetails"]["relatedPlaylists"]["uploads"]}

    def recent_ids(self, ch: dict, max_videos: int) -> list[str]:
        ids, token = [], None
        while len(ids) < max_videos:
            res = self._get("playlistItems", part="contentDetails", playlistId=ch["uploads_playlist"],
                            maxResults=50, **({"pageToken": token} if token else {}))
            ids += [i["contentDetails"]["videoId"] for i in res.get("items", [])]
            token = res.get("nextPageToken")
            if not token:
                break
        return ids[:max_videos]

    def top_ids(self, ch: dict, n: int) -> list[str]:
        """All-time most viewed. search.list costs 100 units, well inside the free 10,000/day."""
        res = self._get("search", part="id", channelId=ch["id"], order="viewCount", type="video", maxResults=min(n, 50))
        return [i["id"]["videoId"] for i in res.get("items", [])]

    def details(self, ids: list[str]) -> list[dict]:
        out = []
        for n in range(0, len(ids), 50):
            res = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[n:n + 50]))
            for i in res.get("items", []):
                sn, st = i["snippet"], i.get("statistics", {})
                thumbs = sn.get("thumbnails", {})
                best = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium", "default") if k in thumbs), "")
                out.append({
                    "id": i["id"], "title": sn["title"], "published": sn["publishedAt"],
                    "description": sn.get("description", "")[:1500], "tags": sn.get("tags", []),
                    "duration": iso_duration(i["contentDetails"].get("duration", "")),
                    "views": int(st.get("viewCount", 0) or 0), "likes": int(st.get("likeCount", 0) or 0),
                    "comments": int(st.get("commentCount", 0) or 0), "thumbnail_url": best,
                    "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "",
                    "category_id": sn.get("categoryId", ""),
                })
        return out


class YtDlpSource:
    name = "yt-dlp"

    def __init__(self, binary: str = "yt-dlp"):
        self.bin = binary

    def _json(self, *args: str, timeout: int = 300) -> dict:
        r = subprocess.run([self.bin, "-J", "--no-warnings", "--skip-download", *args],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {r.stderr.strip()[-400:]}")
        return json.loads(r.stdout)

    def _url(self, ref: dict) -> str:
        if "id" in ref:
            return f"https://www.youtube.com/channel/{ref['id']}"
        if "handle" in ref:
            return f"https://www.youtube.com/{ref['handle']}"
        return f"https://www.youtube.com/c/{ref['legacy']}"

    def channel(self, ref: dict) -> dict:
        base = self._url(ref)
        data = self._json("--flat-playlist", "--playlist-end", "400", base + "/videos")
        self._flat = data.get("entries", [])
        try:  # Shorts live in their own tab
            self._flat += self._json("--flat-playlist", "--playlist-end", "100", base + "/shorts").get("entries", [])
        except RuntimeError:
            pass
        return {"id": data.get("channel_id") or data.get("id", ""), "title": data.get("channel") or data.get("title", ""),
                "handle": data.get("uploader_id", ""), "description": (data.get("description") or "")[:1500],
                "country": "", "created": "", "subs": int(data.get("channel_follower_count") or 0),
                "views": 0, "video_count": len(self._flat), "uploads_playlist": ""}

    def recent_ids(self, ch: dict, max_videos: int) -> list[str]:
        # Tabs list newest first; full details (dates, tags) are fetched for these only.
        videos = [e["id"] for e in self._flat if e.get("duration") is None or e["duration"] > SHORT_MAX_SECONDS][:max_videos // 2]
        shorts = [e["id"] for e in self._flat if e.get("duration") is not None and e["duration"] <= SHORT_MAX_SECONDS][:max_videos // 4]
        return list(dict.fromkeys(videos + shorts))

    def top_ids(self, ch: dict, n: int) -> list[str]:
        ranked = sorted((e for e in self._flat if e.get("view_count")), key=lambda e: e["view_count"], reverse=True)
        return [e["id"] for e in ranked[:n]]

    def details(self, ids: list[str]) -> list[dict]:
        out = []
        for vid in ids:
            try:
                d = self._json(f"https://www.youtube.com/watch?v={vid}", timeout=120)
            except Exception as e:
                print(f"  skipped {vid}: {e}")
                continue
            ts = d.get("timestamp") or 0
            published = dt.datetime.fromtimestamp(ts, dt.timezone.utc) if ts else \
                dt.datetime.strptime(d.get("upload_date", "19700101"), "%Y%m%d").replace(tzinfo=dt.timezone.utc)
            out.append({
                "id": vid, "title": d.get("title", ""), "published": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "description": (d.get("description") or "")[:1500], "tags": d.get("tags") or [],
                "duration": int(d.get("duration") or 0), "views": int(d.get("view_count") or 0),
                "likes": int(d.get("like_count") or 0), "comments": int(d.get("comment_count") or 0),
                "thumbnail_url": d.get("thumbnail", ""), "language": d.get("language") or "",
                "category_id": "", "date_precision": "second" if ts else "day",
            })
        return out


def pick_source():
    key = env("YOUTUBE_API_KEY")
    if key:
        return ApiSource(key)
    import sys
    venv_bin = Path(sys.executable).parent / "yt-dlp"  # venv not activated: still find its yt-dlp
    binary = shutil.which("yt-dlp") or (str(venv_bin) if venv_bin.exists() else None)
    if not binary:
        raise RuntimeError("Set YOUTUBE_API_KEY in .env or install yt-dlp (pip install yt-dlp).")
    return YtDlpSource(binary)


def enrich(videos: list[dict], at: dt.datetime) -> list[dict]:
    for v in videos:
        pub = dt.datetime.strptime(v["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        hours = max((at - pub).total_seconds() / 3600, 1.0)
        v["age_hours"] = round(hours, 1)
        v["views_per_hour"] = round(v["views"] / hours, 1)
        # The API doesn't say "Short"; an old 2-minute song is a normal video.
        v["is_short"] = 0 < v["duration"] <= 60 or (v["duration"] <= SHORT_MAX_SECONDS and (
            pub >= LONG_SHORTS_SINCE or "#short" in v["title"].lower()))
        v["like_rate"] = round(v["likes"] / v["views"], 4) if v["views"] else 0
    return videos


def viral(videos: list[dict], hours: int, top: int) -> dict:
    """Videos uploaded in the last `hours`, ranked by views per hour, each compared with the
    channel's usual pace (median views/hour of its other recent uploads of the same kind)."""
    def baseline(is_short: bool) -> float:
        pace = [v["views_per_hour"] for v in videos if v["is_short"] == is_short and v["age_hours"] > hours]
        return statistics.median(pace) if pace else 0

    base = {False: baseline(False), True: baseline(True)}
    for v in videos:
        b = base[v["is_short"]]
        v["outlier"] = round(v["views_per_hour"] / b, 2) if b else None
    window = sorted((v for v in videos if v["age_hours"] <= hours), key=lambda v: v["views_per_hour"], reverse=True)
    month = sorted((v for v in videos if v["age_hours"] <= 24 * 30), key=lambda v: v["views_per_hour"], reverse=True)
    return {"window_hours": hours, "last_window": window[:top], "last_30_days": month[:top],
            "baseline_views_per_hour": base[False], "baseline_short_views_per_hour": base[True]}


def cadence(videos: list[dict]) -> dict:
    pubs = sorted(dt.datetime.strptime(v["published"], "%Y-%m-%dT%H:%M:%SZ") for v in videos)
    if len(pubs) < 2:
        return {"uploads": len(pubs)}
    span_days = max((pubs[-1] - pubs[0]).total_seconds() / 86400, 1)
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(pubs, pubs[1:])]
    precise = [v for v in videos if v.get("date_precision", "second") == "second"]
    hours = Counter(dt.datetime.strptime(v["published"], "%Y-%m-%dT%H:%M:%SZ").hour for v in precise)
    days = Counter(p.strftime("%A") for p in pubs)
    shorts = sum(1 for v in videos if v["is_short"])
    return {"uploads": len(pubs), "span_days": round(span_days, 1),
            "per_week": round(len(pubs) / span_days * 7, 1), "median_gap_hours": round(statistics.median(gaps), 1),
            "shorts_share": round(shorts / len(videos), 2),
            "top_upload_hours_utc": [h for h, _ in hours.most_common(3)],
            "top_upload_days": [d for d, _ in days.most_common(3)]}


def lengths(videos: list[dict]) -> dict:
    def bucket(sec: int) -> str:
        for limit, name in ((60, "<1 min"), (180, "1-3 min"), (600, "3-10 min"), (1800, "10-30 min"), (3600, "30-60 min")):
            if sec <= limit:
                return name
        return "60+ min"

    longs = [v for v in videos if not v["is_short"]]
    by = {}
    for v in longs:
        by.setdefault(bucket(v["duration"]), []).append(v["views_per_hour"])
    return {"median_long_minutes": round(statistics.median([v["duration"] for v in longs]) / 60, 1) if longs else 0,
            "buckets": {k: {"videos": len(x), "median_views_per_hour": round(statistics.median(x), 1)}
                        for k, x in sorted(by.items())}}


EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def title_patterns(videos: list[dict]) -> dict:
    titles = [v["title"] for v in videos]
    if not titles:
        return {}
    words = Counter()
    bigrams = Counter()
    for t in titles:
        ws = re.findall(r"[a-z0-9']+", t.lower())
        words.update(w for w in ws if w not in STOPWORDS and len(w) > 2)
        bigrams.update(" ".join(p) for p in zip(ws, ws[1:]) if not set(p) <= STOPWORDS)
    tags = Counter(t.lower() for v in videos for t in v.get("tags", []))
    n = len(titles)
    return {
        "median_chars": statistics.median(len(t) for t in titles),
        "with_pipe": round(sum("|" in t for t in titles) / n, 2),
        "with_emoji": round(sum(bool(EMOJI.search(t)) for t in titles) / n, 2),
        "with_number": round(sum(bool(re.search(r"\d", t)) for t in titles) / n, 2),
        "with_caps_word": round(sum(bool(re.search(r"\b[A-Z]{3,}\b", t)) for t in titles) / n, 2),
        "with_hashtag": round(sum("#" in t for t in titles) / n, 2),
        "top_words": words.most_common(25), "top_phrases": bigrams.most_common(20), "top_tags": tags.most_common(25),
    }


def thumbnail_stats(path: Path) -> dict:
    from PIL import Image, ImageFilter, ImageStat

    img = Image.open(path).convert("RGB")
    # Shorts thumbnails come letterboxed in black; measure the picture, not the bars.
    box = img.convert("L").point(lambda p: 255 if p > 20 else 0).getbbox()
    if box and (box[2] - box[0]) * (box[3] - box[1]) > 0.2 * img.width * img.height:
        img = img.crop(box)
    img = img.resize((160, 90))
    _, s, v = ImageStat.Stat(img.convert("HSV")).mean
    pal = img.quantize(colors=4).convert("RGB")
    colours = sorted(pal.getcolors(), reverse=True)[:3]
    edges = ImageStat.Stat(img.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
    return {"brightness": round(v / 255, 2), "saturation": round(s / 255, 2), "busyness": round(edges / 255, 3),
            "main_colours": ["#%02x%02x%02x" % c for _, c in colours]}


def clean_caption(text: str) -> str:
    """Drop [music] / [Applause] cues and >> speaker marks auto-captions add."""
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]|>>", " ", text)).strip()


def transcript(vid: str, languages=("en", "en-US", "en-GB", "hi")) -> dict | None:
    """Cached in data/competitors/transcripts/ so the copy check can reuse them."""
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    cache = TRANSCRIPTS / f"{vid}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return {**data, "text": clean_caption(data["text"]), "hook": clean_caption(data["hook"])} if data else None
    if transcript.blocked:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segs = [{"start": s.start, "text": s.text} for s in YouTubeTranscriptApi().fetch(vid, languages=list(languages))]
    except ImportError:
        return None
    except Exception as e:
        if type(e).__name__ not in NO_TRANSCRIPT:
            # rate limit / IP block / network: not an answer about this video, so nothing is cached
            # and a later run fetches it; stop asking for the rest of this run
            transcript.blocked = True
            print(f"  transcripts paused ({type(e).__name__}); run again later to fill them in")
            return None
        segs = []
    data = {"video_id": vid, "text": clean_caption(" ".join(s["text"] for s in segs)),
            "hook": clean_caption(" ".join(s["text"] for s in segs if s["start"] < 20))} if segs else {}
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data or None


transcript.blocked = False
NO_TRANSCRIPT = {"TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable", "InvalidVideoId", "AgeRestricted",
                 "VideoUnplayable"}  # answers about the video itself: safe to remember


def confirm_shorts(videos: list[dict]) -> None:
    """The API doesn't say which videos are Shorts, and many kids songs are 2-3 minutes long.
    youtube.com/shorts/<id> answers 200 for a Short and redirects a normal video; guesses stay on errors."""
    from concurrent.futures import ThreadPoolExecutor

    def ask(v):
        try:
            r = requests.head(f"https://www.youtube.com/shorts/{v['id']}", allow_redirects=False, timeout=15,
                              headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException:
            return
        if r.status_code in (200, 301, 302, 303):
            v["is_short"] = r.status_code == 200
            v["short_checked"] = True

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(ask, [v for v in videos if 0 < v["duration"] <= SHORT_MAX_SECONDS]))


def download(url: str, dest: Path) -> Path | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def fmt_n(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else f"{n:.0f}"


def report_md(d: dict) -> str:
    ch, vir = d["channel"], d["viral"]

    def rows(vs):
        out = ["| # | title | views | views/hour | x usual | length | age |", "|---|---|---|---|---|---|---|"]
        for i, v in enumerate(vs, 1):
            out.append(f"| {i} | [{v['title'][:70]}](https://youtu.be/{v['id']}) | {fmt_n(v['views'])} | "
                       f"{fmt_n(v['views_per_hour'])} | {v.get('outlier') or '-'} | "
                       f"{'Short' if v['is_short'] else str(round(v['duration'] / 60, 1)) + ' min'} | "
                       f"{round(v['age_hours'] / 24, 1)} d |")
        return "\n".join(out)

    tp, cad, ln = d["titles"], d["cadence"], d["lengths"]
    parts = [
        f"# {ch['title']}: competitor research ({d['date']})",
        f"{fmt_n(ch['subs'])} subscribers, {ch['video_count']} videos, country {ch.get('country') or '?'}. "
        f"Data from {d['source']}; {len(d['videos'])} videos analysed.",
        f"## Taking off in the last {vir['window_hours']} hours",
        rows(vir["last_window"]) if vir["last_window"] else "_No uploads in this window._",
        "## Fastest of the last 30 days", rows(vir["last_30_days"]),
        "## All-time top", rows(d["all_time_top"]),
        "## Upload rhythm",
        f"{cad.get('per_week')} uploads a week (median gap {cad.get('median_gap_hours')} h), "
        f"{int(cad.get('shorts_share', 0) * 100)}% Shorts. Busiest UTC hours {cad.get('top_upload_hours_utc')}, "
        f"days {cad.get('top_upload_days')}.",
        "## Length",
        f"Median long video: {ln['median_long_minutes']} min.\n\n| length | videos | median views/hour |\n|---|---|---|\n" +
        "\n".join(f"| {k} | {b['videos']} | {fmt_n(b['median_views_per_hour'])} |" for k, b in ln["buckets"].items()),
        "## Titles",
        f"Median {tp.get('median_chars')} characters. Pipe '|' {int(tp.get('with_pipe', 0) * 100)}%, "
        f"emoji {int(tp.get('with_emoji', 0) * 100)}%, numbers {int(tp.get('with_number', 0) * 100)}%, "
        f"CAPS word {int(tp.get('with_caps_word', 0) * 100)}%, hashtags {int(tp.get('with_hashtag', 0) * 100)}%.\n\n"
        f"Words: {', '.join(w for w, _ in tp.get('top_words', []))}\n\n"
        f"Phrases: {', '.join(w for w, _ in tp.get('top_phrases', []))}\n\n"
        f"Tags: {', '.join(w for w, _ in tp.get('top_tags', []))}",
    ]
    thumbs = [v for v in d["videos"] if v.get("thumbnail")]
    if thumbs:
        parts += ["## Thumbnails of the top videos",
                  "| video | brightness | saturation | busyness | main colours |\n|---|---|---|---|---|\n" +
                  "\n".join(f"| {v['title'][:50]} | {v['thumbnail']['brightness']} | {v['thumbnail']['saturation']} | "
                            f"{v['thumbnail']['busyness']} | {' '.join(v['thumbnail']['main_colours'])} |" for v in thumbs)]
    hooks = [v for v in d["videos"] if v.get("hook")]
    if hooks:
        parts += ["## Openings (first 20 seconds)"] + [f"- **{v['title'][:60]}**: {v['hook'][:300]}" for v in hooks]
    return "\n\n".join(parts) + "\n"


def strategy_prompt(d: dict, us: dict) -> str:
    from . import llm

    keep = ("title", "views", "views_per_hour", "outlier", "duration", "is_short", "tags", "age_hours", "hook", "thumbnail")
    top = {k: [{f: v.get(f) for f in keep} for v in d["viral"][k]] for k in ("last_window", "last_30_days")}
    top["all_time"] = [{f: v.get(f) for f in keep} for v in d["all_time_top"]]
    return f"""You are the strategist for our YouTube channel. Study a competitor and say what we
should learn from it. Learn patterns (formats, topics, lengths, title shapes, thumbnail
style, openings, rhythm). Never copy: no titles, characters, lyrics, scripts, thumbnails
or brand elements of theirs. Traditional public-domain songs and stories are fine to
retell in our own way.

Our channel: {us.get('name')}
Niche: {us.get('niche')}
Audience: {us.get('audience')}

Competitor: {d['channel']['title']} ({fmt_n(d['channel']['subs'])} subscribers)
Measured numbers (views_per_hour = views since upload / hours since upload; outlier = that
divided by the channel's usual pace; duration in seconds; hook = first 20 seconds of speech):
{llm.untrusted(json.dumps({"cadence": d["cadence"], "lengths": d["lengths"], "titles": d["titles"], "top_videos": top}, ensure_ascii=False)[:60000])}

Return JSON with keys:
 "summary": 3-4 sentences on why their winners win,
 "patterns": {{"topics": [...], "titles": [...], "thumbnails": [...], "hooks": [...], "length": [...], "cadence": [...], "formats": [...]}},
 "do_for_us": [8-12 concrete actions for our channel, each one line],
 "avoid": [things that would hurt us: copying, policy risks for made-for-kids content, low effort],
 "idea_seeds": [8 objects {{"topic", "angle", "format": "song|story|learning|compilation|short", "minutes", "why"}}, each original to us]"""


def strategy_md(s: dict, ch: dict) -> str:
    out = [f"# What to learn from {ch['title']}", s.get("summary", "")]
    for k, items in (s.get("patterns") or {}).items():
        out.append(f"## {k.capitalize()}\n" + "\n".join(f"- {i}" for i in items))
    out.append("## Do on our channel\n" + "\n".join(f"- {i}" for i in s.get("do_for_us", [])))
    out.append("## Avoid\n" + "\n".join(f"- {i}" for i in s.get("avoid", [])))
    out.append("## Idea seeds\n" + "\n".join(
        f"- **{i.get('topic')}** ({i.get('format')}, {i.get('minutes')} min): {i.get('angle')}. _{i.get('why')}_"
        for i in s.get("idea_seeds", [])))
    return "\n\n".join(out) + "\n"


def analyse(source, ref: str, *, hours: int = 72, max_videos: int = 150, top: int = 10,
            fetch_media: bool = True, at: dt.datetime | None = None) -> dict:
    at = at or now()
    ch = source.channel(parse_channel(ref))
    print(f"{ch['title']}: {fmt_n(ch['subs'])} subscribers, reading up to {max_videos} recent videos via {source.name}")
    recent = source.recent_ids(ch, max_videos)
    top_all = source.top_ids(ch, top)
    videos = enrich(source.details(list(dict.fromkeys(recent + top_all))), at)
    if fetch_media:
        confirm_shorts(videos)
    by_id = {v["id"]: v for v in videos}
    all_time = sorted((by_id[i] for i in top_all if i in by_id), key=lambda v: v["views"], reverse=True)
    recent_set = set(recent)
    recent_videos = [v for v in videos if v["id"] in recent_set]
    vir = viral(recent_videos, hours, top)
    d = {"date": at.strftime("%Y-%m-%d"), "source": source.name, "channel": ch, "videos": videos,
         "viral": vir, "all_time_top": all_time, "cadence": cadence(recent_videos),
         "lengths": lengths(recent_videos), "titles": title_patterns(recent_videos)}
    d["folder"] = str(OUT / slug(ch.get("handle") or ch["title"]) / d["date"])

    studied = {v["id"]: v for v in vir["last_window"] + vir["last_30_days"] + all_time}
    if fetch_media:
        folder = Path(d["folder"])
        for v in studied.values():
            t = transcript(v["id"])
            if t:
                v["hook"] = t["hook"] or "(music only, no words in the first 20 seconds)"
                v["has_transcript"] = True
            p = download(v["thumbnail_url"], folder / "thumbs" / f"{v['id']}.jpg")
            if p:
                try:
                    v["thumbnail"] = thumbnail_stats(p)
                except Exception:
                    pass
    d["studied_ids"] = list(studied)
    return d


def save(d: dict) -> Path:
    folder = Path(d["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dataset.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    cols = ["id", "title", "published", "views", "views_per_hour", "outlier", "duration", "is_short", "likes",
            "comments", "like_rate", "tags"]
    with open(folder / "videos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for v in sorted(d["videos"], key=lambda v: v["views_per_hour"], reverse=True):
            w.writerow([("; ".join(v[c]) if c == "tags" else v.get(c)) for c in cols])
    (folder / "report.md").write_text(report_md(d), encoding="utf-8")
    return folder


def write_strategy(d: dict) -> dict | None:
    from . import llm
    from .config import section

    folder = Path(d["folder"])
    try:
        s = llm.ask(strategy_prompt(d, section("channel")), name="strategy", workdir=folder, want_json=True)
    except llm.WaitingForHuman as e:
        print(e)
        return None
    (folder / "strategy.json").write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "strategy.md").write_text(strategy_md(s, d["channel"]), encoding="utf-8")
    update_insights(d, s)
    return s


def update_insights(d: dict, s: dict) -> None:
    p = OUT / "insights.json"
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[d["channel"]["id"]] = {"channel": d["channel"]["title"], "date": d["date"], "folder": d["folder"],
                                "summary": s.get("summary", ""), "do_for_us": s.get("do_for_us", []),
                                "avoid": s.get("avoid", []), "idea_seeds": s.get("idea_seeds", []),
                                "reference_videos": d["studied_ids"],
                                "top_titles": [v["title"] for v in d["viral"]["last_30_days"]][:10]}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_insights() -> dict:
    p = OUT / "insights.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def prompt_block(max_channels: int = 5) -> tuple[str, list[str]]:
    """Text for idea/script prompts plus the competitor video ids the copy check must compare against."""
    ins = sorted(load_insights().values(), key=lambda x: x["date"], reverse=True)[:max_channels]
    if not ins:
        return "", []
    from . import llm

    lines, refs = [], []
    for i in ins:
        lines.append(f"From {i['channel']} ({i['date']}): {i['summary']}\nDo: " + "; ".join(i["do_for_us"]) +
                     "\nAvoid: " + "; ".join(i["avoid"]) +
                     "\nTheir current winners (data, never copy): " + " / ".join(i["top_titles"]))
        refs += i["reference_videos"]
    text = ("Competitor research (patterns to learn from, never copy titles, characters, lyrics or scripts):\n"
            + llm.untrusted("\n\n".join(lines)))
    return text, list(dict.fromkeys(refs))


def run(refs: list[str], *, hours: int = 72, max_videos: int = 150, top: int = 10, strategy: bool = True,
        source=None) -> list[Path]:
    source = source or pick_source()
    folders = []
    for ref in refs:
        d = analyse(source, ref, hours=hours, max_videos=max_videos, top=top)
        folder = save(d)
        print(f"Report: {folder / 'report.md'}")
        if strategy and write_strategy(d):
            print(f"Strategy: {folder / 'strategy.md'}")
        folders.append(folder)
    return folders
