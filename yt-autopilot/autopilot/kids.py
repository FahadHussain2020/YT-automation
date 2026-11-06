"""Kids mode (`mode: kids` in config/channel.yaml): original songs and stories for ages 0-6,
told by a friendly narrator, optionally with an on-screen host character (`host: none` = no host).

What changes compared with the default (history) path:
  script      no research or sources; original lyrics/story in a kids structure, with pauses
              for call-and-response; a kids safety check replaces the fact and quality checks
  pictures    "sticker scenes": the script names a few places and a cast; each place and each
              cast member is drawn ONCE (fixed seed) and the cut-outs are placed into the same
              backgrounds, so the farm and every animal look identical in every shot (an image
              model redraws things differently each time). The host, if any, is added the same way.
  thumbnails  one subject (host or main cast member) large, flat bright background, 2-4 big words
  packaging   plain titles with the age group, at most 2 hashtags, never another channel's name
Upload stays private with made_for_kids and the synthetic-media disclosure set.
"""
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import competitors, llm, store
from .config import ROOT, channel, section

SCENE_STYLE = (", soft 3D cartoon scene for toddlers, children's animation style, bright pastel colours, "
               "simple uncluttered background, soft gentle light, cute and friendly")
SCENE_NEGATIVE = ("text, letters, words, writing, watermark, logo, signature, realistic photo, scary, dark, horror, "
                  "angry, teeth, blood, weapon, deformed, extra limbs")
CHARACTER = {
    "name": "Hoppy the Bunny",
    "description": "cute friendly little bunny character, soft light grey fur, long floppy ears, pink nose, "
                   "big round eyes, wide happy smile, chubby round soft body, short arms",
    "style": ", full body, standing, centered, plain pure white background, soft 3D cartoon render, pastel colours",
    "seed": 123,
    "sprite": "assets/characters/host.png",
}
SCRIPT_SHAPE = """{
  "structure": "<structure name>",
  "places": {"<place>": "what this one setting looks like (drawn once, reused in every shot set there)"},
  "cast": {"<name>": {"look": "how this animal/object looks (drawn once, reused)", "size": "big | medium | small",
                      "position": "ground | sky (sun, moon, stars, clouds, rainbow float in the sky)"}},
  "sections": [
    {"heading": "short part name",
     "beat": "which beat of the structure this is",
     "lines": [
        {"text": "what the narrator says or chants, in short simple words",
         "kind": "song | story | prompt",
         "pause": 0,
         "place": "<one of places>",
         "pose": "<only on lines showing a recurring character: one of their poses>",
         "subjects": ["<names from cast shown in this shot, 0-3; up to 8 only in a recap>"],
         "shot": "one sentence describing the picture"}
     ]}
  ]
}"""


def enabled() -> bool:
    return channel().get("mode") == "kids"


def characters() -> dict:
    """Recurring characters from channel.yaml `characters:` (key -> settings); the old single
    `character:` section counts as one called "character"."""
    out = {k.lower(): {"style": CHARACTER["style"], **c} for k, c in (section("characters") or {}).items()}
    if section("character"):
        out.setdefault("character", {**CHARACTER, **section("character")})
    return out


def character(key: str | None = None) -> dict | None:
    """The on-screen host (or the named character), None when channel.yaml says `host: none`."""
    key = (key or str(channel().get("host", "character"))).lower()
    if key == "none":
        return None
    return characters().get(key) or {**CHARACTER, **section("character")}


def ready_characters() -> dict:
    """Characters whose cut-out exists, so scripts may put them on screen."""
    return {k: c for k, c in characters().items() if c.get("sprite") and (ROOT / c["sprite"]).exists()}


def video_format(v: store.Video) -> dict:
    """Format settings with this video's own overrides (a vertical Short has its own size and length)."""
    fmt = dict(section("format"))
    for k in ("resolution", "target_minutes"):
        if v.state.get(k):
            fmt[k] = v.state[k]
    return fmt


def pick_structure(cfg: dict, short: bool) -> dict:
    """Shorts use the structures made for Shorts, long videos the others; least recently used first."""
    from collections import Counter

    fitting = [s for s in cfg["structures"] if ("short" in s["name"]) == short] or cfg["structures"]
    used = Counter(v.state.get("structure") for v in store.all_videos()[-len(fitting) * 2:])
    return min(fitting, key=lambda s: used.get(s["name"], 0))


