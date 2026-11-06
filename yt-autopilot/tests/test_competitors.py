"""Competitor research, offline: a fake source instead of YouTube."""
import datetime as dt
import json

import pytest
from PIL import Image

from autopilot import competitors, config
from autopilot.checks import copying

AT = dt.datetime(2026, 10, 25, 12, tzinfo=dt.timezone.utc)


def iso(hours_ago: float) -> str:
    return (AT - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def vid(i, hours_ago, views, duration=240, title=None, tags=()):
    return {"id": f"v{i:02d}", "title": title or f"Wheels on the Bus Song {i} | Nursery Rhymes", "published": iso(hours_ago),
            "description": "", "tags": list(tags), "duration": duration, "views": views, "likes": views // 100,
            "comments": 0, "thumbnail_url": "", "language": "en", "category_id": "27"}


class FakeSource:
    name = "fake"

    def __init__(self):
        self.videos = [vid(0, 24, 48000, title="Bath Time Song | Kids Songs", tags=["bath song"]),
                       vid(1, 30, 900, duration=45, title="Tiny Dance #shorts")]
        self.videos += [vid(i, 24 * (i + 2), int(100 * 24 * (i + 2))) for i in range(2, 20)]
        self.videos.append(vid(99, 24 * 2000, 900_000_000, title="Johny Johny Classic"))

    def channel(self, ref):
        return {"id": "UCfake", "title": "Fake Kids TV", "handle": "@fakekids", "description": "", "country": "IN",
                "created": "", "subs": 5_000_000, "views": 0, "video_count": len(self.videos), "uploads_playlist": "UU"}

    def recent_ids(self, ch, n):
        return [v["id"] for v in self.videos if v["id"] != "v99"][:n]

    def top_ids(self, ch, n):
        return ["v99"]

    def details(self, ids):
        return [dict(v) for v in self.videos if v["id"] in ids]


@pytest.mark.parametrize("ref,want", [
    ("@ChuChuTV", {"handle": "@ChuChuTV"}),
    ("https://www.youtube.com/@ChuChuTV/videos", {"handle": "@ChuChuTV"}),
    ("ChuChuTV", {"handle": "@ChuChuTV"}),
    ("UCBnZ16ahKA2DZ_T5W0FPUXg", {"id": "UCBnZ16ahKA2DZ_T5W0FPUXg"}),
    ("https://www.youtube.com/c/ChuChuTV", {"legacy": "ChuChuTV"}),
])
def test_parse_channel(ref, want):
    assert competitors.parse_channel(ref) == want


def test_iso_duration():
    assert competitors.iso_duration("PT1H2M3S") == 3723
    assert competitors.iso_duration("PT45S") == 45
    assert competitors.iso_duration("") == 0


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(competitors, "OUT", tmp_path / "competitors")
    return tmp_path


def test_analyse_finds_the_hit(out):
    d = competitors.analyse(FakeSource(), "@fakekids", fetch_media=False, at=AT)
    hit = d["viral"]["last_window"][0]
    assert hit["id"] == "v00" and hit["outlier"] > 10
    assert d["all_time_top"][0]["views"] == 900_000_000
    assert d["cadence"]["per_week"] > 0
    assert any(v["is_short"] for v in d["videos"])


def test_save_and_prompt_block(out):
    d = competitors.analyse(FakeSource(), "@fakekids", fetch_media=False, at=AT)
    folder = competitors.save(d)
    assert len((folder / "videos.csv").read_text(encoding="utf-8").strip().splitlines()) == len(d["videos"]) + 1
    assert "Taking off in the last 72 hours" in (folder / "report.md").read_text(encoding="utf-8")
    competitors.update_insights(d, {"summary": "Short bright songs win.", "do_for_us": ["Make a bath song"],
                                    "avoid": ["copying"], "idea_seeds": []})
    text, ids = competitors.prompt_block()
    assert "Make a bath song" in text and "<untrusted>" in text
    assert "v00" in ids


def test_fetch_transcripts_uses_competitor_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    cache = tmp_path / "competitors" / "transcripts"
    cache.mkdir(parents=True)
    (cache / "abc.json").write_text(json.dumps({"video_id": "abc", "text": "row row row your boat"}))
    (cache / "nolyrics.json").write_text("{}")  # known to have no transcript: not fetched again
    assert copying.fetch_transcripts(["abc", "nolyrics"]) == [{"video_id": "abc", "text": "row row row your boat"}]


def test_thumbnail_stats(tmp_path):
    p = tmp_path / "t.jpg"
    Image.new("RGB", (320, 180), (255, 230, 0)).save(p)
    s = competitors.thumbnail_stats(p)
    assert s["brightness"] > 0.9 and s["saturation"] > 0.9


def test_letterboxed_short_thumbnail_ignores_black_bars(tmp_path):
    p = tmp_path / "short.jpg"
    img = Image.new("RGB", (480, 360), (0, 0, 0))
    img.paste(Image.new("RGB", (200, 360), (255, 230, 0)), (140, 0))
    img.save(p)
    assert competitors.thumbnail_stats(p)["brightness"] > 0.9


def test_old_three_minute_song_is_not_a_short():
    old = vid(5, 24 * 3000, 1000, duration=150)
    new = vid(6, 24, 1000, duration=150)
    competitors.enrich([old, new], AT)
    assert not old["is_short"] and new["is_short"]


def test_clean_caption():
    assert competitors.clean_caption("[music] Open. >> Open. [Applause]") == "Open. Open."


def test_blocked_transcripts_are_not_cached(out, monkeypatch):
    import youtube_transcript_api

    class IpBlocked(Exception):
        pass

    class Api:
        def fetch(self, vid, languages):
            raise IpBlocked("blocked")

    monkeypatch.setattr(competitors, "TRANSCRIPTS", out / "transcripts")
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", Api)
    monkeypatch.setattr(competitors.transcript, "blocked", False)
    assert competitors.transcript("abc") is None
    assert not (out / "transcripts" / "abc.json").exists() and competitors.transcript.blocked


def test_confirm_shorts_uses_the_shorts_url(monkeypatch):
    class R:
        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(competitors.requests, "head",
                        lambda url, **kw: R(200 if url.endswith("short1") else 303))
    vs = [{"id": "short1", "duration": 150, "is_short": False}, {"id": "song1", "duration": 170, "is_short": True},
          {"id": "long1", "duration": 400, "is_short": False}]
    competitors.confirm_shorts(vs)
    assert [v["is_short"] for v in vs] == [True, False, False]
