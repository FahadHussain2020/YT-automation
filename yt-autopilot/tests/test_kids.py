"""Kids mode, offline: switch, prompts, safety check, cut-out, host placement, thumbnails, checks wiring."""
import pytest
from PIL import Image, ImageDraw

from autopilot import config, kids, store
from autopilot.checks import kids_safety


def kscript(lines):
    return {"structure": "learn_one_thing_short", "sections": [
        {"heading": "Farm", "beat": "", "lines": [{"text": t, "kind": "song", "pause": 0, "shot": "a cow in a barn"}
                                                 for t in lines]}]}


@pytest.fixture
def kids_cfg(monkeypatch):
    cfg = {**config.channel(), "mode": "kids"}
    monkeypatch.setattr(kids, "channel", lambda: cfg)
    return cfg


def test_mode_switch(kids_cfg, monkeypatch):
    assert kids.enabled()
    monkeypatch.setattr(kids, "channel", lambda: {k: v for k, v in kids_cfg.items() if k != "mode"})
    assert not kids.enabled()  # history path stays the default


def test_safety_passes_gentle_script():
    r = kids_safety.check(kscript(["Moo! Moo! It's a cow.", "Can you say moo?", "Baa! Baa! A fluffy sheep."]))
    assert r["passed"], r["problems"]


@pytest.mark.parametrize("line,why", [
    ("The scary monster will eat you.", "Not for ages 0-6"),
    ("Sing along like on CoComelon!", "Brand"),
    ("This song boosts IQ for babies.", "Claim"),
])
def test_safety_flags(line, why):
    r = kids_safety.check(kscript(["Moo! Moo! It's a cow.", line]))
    assert not r["passed"] and any(why in p for p in r["problems"])


def test_safety_flags_greeting_and_long_sentences():
    assert not kids_safety.check(kscript(["Hello friends, welcome back!", "Moo says the cow."]))["passed"]
    long = "The cow walks slowly across the big green field and then she stops to eat some very tasty grass today."
    assert not kids_safety.check(kscript(["Moo!", long, long]))["passed"]


def test_short_videos_get_short_structures(kids_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "VIDEOS", tmp_path)
    assert "short" in kids.pick_structure(kids_cfg, short=True)["name"]
    assert "short" not in kids.pick_structure(kids_cfg, short=False)["name"]


def test_script_prompt_has_kids_rules(kids_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "VIDEOS", tmp_path)
    kids_cfg["host"] = "character"
    v = store.create("Farm animal sounds with Hoppy", short=True)
    p = kids.script_prompt(v, kids_cfg["structures"][0], kids_cfg["hooks"][0], kids_cfg, 100)
    assert "Hoppy the Bunny" in p and "pause" in p and "Sources" not in p


def fake_character():
    img = Image.new("RGB", (400, 400), (235, 235, 235))
    d = ImageDraw.Draw(img)
    d.ellipse([120, 80, 280, 360], fill=(60, 200, 60))
    d.ellipse([180, 150, 200, 170], fill=(255, 255, 255))  # eye highlight: must stay
    return img