def script_prompt(v: store.Video, structure: dict, hook: str, cfg: dict, words: int) -> str:
    ch, host = cfg["channel"], character(v.state.get("host"))
    lessons = [l["lesson"] for l in store.load_lessons()][-10:]
    research, _ = competitors.prompt_block()
    if not host:  # strategies written for a channel with a host may still name it
        research = without_host(research)
    short = "This is a vertical YouTube Short: every second counts." if v.state.get("short") else ""
    return f"""Write an ORIGINAL script for a children's YouTube video. {short}

Channel: {ch.get('name')}: {ch['niche']}
Audience: {ch['audience']}
{f"Host: {host['name']}, who speaks directly to the child." if host else
  "Narrator: a warm, friendly voice speaking directly to the child. There is NO on-screen host or character: "
  "never mention or name one."}
Topic: {v.state['topic']}
Angle: {v.state.get('angle', '')}
Length: about {words} spoken words in total.

Structure "{structure['name']}", beats in this order:
{json.dumps(structure['beats'])}

Opening rule: {hook}

Lessons from this channel's analytics:
{json.dumps(lessons)}

{research}

Rules:
- Ages 0-6: very short sentences (mostly 3-8 words), simple everyday words, lots of repetition.
- Call-and-response: ask the child to say or do something ("Can you say moo?"), then set "pause" to 1.5-2
  seconds on that line so they can answer. Use 2-4 such moments.
- Gentle and warm. Nothing scary, sad, violent or rude. No dangerous actions a toddler could copy.
- No brand names, no other channels or characters, no claims like "makes your baby smarter".
- No greeting or intro before the content; never ask to like or subscribe.
- All lines are our own, except the traditional public-domain words of a classic rhyme (e.g. "Twinkle, twinkle,
  little star"), which may be used as written, plus new verses of our own. Never reuse another channel's words.
- The words are spoken (chanted) by a voice, not sung: give them a bouncy, rhythmic feel.
  {("Each line is one phrase of the melody playing underneath, so song lines should be short (4-8 words) and "
    "even, like lines of a song.") if v.state.get("melody") else ""}
{recurring_rule()}
- Whenever a recurring character is in "subjects", set "pose" on that line to fit the words.
- Pictures: define 1-3 "places" (simple settings, no animals or people in them) and a "cast" (each
  animal or object that appears, with its look). Every line picks a place and lists the cast "subjects"
  seen in that shot, matching the words exactly (if the line names a cow, the cow is in the shot; while
  a sound is heard before the reveal, the shot has no subjects). No people or children in the cast.
  {"The host is added automatically: don't put him in the cast." if host else ""}
  No words, letters or numbers in any picture.

Return JSON in exactly this shape:
{SCRIPT_SHAPE}"""


def recurring_rule() -> str:
    ready = ready_characters()
    if not ready:
        return "- No people or children in the story or pictures."
    names = ", ".join(f"{c.get('name', k)} ({c.get('kind', 'character')}, cast key \"{k}\")" for k, c in ready.items())
    boys = [c.get("name", k) for k, c in ready.items() if c.get("kind") == "boy"]
    poses = sorted({p for c in ready.values() for p in (c.get("poses") or {})})
    return (f"- Recurring characters you may use: {names}. Call them by name, list them in \"subjects\" by their "
            f"cast key and do NOT put them in \"cast\" (their look is fixed)."
            + (f" Any boy in the story is {boys[0]}; no other boys." if boys else "")
            + (f" A line may set \"pose\" to one of {poses}." if poses else "")
            + " No other people or children.")


def without_host(text: str) -> str:
    import re

    full = re.escape(CHARACTER["name"])
    first = re.escape(CHARACTER["name"].split()[0])
    text = re.sub(full + r"'?s?", "the narrator", text)
    text = re.sub(r"\b" + first + r"'s\b", "our", text)
    return re.sub(r"\b" + first + r"\b", "the narrator", text)


def package_prompt(v: store.Video, script: dict) -> str:
    lines = [l["text"] for s in script["sections"] for l in s["lines"]][:60]  # all of it: titles must match
    kind = "a YouTube Short (vertical, under a minute)" if v.state.get("short") else "a YouTube video"
    return f"""Write packaging for {kind} on a made-for-kids channel ({section('channel').get('name')}).
Topic: {v.state['topic']}
Script: {json.dumps(lines)}

Rules: honest, and true to the whole script (name what really appears), simple, parent-friendly. Titles 50-70 characters: the topic plus "for Toddlers" or "for Kids".
At most 2 hashtags in total{', one of them #Shorts' if v.state.get('short') else ''}. Never name another channel,
brand or character. No claims about making children smarter.

Return JSON: {{
 "titles": [3 options, 50-70 characters],
 "thumbnail_text": [3 options, 2-4 words each],
 "description": "2 short paragraphs for parents: what the child will see and do",
 "tags": [8-12 tags],
 "pinned_comment": ""
}}"""


def checks(v: store.Video, script: dict, cfg: dict) -> list[dict]:
    from .checks import copying, kids_safety, timing

    own = [o.read("script.md") or "" for o in store.all_videos() if o.id != v.id and o.path("script.md").exists()][-30:]
    refs = v.read("reference_transcripts.json")
    if refs is None:
        refs = copying.fetch_transcripts(v.state.get("reference_videos", []))
        v.write("reference_transcripts.json", refs)
    fmt = video_format(v)
    speed = v.state.get("voice_speed")
    base = section("languages").get("en", {}).get("speed", 1.0) or 1.0
    wpm = int(fmt["words_per_minute"] * (speed / base if speed else 1))  # slower voice: fewer words per minute
    traditional = [p.read_text(encoding="utf-8") for p in sorted((ROOT / "config" / "traditional").glob("*.txt"))]
    return [timing.check(script, fmt["target_minutes"], wpm),
            copying.check(script, [], own, refs, traditional=traditional),
            kids_safety.check(script, characters=ready_characters())]


