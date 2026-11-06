"""Thumbnails: a real photo from the video, darkened, with 2-4 big words.
Makes one per thumbnail_text option so you can pick (or A/B test in YouTube Studio)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .media.ai_images import font
from .store import Video

W, H = 1280, 720


def make(photo: Path | None, text: str, out: Path) -> Path:
    if photo and photo.exists():
        img = Image.open(photo).convert("RGB")
        scale = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
        left, top = (img.width - W) // 2, (img.height - H) // 2
        img = img.crop((left, top, left + W, top + H))
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = ImageEnhance.Brightness(img).enhance(0.7)
    else:
        img = Image.new("RGB", (W, H), (20, 20, 24))
    d = ImageDraw.Draw(img)
    words = text.upper().split()
    lines = [" ".join(words[i:i + 2]) for i in range(0, len(words), 2)]
    size = 150 if max(len(l) for l in lines) <= 10 else 110
    f = font(size)
    y = H - 60 - len(lines) * (size + 10)
    for line in lines:
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((64, y + 6), line, font=f, fill=(0, 0, 0, 220))
        img.paste(shadow.filter(ImageFilter.GaussianBlur(6)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(6)))
        d.text((60, y), line, font=f, fill=(255, 214, 0), stroke_width=6, stroke_fill=(0, 0, 0))
        y += size + 10
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90, optimize=True)
    return out


def run(v: Video) -> list[Path]:
    from . import kids

    if kids.enabled():
        return kids.thumbnails(v)
    package = v.read("package.json") or {}
    texts = package.get("thumbnail_text") or [v.state["topic"][:24]]
    stills = [Path(s["path"]) for p in (v.read("visuals.json") or []) for s in p["shots"]
              if s["kind"] == "image" and s["source"] != "AI"]
    stills = list(dict.fromkeys(stills))
    if len(stills) > 1:  # the stills that best show the topic make the best thumbnails
        from .media import vision

        scores = vision.clip_scores(stills, f"a striking photo of {v.state['topic']}")
        if scores:
            stills = [p for _, p in sorted(zip(scores, stills), key=lambda x: -x[0])]
    outs = []
    for n, t in enumerate(texts[:3]):
        photo = stills[n % len(stills)] if stills else None
        outs.append(make(photo, t, v.path(f"thumbnails/thumb_{n + 1}.jpg")))
    return outs
