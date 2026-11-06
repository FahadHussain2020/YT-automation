"""Offline tests: no API keys or network needed. Run: python -m pytest -q"""
import os
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from autopilot import checks, render, store
from autopilot.checks import copying, facts, quality, timing
from autopilot.media import licences

SOURCES = [{"id": "S1", "title": "Library of Alexandria", "url": "https://en.wikipedia.org/wiki/Library_of_Alexandria",
            "text": "The library was founded around 285 BC under Ptolemy I Soter. It may have held 40000 scrolls. "
                    "Julius Caesar's fire in 48 BC damaged part of the city's warehouses."}]


def make_script(lines):
    return {"structure": "myth_vs_fact", "sections": [
        {"heading": f"Part {n}", "beat": "", "lines": chunk} for n, chunk in enumerate(lines, 1)]}


def line(text, kind="fact", src=("S1",)):
    return {"text": text, "kind": kind, "sources": list(src), "shot": "old scrolls", "search": "papyrus scroll"}


def test_fact_check_flags_unsupported_numbers_and_missing_sources():
    s = make_script([[line("Ptolemy I Soter founded it around 285 BC."),
                      line("It held 700000 scrolls."),
                      line("Nobody knows who burned it.", src=()),
                      line("I think the myth says more about us.", kind="opinion", src=())]])
    r = facts.check(s, SOURCES)
    assert not r["passed"]
    assert any("700000" in p for p in r["problems"])
    assert any("No source" in p for p in r["problems"])
    assert r["score"] == pytest.approx(1 / 3, abs=0.01)


def test_timing_check():
    words = " ".join(["word"] * 150)
    hook = " ".join(["word"] * 100)
    r = timing.check(make_script([[line(hook)], [line(words)], [line(words)], [line(" ".join(["w"] * 50))]]),
                     target_minutes=3, wpm=150)
    assert r["passed"], r["problems"]
    assert not timing.check(make_script([[line(words)]] * 3), target_minutes=3, wpm=150)["passed"]  # long hook
    assert not timing.check(make_script([[line(words)]]), target_minutes=9, wpm=150)["passed"]


def test_copy_check_catches_long_runs_from_source_and_transcripts():
    copied = make_script([[line("The library was founded around 285 BC under Ptolemy I Soter. It may have held 40000 scrolls.")]])
    r = copying.check(copied, SOURCES, [], [])
    assert not r["passed"]
    fresh = make_script([[line("Around 285 BC, Ptolemy I Soter started a collection that drew scholars to Alexandria.")]])
    assert copying.check(fresh, SOURCES, [], [])["passed"]
    transcript = [{"video_id": "abc123", "text": "around 285 BC Ptolemy I Soter started a collection that drew scholars to Alexandria"}]
    assert not copying.check(fresh, SOURCES, [], transcript)["passed"]


def test_quality_check_rejects_filler_and_vague_hook():
    s = make_script([[line("In this video we delve into history."), line("It was big.")]])
    r = quality.check(s)
    assert not r["passed"]
    assert any("delve" in p for p in r["problems"])


@pytest.mark.parametrize("lic,ok,credit", [
    ("CC BY-SA 4.0", True, True), ("CC BY 2.0", True, True), ("Public domain", True, False), ("CC0", True, False),
    ("CC BY-NC 4.0", False, False), ("CC BY-ND 3.0", False, False), ("Fair use", False, False), ("", False, False),
    ("Pexels License", True, False)])
def test_licences(lic, ok, credit):
    assert licences.allowed(lic) is ok
    if ok:
        assert licences.needs_credit(lic) is credit


def test_description_credits():
    items = [{"source": "Wikimedia Commons", "title": "Map.jpg", "author": "Jane Doe", "licence": "CC BY-SA 4.0",
              "licence_url": "https://creativecommons.org/licenses/by-sa/4.0", "page_url": "x"},
             {"source": "AI", "title": "AI illustration", "author": "AI", "licence": "AI generated", "licence_url": "", "page_url": ""}]
    text = licences.description_block(items)
    assert "Jane Doe" in text and "CC BY-SA 4.0" in text and "AI-generated" in text


def test_captions_and_chapters():
    tl = [{"i": 0, "section": "Intro", "text": "One two three four five six seven eight nine ten eleven twelve", "start": 0, "end": 4},
          {"i": 1, "section": "Middle", "text": "More words here", "start": 12, "end": 15},
          {"i": 2, "section": "End", "text": "Last", "start": 30, "end": 31}]
    srt = render.captions(tl, max_chars=20)
    assert srt.startswith("1\n00:00:00,000 --> ")
    chs = render.chapters(tl)
    assert [c["title"] for c in chs] == ["Intro", "Middle", "End"] and chs[0]["start"] == 0
    assert render.chapter_text(chs).splitlines()[1] == "0:12 Middle"


@pytest.fixture
def tmp_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "VIDEOS", tmp_path / "videos")
    return tmp_path


def test_store_stages(tmp_videos):
    v = store.create("The Library of Alexandria")
    assert v.stage == "idea" and store.at_stage("idea")[0].id == v.id
    v.set_stage("scripted")
    assert store.get(v.id).stage == "scripted"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_render_end_to_end(tmp_videos, monkeypatch):
    """Fake voice + generated pictures -> real ffmpeg render with loudness and chapters."""
    monkeypatch.setattr(render, "pick_music", lambda v: None)  # no network in tests
    v = store.create("Render test")
    sr, tl, t, chunks = 24000, [], 0.0, []
    for i, sec in enumerate(["Intro", "Middle", "End"]):
        dur = 11.0
        tone = (0.2 * np.sin(2 * np.pi * (220 + 60 * i) * np.arange(int(sr * dur)) / sr)).astype("float32")
        chunks.append(tone)
        tl.append({"i": i, "section": sec, "text": f"Line {i} of the test video", "kind": "fact", "start": t, "end": t + dur})
        t += dur
    sf.write(v.path("narration_en.wav"), np.concatenate(chunks), sr)
    plan = []
    for i in range(3):
        p = v.path(f"media/img_{i}.jpg")
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (1600, 1000), (60 * i, 90, 150)).save(p)
        plan.append({"i": i, "start": tl[i]["start"], "end": tl[i]["end"],
                     "shots": [{"path": str(p), "kind": "image", "source": "local"}]})
    final = render.run(v, plan, tl)
    assert final.exists()
    assert abs(render.probe_duration(final) - 33) < 1.0
    assert len(v.read("chapters.json")) == 3
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(final), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    integrated = float(out.rsplit("I:", 1)[1].split("LUFS")[0])
    assert abs(integrated - (-14)) < 1.5


def test_writer_mode_falls_back_without_keys(monkeypatch):
    from autopilot import llm

    monkeypatch.setenv("AI_MODE", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_BIN", "no-such-claude-binary")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    llm.resolve_mode.cache_clear()
    try:
        assert llm.resolve_mode() == "offline"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
        llm.resolve_mode.cache_clear()
        assert llm.resolve_mode() == "anthropic"
    finally:
        llm.resolve_mode.cache_clear()


def test_title_card(tmp_path):
    from autopilot.media.ai_images import title_card

    out = title_card("A fairly long title that has to wrap onto two lines", tmp_path / "card.jpg")
    assert Image.open(out).size == (1920, 1080)