# ---------- pictures ----------

def cutout(img: Image.Image, max_saturation: int = 48) -> Image.Image:
    """Removes a plain grey/white studio background: greyish pixels connected to the image edge.
    The character is all saturated colour, so the gradient and floor go but his eye highlights stay."""
    rgb = img.convert("RGB")
    grey = rgb.convert("HSV").getchannel("S").point(lambda v: 255 if v <= max_saturation else 0)
    w, h = grey.size
    edge = [(x, y) for x in range(0, w, 8) for y in (0, h - 1)] + [(x, y) for y in range(0, h, 8) for x in (0, w - 1)]
    for xy in edge:
        if grey.getpixel(xy) == 255:
            ImageDraw.floodfill(grey, xy, 128)
    mask = grey.point(lambda v: 0 if v == 128 else 255)
    # keep only the shape in the middle (the character), not floor specks touching his feet:
    # thin bridges are cut first (opening), then the edges are given back from the original mask
    opened = mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MaxFilter(9))
    box = opened.getbbox()
    centre = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    if opened.getpixel(centre) == 255:
        ImageDraw.floodfill(opened, centre, 200)
        body = opened.point(lambda v: 255 if v == 200 else 0).filter(ImageFilter.MaxFilter(7))
        mask = Image.composite(mask, Image.new("L", mask.size, 0), body)
    mask = mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.5))
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out.crop(mask.point(lambda v: 255 if v > 128 else 0).getbbox())


def sprite(key: str | None = None, pose: str | None = None) -> Image.Image:
    """A character's cut-out (the host by default). Made once from the fixed description and seed,
    then reused for every video. `pose` picks one of its `poses:` cut-outs when it has them."""
    c = character(key)
    poses = c.get("poses") or {}
    if pose and pose in poses and (ROOT / poses[pose]).exists():
        return Image.open(ROOT / poses[pose]).convert("RGBA")
    path = ROOT / c["sprite"]
    if not path.exists():
        from .media import ai_images

        raw = ai_images.generate(c["description"], path.with_suffix(".raw.png"), 1024, 1024, style=c["style"],
                                 negative=SCENE_NEGATIVE, seed=int(c["seed"]))
        if raw is None:
            raise RuntimeError("Kids mode needs the local AI image model (or AI_IMAGE_URL) to draw the host once.")
        cutout(Image.open(raw)).save(path)
    return Image.open(path).convert("RGBA")


def place_host(scene: Image.Image, host: Image.Image, n: int) -> Image.Image:
    """Host standing at the bottom, alternating sides, with a soft shadow."""
    W, H = scene.size
    vertical = H > W
    target_h = int(H * (0.36 if vertical else 0.62))
    s = host.resize((int(host.width * target_h / host.height), target_h), Image.LANCZOS)
    left = n % 2 == 0
    if not left:
        s = s.transpose(Image.FLIP_LEFT_RIGHT)  # faces into the picture from the other side
    margin = int(W * 0.04)
    x = margin if left else W - s.width - margin
    y = H - s.height - int(H * 0.03)
    out = scene.convert("RGBA")
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([x + s.width * 0.1, y + s.height * 0.93, x + s.width * 0.9, y + s.height * 1.03],
                                   fill=(0, 0, 0, 70))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    out.alpha_composite(s, (x, y))
    return out if scene.mode == "RGBA" else out.convert("RGB")