def test_cutout_removes_grey_background():
    c = kids.cutout(fake_character())
    assert 150 <= c.width <= 170 and c.getpixel((c.width // 2, c.height // 2))[3] == 255
    assert c.getpixel((c.width // 2 - 20 + 10, 80))[3] == 255  # eye highlight inside the body kept
    assert c.getpixel((0, 0))[3] == 0


def test_place_host_and_thumbnail(tmp_path, monkeypatch):
    host = kids.cutout(fake_character())
    scene = Image.new("RGB", (1080, 1920), (120, 200, 255))
    out = kids.place_host(scene, host, 0)
    assert out.size == (1080, 1920) and out.getpixel((540, 200)) == (120, 200, 255)
    monkeypatch.setattr(kids, "sprite", lambda: host)
    p = kids.thumbnail("Moo Moo Farm", tmp_path / "t.jpg", kids.BRIGHT[0])
    assert Image.open(p).size == (1280, 720)


def test_tts_pause_adds_silence(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    from autopilot import tts
    monkeypatch.setattr(store, "VIDEOS", tmp_path)
    v = store.create("pause test")
    v.write("script.json", kscript(["Can you say moo?"]) | {"sections": [{"heading": "A", "lines": [
        {"text": "Can you say moo?", "pause": 2, "shot": "cow"}]}]})
    monkeypatch.setattr(tts, "kokoro_tts", lambda text, voice, speed, out: sf.write(out, np.zeros(24000, "float32"), 24000))
    tl = tts.run(v)
    total = sf.info(v.path("narration_en.wav")).duration
    assert tl[0]["end"] == pytest.approx(1.0) and total == pytest.approx(1.0 + tts.GAP + 2.0, abs=0.01)


def test_vertical_captions_are_ass_sized_to_the_frame():
    from autopilot import render
    srt = render.captions([{"text": "Moo! Look, a cow!", "start": 0.0, "end": 1.5}], max_chars=18)
    ass = render.ass_captions(srt, 1080, 1920)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.00," in ass and "Moo! Look, a cow!" in ass


def test_host_none_removes_the_character(kids_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "VIDEOS", tmp_path)
    kids_cfg["host"] = "none"
    assert kids.character() is None
    v = store.create("Who's on the farm?")
    p = kids.script_prompt(v, kids_cfg["structures"][0], kids_cfg["hooks"][0], kids_cfg, 400)
    assert "hoppy the bunny" not in p.lower() and "NO on-screen host" in p


def test_cutout_key_keeps_a_white_animal_on_blue():
    img = Image.new("RGB", (400, 400), (150, 200, 245))
    ImageDraw.Draw(img).ellipse([100, 120, 300, 330], fill=(250, 250, 250))  # white sheep
    c = kids.cutout_key(img)
    assert 190 <= c.width <= 205 and c.getpixel((c.width // 2, c.height // 2))[3] == 255
    assert c.getpixel((2, 2))[3] == 0


def test_compose_puts_the_same_cutout_on_the_same_place():
    bg = Image.new("RGB", (1344, 768), (120, 200, 120))
    cow = Image.new("RGBA", (200, 160), (120, 80, 40, 255))
    one = kids.compose(bg, [(cow, "big")], 0, (1920, 1080))
    many = kids.compose(bg, [(cow, "big")] * 6, 0, (1920, 1080))
    assert one.size == many.size == (1920, 1080)
    assert one.getpixel((960, 50)) == (120, 200, 120)  # sky/background untouched


def test_timing_counts_answer_pauses():
    from autopilot.checks import timing
    s = kscript([" ".join(["moo"] * 100)])
    assert timing.check(s, 1.0, 130)["score"] == pytest.approx(100 / 130, abs=0.01)
    s["sections"][0]["lines"][0]["pause"] = 3
    assert timing.check(s, 1.0, 130)["score"] == pytest.approx(100 / 130 + 0.05, abs=0.01)


def test_recurring_boy_rule(kids_cfg, tmp_path, monkeypatch):
    from autopilot import config as cfgmod
    sprite = tmp_path / "max.png"
    Image.new("RGBA", (10, 10)).save(sprite)
    kids_cfg["characters"] = {"max": {"name": "Max", "kind": "boy", "sprite": str(sprite)}}
    monkeypatch.setattr(kids, "section", lambda n: kids_cfg.get(n, {}) or {})
    assert "max" in kids.ready_characters()
    assert "Any boy in the story is Max" in kids.recurring_rule()
    s = kscript(["Moo! Look, a cow."])
    s["cast"] = {"tom": {"look": "a little boy in a red hat"}}
    r = kids_safety.check(s, characters=kids.ready_characters())
    assert not r["passed"] and any("use Max" in p for p in r["problems"])
    s["cast"] = {"cow": {"look": "a brown cow"}}
    assert kids_safety.check(s, characters=kids.ready_characters())["passed"]


def test_main_shape_spots_patterns():
    one = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    ImageDraw.Draw(one).ellipse([50, 50, 250, 250], fill=(200, 100, 50, 255))
    ImageDraw.Draw(one).rectangle([280, 280, 285, 285], fill=(200, 100, 50, 255))  # stray speck
    cut, share = kids.main_shape(one)
    assert share > 0.95 and cut.width <= 210
    many = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    for x in range(0, 300, 60):
        for y in range(0, 300, 60):
            ImageDraw.Draw(many).ellipse([x + 5, y + 5, x + 45, y + 45], fill=(200, 100, 50, 255))
    assert kids.main_shape(many)[1] < 0.2


def test_layered_segment_puts_characters_over_a_moving_place(tmp_path):
    import shutil
    import subprocess

    from autopilot import render
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    bg = tmp_path / "loop.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:s=320x180:r=24:d=2",
                    "-pix_fmt", "yuv420p", str(bg)], check=True)
    over = tmp_path / "over.png"
    layer = Image.new("RGBA", (320, 180), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([140, 60, 180, 120], fill=(255, 0, 0, 255))
    layer.save(over)
    out = tmp_path / "seg.mp4"
    render.layered_segment(bg, over, 3.0, 5.2, out, 320, 180, 24)  # longer than the loop, entered mid-loop
    assert abs(render.probe_duration(out) - 3.0) < 0.1
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(frame)], check=True)
    img = Image.open(frame).convert("RGB")
    assert img.getpixel((160, 90))[0] > 200 and img.getpixel((20, 20))[1] > 100  # red character on green place


def test_safety_flags_words_the_voice_spells_out():
    r = kids_safety.check(kscript(["Shh, little one.", "Goodnight, moon."]))
    assert not r["passed"] and any("spells out" in p for p in r["problems"])