def cutout_key(img: Image.Image, tolerance: int = 70) -> Image.Image:
    """Cut-out for a subject drawn on a plain coloured backdrop (any colour, so white sheep work):
    pixels close to the edge colour and connected to the edge are removed, then specks."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(xy) for xy in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3), (w // 2, 2))]
    key = tuple(sorted(c[i] for c in corners)[2] for i in range(3))  # median corner colour
    dist = Image.merge("RGB", [rgb.getchannel(i).point(lambda v, k=key[i]: abs(v - k)) for i in range(3)])
    near = dist.convert("L").point(lambda v: 255 if v * 1.8 < tolerance else 0)
    for xy in [(x, y) for x in range(0, w, 8) for y in (0, h - 1)] + [(x, y) for y in range(0, h, 8) for x in (0, w - 1)]:
        if near.getpixel(xy) == 255:
            ImageDraw.floodfill(near, xy, 128)
    mask = near.point(lambda v: 0 if v == 128 else 255)
    opened = mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.MaxFilter(9))
    box = opened.getbbox()
    if box:
        centre = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        if opened.getpixel(centre) == 255:
            ImageDraw.floodfill(opened, centre, 200)
            body = opened.point(lambda v: 255 if v == 200 else 0).filter(ImageFilter.MaxFilter(7))
            mask = Image.composite(mask, Image.new("L", mask.size, 0), body)
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out.crop(mask.point(lambda v: 255 if v > 128 else 0).getbbox() or (0, 0, w, h))


def main_shape(rgba: Image.Image) -> tuple[Image.Image, float]:
    """Keeps the largest solid shape of a cut-out (drops faint leftovers and stray bits).
    Returns the cleaned cut-out and how much of the visible area that shape is (1.0 = one subject;
    low = a pattern of many small copies, which happens with some prompts)."""
    import numpy as np
    from scipy import ndimage

    a = np.array(rgba.getchannel("A"))
    solid = a > 128
    labels, n = ndimage.label(ndimage.binary_opening(solid, iterations=2))
    if n == 0:
        return rgba, 0.0
    sizes = ndimage.sum(solid, labels, range(1, n + 1))
    keep = labels == (int(np.argmax(sizes)) + 1)
    keep = ndimage.binary_dilation(keep, iterations=4) & (a > 10)
    share = float(sizes.max() / max(solid.sum(), 1))
    out = rgba.copy()
    out.putalpha(Image.fromarray(np.where(keep, a, 0).astype("uint8")))
    box = out.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    return (out.crop(box) if box else out), share


def cut_subject(img: Image.Image) -> tuple[Image.Image, float]:
    """Background removal with a local segmentation model (rembg, isnet-general-use), then main_shape."""
    from rembg import new_session, remove

    if not hasattr(cut_subject, "session"):
        cut_subject.session = new_session("isnet-general-use")
    return main_shape(remove(img.convert("RGB"), session=cut_subject.session))


def seed_for(name: str) -> int:
    import hashlib

    return int(hashlib.sha1(name.lower().encode()).hexdigest()[:6], 16)


PLACE_STYLE = SCENE_STYLE + ", wide empty scene, no animals, no people, plenty of open ground in the foreground"
PLACE_NEGATIVE = SCENE_NEGATIVE + ", animal, animals, people, person, child, cow, pig, sheep, horse, bird"
CAST_STYLE = (", one single character, full body, side-front view, standing, centered, on a plain flat solid "
              "sky blue background, soft 3D cartoon render for toddlers, cute, friendly, pastel colours")
CAST_NEGATIVE = (SCENE_NEGATIVE + ", grass, ground, floor, shadow, scenery, two, multiple, group, flock, crowd, "
                 "pattern, wallpaper, seamless, repeated, tiled, sticker sheet, blue animal")


def place_image(v: store.Video, name: str, look: str, w: int, h: int) -> Path:
    from .media import ai_images

    out = v.path(f"media/place_{store.slugify(name, 30)}.png")
    if not out.exists():
        if ai_images.generate(look, out, w, h, style=PLACE_STYLE, negative=PLACE_NEGATIVE, seed=seed_for(name)) is None:
            raise RuntimeError("Kids mode needs the local AI image model (or AI_IMAGE_URL).")
    return out


def cast_sprite(v: store.Video, name: str, look: str, drafts: int) -> Path:
    """One cut-out per cast member: best of `drafts` by CLIP, then reused in every shot."""
    from .media import ai_images, vision

    out = v.path(f"media/cast_{store.slugify(name, 30)}.png")
    if out.exists():
        return out
    cuts = []  # (cut-out, share of one shape, raw path)
    k = 0
    while k < max(1, drafts) or (k < drafts + 3 and not any(sh >= 0.85 for _, sh, _ in cuts)):
        raw = out.with_name(f"{out.stem}.raw{k}.png")
        if not raw.exists() and ai_images.generate(f"one cute cartoon {name}, {look}", raw, 1024, 1024, style=CAST_STYLE,
                                                   negative=CAST_NEGATIVE, seed=seed_for(name) + 1000 * k) is None:
            raise RuntimeError("Kids mode needs the local AI image model (or AI_IMAGE_URL).")
        cut, share = cut_subject(Image.open(raw))
        cuts.append((cut, share, raw))
        k += 1
    single = [c for c in cuts if c[1] >= 0.85] or sorted(cuts, key=lambda c: -c[1])[:1]
    if len(single) > 1:  # several clean drafts: the one that looks most like the animal
        scores = vision.clip_scores([c[2] for c in single], f"a cute cartoon {name}")
        if scores:
            single = [single[max(range(len(single)), key=lambda i: scores[i])]]
    single[0][0].save(out)
    return out


SIZES = {"big": 0.62, "medium": 0.5, "small": 0.36}
SKY_WORDS = ("sun", "moon", "star", "cloud", "rainbow")


def in_sky(name: str, c) -> bool:
    pos = c.get("position") if isinstance(c, dict) else None
    return pos == "sky" if pos else any(w in name.lower() for w in SKY_WORDS)


def drawn_rainbow(w: int = 1600) -> Image.Image:
    """A clean pastel rainbow with soft clouds at its feet (image models smear rainbows)."""
    band = w // 22
    top = w // 12
    foot = top + w // 2  # where the outer arc meets the ground line
    h = foot + band * 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bands = [(255, 120, 120), (255, 180, 100), (255, 225, 110), (140, 215, 140), (120, 180, 235), (170, 140, 220)]
    for k, c in enumerate(bands):
        r = w // 2 - band - k * band
        d.arc([w // 2 - r, foot - r, w // 2 + r, foot + r], 180, 360, fill=c + (235,), width=band)
    clouds = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(clouds)
    for cx in (band * 4, w - band * 4):  # round puffy clouds where the arc meets the ground
        puffs = [(-1.6, 0.5, 1.0), (-0.6, -0.3, 1.35), (0.7, -0.1, 1.2), (1.7, 0.55, 0.9), (0, 0.6, 1.1)]
        for shade, off in (((225, 228, 240, 255), 0.18), ((255, 255, 255, 255), 0)):
            for dx, dy, rr in puffs:
                x, y, rad = cx + dx * band, foot - band * 0.5 + (dy + off) * band, rr * band
                cd.ellipse([x - rad, y - rad, x + rad, y + rad], fill=shade)
    img.alpha_composite(clouds.filter(ImageFilter.GaussianBlur(2)))
    return img.filter(ImageFilter.GaussianBlur(1))


def drawn_stars(w: int = 1600, count: int = 7, seed: int = 3) -> Image.Image:
    """A scatter of soft glowing five-point stars (image models draw 'little stars' as blurry blobs)."""
    import math

    h = w // 3
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rnd = random.Random(seed)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd, d = ImageDraw.Draw(glow), ImageDraw.Draw(img)
    for k in range(count):
        cx = w * (k + 0.5) / count + rnd.uniform(-w / count / 4, w / count / 4)
        cy = rnd.uniform(h * 0.25, h * 0.75)
        r = rnd.uniform(w / 60, w / 34)
        pts = [(cx + (r if i % 2 == 0 else r * 0.45) * math.cos(math.pi / 2 + i * math.pi / 5),
                cy - (r if i % 2 == 0 else r * 0.45) * math.sin(math.pi / 2 + i * math.pi / 5)) for i in range(10)]
        gd.ellipse([cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2], fill=(255, 240, 170, 70))
        d.polygon(pts, fill=(255, 226, 110, 255))
    out = glow.filter(ImageFilter.GaussianBlur(w / 80))
    out.alpha_composite(img.filter(ImageFilter.GaussianBlur(0.8)))
    return out


def drawn_moon(size: int = 700) -> Image.Image:
    """A soft smiling crescent moon with sleepy closed eyes and a gentle glow."""
    S = size
    body = Image.new("L", (S, S), 0)
    bd = ImageDraw.Draw(body)
    m = S // 10
    bd.ellipse([m, m, S - m, S - m], fill=255)
    bd.ellipse([m + S // 3, m - S // 12, S - m + S // 3, S - m - S // 12], fill=0)  # bite out of the right side
    body = body.filter(ImageFilter.GaussianBlur(2))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow = Image.new("RGBA", (S, S), (255, 240, 180, 0))
    glow.putalpha(body.filter(ImageFilter.GaussianBlur(S / 18)).point(lambda v: int(v * 0.45)))
    out.alpha_composite(glow)
    face = Image.new("RGBA", (S, S), (255, 228, 130, 255))
    out.alpha_composite(Image.composite(face, Image.new("RGBA", (S, S), (0, 0, 0, 0)), body))
    d = ImageDraw.Draw(out)
    ink = (120, 85, 40, 255)
    ex, ey = int(S * 0.30), int(S * 0.42)  # one sleepy eye and a smile, on the fat part of the crescent
    d.arc([ex - S // 16, ey - S // 28, ex + S // 16, ey + S // 28], 10, 170, fill=ink, width=max(3, S // 90))
    d.arc([ex - S // 10, int(S * 0.52), ex + S // 12, int(S * 0.64)], 20, 160, fill=ink, width=max(3, S // 90))
    d.ellipse([ex - S // 9, int(S * 0.5), ex - S // 22, int(S * 0.55)], fill=(255, 170, 150, 160))  # rosy cheek
    return out


def add_sky(img: Image.Image, items: list[Image.Image], n: int, big: tuple = ()) -> Image.Image:
    """Sun, moon, stars, clouds: floating in the upper part of the picture, not standing on the floor.
    Items listed in `big` (e.g. a rainbow) span much of the sky."""
    W, H = img.size
    out = img.convert("RGBA")
    for s in big:
        bw = int(W * 0.5)
        s = s.resize((bw, int(s.height * bw / s.width)), Image.LANCZOS)
        out.alpha_composite(s, ((W - bw) // 2, int(H * 0.02)))
    for k, s in enumerate(items):
        th = int(H * (0.26 if len(items) == 1 else 0.18))
        s = s.resize((max(1, int(s.width * th / s.height)), th), Image.LANCZOS)
        slots = [0.72, 0.28, 0.5, 0.88, 0.12]
        x = int(W * slots[(k + n) % len(slots)] - s.width / 2)
        out.alpha_composite(s, (max(0, min(W - s.width, x)), int(H * (0.06 + 0.05 * (k % 2)))))
    return out if img.mode == "RGBA" else out.convert("RGB")


def silhouette(img: Image.Image) -> Image.Image:
    """The animal as a soft dark shadow shape, for "guess who?" moments before the reveal."""
    a = img.getchannel("A").point(lambda v: int(v * 0.85))
    out = Image.new("RGBA", img.size, (70, 45, 110, 0))
    out.putalpha(a)
    return out


def compose(bg: Image.Image, sprites: list[tuple[Image.Image, str]], n: int, size: tuple[int, int]) -> Image.Image:
    """Cast cut-outs standing on the ground of a place, spread evenly, with soft shadows.
    More than 4: two rows, the bigger animals at the back."""
    W, H = size
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    out = bg.crop((left, top, left + W, top + H)).convert("RGBA")
    keep = bg.mode == "RGBA"  # transparent background: an overlay for an animated place
    if not sprites:
        return out if keep else out.convert("RGB")
    if len(sprites) > 4:
        order = sorted(sprites, key=lambda s: -SIZES.get(s[1], 0.5))
        back, front = order[:len(order) // 2], order[len(order) // 2:]
        out = _row(out, back, n, 0.62, 0.80, W, H)
        out = _row(out, front, n, 0.62, 0.97, W, H)
        return out if keep else out.convert("RGB")
    out = _row(out, sprites, n, 1.0 if len(sprites) <= 2 else 0.75, 0.94, W, H)
    return out if keep else out.convert("RGB")


def _row(out: Image.Image, sprites: list, n: int, crowd: float, ground_at: float, W: int, H: int) -> Image.Image:
    scaled = []
    for img, sz in sprites:
        th = int(H * SIZES.get(sz, 0.5) * crowd)
        scaled.append(img.resize((max(1, int(img.width * th / img.height)), th), Image.LANCZOS))
    total = sum(s.width for s in scaled)
    if total > W * 0.9:  # still too wide: shrink the whole row
        f = W * 0.9 / total
        scaled = [s.resize((max(1, int(s.width * f)), max(1, int(s.height * f))), Image.LANCZOS) for s in scaled]
        total = sum(s.width for s in scaled)
    gap = (W - total) / (len(scaled) + 1)
    x = gap if len(scaled) > 1 else (W - total) / 2 + (W * 0.12 if n % 2 else -W * 0.12)
    ground = H * ground_at
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    for s in scaled:
        ImageDraw.Draw(shadow).ellipse([x + s.width * 0.12, ground - s.height * 0.05, x + s.width * 0.88,
                                        ground + s.height * 0.04], fill=(0, 0, 0, 60))
        x += s.width + gap
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    x = gap if len(scaled) > 1 else (W - total) / 2 + (W * 0.12 if n % 2 else -W * 0.12)
    for s in scaled:
        out.alpha_composite(s, (int(x), int(ground - s.height)))
        x += s.width + gap
    return out


def sticker_scenes(v: store.Video, timeline: list[dict], script: dict, size: tuple[int, int], drafts: int) -> dict:
    """Shot image per line from the script's places and cast."""
    w, h = size
    gen = (768, 1344) if h > w else (1344, 768)
    places = {k: place_image(v, k, look, *gen) for k, look in (script.get("places") or {}).items()}
    cast = script.get("cast") or {}
    recurring = ready_characters()
    rainbow, stars, moon = drawn_rainbow(), drawn_stars(), drawn_moon()
    sprites = {k: (Image.open(cast_sprite(v, k, c.get("look", "") if isinstance(c, dict) else str(c), drafts)),
                   c.get("size", "medium") if isinstance(c, dict) else "medium")
               for k, c in cast.items()
               if k.lower() not in recurring and "rainbow" not in k.lower() and not k.lower().endswith("stars")
               and "moon" not in k.lower()}
    host_c = character(v.state.get("host"))
    host_key = (v.state.get("host") or str(channel().get("host", "character"))).lower()
    lines = [l for sec in script["sections"] for l in sec["lines"]]
    out = {}
    for n, t in enumerate(timeline):
        line = lines[t["i"]] if t["i"] < len(lines) else {}
        place_path = places.get(line.get("place")) or next(iter(places.values()))
        loop = place_path.with_suffix(".loop.mp4")
        # animated place: draw the same shot on a transparent layer as well; the render puts it over the loop
        layers = [(Image.open(place_path), None)]
        if loop.exists():
            layers.append((Image.new("RGBA", (w, h), (0, 0, 0, 0)), loop))
        for place, bg_loop in layers:
            img = _shot(v, t, n, line, lines, place, script, cast, sprites, recurring, rainbow, stars, moon, host_c,
                        host_key, w, h)
            if bg_loop is None:
                p = v.path(f"media/kids_{t['i']:03d}.jpg")
                img.convert("RGB").save(p, quality=92)
                out[t["i"]] = p
            else:
                img.save(v.path(f"media/kids_{t['i']:03d}.over.png"))
                v.path(f"media/kids_{t['i']:03d}.loop.txt").write_text(str(bg_loop))
    return out


def _shot(v, t, n, line, lines, place, script, cast, sprites, recurring, rainbow, stars, moon, host_c, host_key, w, h):
    """One shot: the place with its subjects (or a transparent layer with only the subjects)."""
    if not line.get("subjects"):  # just before a reveal: the coming animal's shadow, to guess
        coming = next((l["subjects"] for l in lines[t["i"] + 1:t["i"] + 6] if l.get("subjects")), [])
        if len(coming) == 1 and coming[0] in sprites and not in_sky(coming[0], cast.get(coming[0])):
            # same spot as the reveal that follows, so the shadow "becomes" the animal
            return compose(place, [(silhouette(sprites[coming[0]][0]), sprites[coming[0]][1])],
                           seed_for(coming[0]), (w, h))
    subs, sky, big_sky = [], [], []
    for s_ in line.get("subjects") or []:
        if s_.lower() in recurring:  # recurring characters: always their own fixed cut-out
            subs.append((sprite(s_.lower(), line.get("pose")), "big"))
        elif "rainbow" in s_.lower():
            big_sky.append(rainbow)
        elif s_.lower().endswith("stars"):  # a group of little stars: drawn, spread across the sky
            big_sky.append(stars)
        elif "moon" in s_.lower():
            sky.append(moon)
        elif s_ in sprites and in_sky(s_, cast.get(s_)):
            sky.append(sprites[s_][0])
        elif s_ in sprites:
            subs.append(sprites[s_])
    names = [x for x in line.get("subjects") or [] if not (x in cast and in_sky(x, cast.get(x)))]
    look = f"{line.get('place', '')} {(script.get('places') or {}).get(line.get('place'), '')}".lower()
    indoors = any(word in look for word in ("bedroom", "bathroom", "kitchen", "room", "indoor", "inside", "house")) and \
        not any(word in look for word in ("seen from the window", "seen from his window", "seen from her window",
                                    "through the window", "view of the sky"))
    img = compose(place, [], n, (w, h))
    if (sky or big_sky) and not indoors:  # a sun or moon floating inside a room looks like a sticker
        img = add_sky(img, sky, n, big=big_sky)  # sky first: characters always stand in front of it
    img = compose(img, subs, seed_for(names[0]) if len(names) == 1 else n, (w, h))
    if host_c and host_key not in [x.lower() for x in names]:  # host already in the shot: not twice
        img = place_host(img, sprite(v.state.get("host"), line.get("pose")), n)
    return img


def best_scene(shot: str, out: Path, w: int, h: int, seed: int, drafts: int) -> Path:
    """Draws `drafts` versions of the scene and keeps the one CLIP thinks shows the shot best."""
    from .media import ai_images, vision

    paths = []
    for k in range(max(1, drafts)):
        p = ai_images.generate(shot, out.with_name(f"{out.stem}.{k}.png"), w, h, style=SCENE_STYLE,
                               negative=SCENE_NEGATIVE, seed=seed + 1000 * k)
        if p is None:
            raise RuntimeError("Kids mode needs the local AI image model (or AI_IMAGE_URL) for cartoon scenes.")
        paths.append(p)
    scores = vision.clip_scores(paths, shot) if len(paths) > 1 else None
    best = paths[max(range(len(paths)), key=lambda k: scores[k])] if scores else paths[0]
    best.replace(out)
    for p in paths:
        p.unlink(missing_ok=True)
    return out


def visuals(v: store.Video, timeline: list[dict]) -> list[dict]:
    w, h = video_format(v).get("resolution", [1920, 1080])
    gen_w, gen_h = (768, 1344) if h > w else (1344, 768)
    host = sprite(v.state.get("host")) if character(v.state.get("host")) else None
    base_seed = random.Random(v.id).randrange(10 ** 6)
    drafts = int(section("visuals").get("kids_drafts", 2))
    script = v.read("script.json") or {}
    stickers = sticker_scenes(v, timeline, script, (w, h), drafts) if script.get("places") and script.get("cast") else {}
    plan, items = [], []
    for n, t in enumerate(timeline):
        out = stickers.get(t["i"]) or v.path(f"media/kids_{t['i']:03d}.jpg")
        bg = v.path(f"media/kids_{t['i']:03d}.bg.png")
        if not out.exists():  # a saved background is reused, so a new host cut-out needs no redraw
            raw = bg if bg.exists() else best_scene(t.get("shot") or t["text"], v.path(f"media/kids_{t['i']:03d}.bg.png"), gen_w, gen_h,
                             base_seed + t["i"], drafts)
            out.parent.mkdir(parents=True, exist_ok=True)
            img = Image.open(raw).convert("RGB")
            (place_host(img, host, n) if host else img).save(out, quality=92)
        shot = {"kind": "image", "url": "", "page_url": "", "title": "Cartoon scene", "author": "channel",
                "licence": "AI generated", "licence_url": "", "source": "AI", "path": str(out)}
        over, loop = v.path(f"media/kids_{t['i']:03d}.over.png"), v.path(f"media/kids_{t['i']:03d}.loop.txt")
        if stickers and over.exists() and loop.exists():  # animated place behind the characters
            shot.update(bg_video=loop.read_text().strip(), overlay=str(over))
        plan.append({"i": t["i"], "start": t["start"], "end": t["end"], "shots": [shot]})
        items.append({k: shot[k] for k in ("source", "title", "author", "licence", "licence_url", "page_url", "path")})
        if not stickers:
            print(f"  cartoon {n + 1}/{len(timeline)}: {t.get('shot', '')[:70]!r}", flush=True)
    v.write("visuals.json", plan)
    v.write("licences.json", items)
    v.update(ai_image_share=1.0 if timeline else 0, missing_visuals=0)
    return plan


# ---------- thumbnails ----------

BRIGHT = [((255, 214, 64), (255, 160, 40)), ((120, 210, 255), (60, 150, 240)), ((255, 140, 180), (240, 90, 140))]
CALM = [((40, 50, 110), (15, 20, 60))]  # bedtime: darker, calmer


def thumbnail(text: str, out: Path, colours: tuple, size=(1280, 720), subject: Image.Image | None = None,
              backdrop: Image.Image | None = None) -> Path:
    from .media.ai_images import font

    W, H = size
    top, bottom = colours
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):  # flat colour with a soft vertical fade
        f = y / H
        px.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * f) for a, b in zip(top, bottom)))
    if backdrop is not None:  # the video's own setting, brightened, instead of a flat colour
        from PIL import ImageEnhance

        img = ImageEnhance.Brightness(compose(backdrop, [], 0, (W, H))).enhance(1.05)
    host = subject if subject is not None else sprite()
    f = min(H * 0.92 / host.height, W * 0.42 / host.width)  # wide subjects leave room for big words
    s = host.resize((int(host.width * f), int(host.height * f)), Image.LANCZOS)
    img = img.convert("RGBA")
    img.alpha_composite(s, (W - s.width - 30, H - s.height - 10))
    d = ImageDraw.Draw(img)
    words = text.upper().split()[:4]
    lines = [" ".join(words[i:i + 2]) for i in range(0, len(words), 2)]
    room = W - s.width - 90
    size_px = 170
    while size_px > 60 and max(d.textlength(l, font=font(size_px)) for l in lines) > room:
        size_px -= 8
    f = font(size_px)
    y = (H - len(lines) * (size_px + 16)) // 2
    for line in lines:
        d.text((50, y), line, font=f, fill=(255, 255, 255), stroke_width=10, stroke_fill=(40, 30, 80))
        y += size_px + 16
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out


def thumbnails(v: store.Video) -> list[Path]:
    package = v.read("package.json") or {}
    texts = package.get("thumbnail_text") or [v.state["topic"][:20]]
    calm = any(k in (v.state.get("structure") or "") for k in ("bedtime", "lullaby"))
    palette = CALM if calm else BRIGHT
    subject = backdrop = None
    if not character(v.state.get("host")):  # no host: the first subject shown on its own, in its own place
        script = v.read("script.json") or {}
        recurring = ready_characters()
        all_lines = [l for s in script.get("sections", []) for l in s["lines"]]
        star = next((k for k in recurring if sum(k in [x.lower() for x in l.get("subjects") or []] for l in all_lines)
                     >= 0.3 * max(len(all_lines), 1)), None)
        if star:  # the channel's character carries most of the video: he is the face of the thumbnail
            first = next(l for l in all_lines if star in [x.lower() for x in l.get("subjects") or []])
            all_lines = [{**first, "subjects": [star]}] + all_lines
        for l in all_lines:
            subs = l.get("subjects") or []
            if len(subs) == 1 and subs[0].lower() in recurring:
                subject = sprite(subs[0].lower(), l.get("pose"))
            elif len(subs) == 1 and v.path(f"media/cast_{store.slugify(subs[0], 30)}.png").exists():
                subject = Image.open(v.path(f"media/cast_{store.slugify(subs[0], 30)}.png")).convert("RGBA")
            if subject is not None:
                place = v.path(f"media/place_{store.slugify(l.get('place') or '', 30)}.png")
                backdrop = Image.open(place) if place.exists() else None
                break
        if subject is None:
            raise RuntimeError("No host and no cast picture for the thumbnail")
    outs = []
    for n, t in enumerate(texts[:3]):
        # first option on the video's own setting, the others on flat bright colours for an A/B test
        bd = backdrop if n == 0 else None
        outs.append(thumbnail(t, v.path(f"thumbnails/thumb_{n + 1}.jpg"), palette[n % len(palette)], subject=subject,
                              backdrop=bd))
    return outs
