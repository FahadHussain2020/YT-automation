"""AI images, used only as a last resort and always labelled on screen.

Two ways, tried in this order:
  AI_IMAGE_URL     any Stable-Diffusion server that speaks the AUTOMATIC1111 API
                   (/sdapi/v1/txt2img), e.g. Draw Things on Mac. http://127.0.0.1:7860
  local GPU        Stable Diffusion XL through `diffusers` on this machine's NVIDIA GPU,
                   when torch + diffusers are installed (pip install torch diffusers
                   transformers accelerate). AI_IMAGE_MODEL picks the model; the default
                   SDXL base 1.0 licence (CreativeML Open RAIL++-M) allows commercial use.
                   Set AI_IMAGE_PROVIDER=none to switch AI images off.
"""
import base64
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from ..config import env

LABEL = "AI illustration"


STYLE = ", documentary illustration, cinematic lighting, historically plausible, no text, no writing"
NEGATIVE = "text, letters, words, writing, typography, caption, watermark, logo, signature, gore, deformed hands, blurry"


def generate(prompt: str, out: Path, width: int = 1344, height: int = 768, *, style: str = STYLE,
             negative: str = NEGATIVE, seed: int | None = None) -> Path | None:
    url = env("AI_IMAGE_URL")
    if not url:
        return _diffusers(prompt + style, negative, out, width, height, seed)
    r = requests.post(url.rstrip("/") + "/sdapi/v1/txt2img", timeout=600, json={
        "prompt": prompt + style,
        "negative_prompt": negative,
        "width": width, "height": height, "steps": 25, "seed": -1 if seed is None else seed})
    r.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(r.json()["images"][0]))
    return out


def _pipeline():
    if not hasattr(_pipeline, "pipe"):
        import torch
        from diffusers import AutoPipelineForText2Image

        if not torch.cuda.is_available():
            raise RuntimeError("no CUDA GPU for local AI images")
        pipe = AutoPipelineForText2Image.from_pretrained(
            env("AI_IMAGE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0"),
            dtype=torch.float16, variant="fp16", use_safetensors=True)
        pipe.enable_model_cpu_offload()  # fits SDXL in 8 GB of video memory
        _pipeline.pipe = pipe
    return _pipeline.pipe


def _diffusers(prompt: str, negative: str, out: Path, width: int, height: int, seed: int | None) -> Path | None:
    if env("AI_IMAGE_PROVIDER", "auto").lower() == "none":
        return None
    try:
        import diffusers  # noqa: F401
    except ImportError:
        return None
    import torch

    gen = torch.Generator("cpu").manual_seed(seed) if seed is not None else None
    img = _pipeline()(prompt=prompt, negative_prompt=negative, width=width, height=height, generator=gen,
                      num_inference_steps=int(env("AI_IMAGE_STEPS", "28")), guidance_scale=6.5).images[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def title_card(text: str, out: Path, w: int = 1920, h: int = 1080) -> Path:
    """A plain dark card with the title, used when no picture was found for the opening."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):  # soft vertical gradient
        c = int(18 + 22 * y / h)
        for x in range(0, w):
            px[x, y] = (c, c, c + 6)
    d = ImageDraw.Draw(img)
    words, lines, cur = text.split(), [], ""
    f = font(96)
    for word in words:
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=f) > w - 300 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    y = (h - len(lines) * 116) // 2
    for line in lines:
        d.text(((w - d.textlength(line, font=f)) // 2, y), line, font=f, fill=(240, 240, 240))
        y += 116
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out


def font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def label(path: Path) -> Path:
    """Draws "AI illustration" in the corner so viewers always know."""
    img = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(img)
    f = font(max(18, img.width // 60))
    x0, y0, x1, y1 = d.textbbox((0, 0), LABEL, font=f)
    pad = 10
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    d.rectangle([img.width - w - 24, img.height - h - 24, img.width - 24, img.height - 24], fill=(0, 0, 0))
    d.text((img.width - w - 24 + pad, img.height - h - 24 + pad - y0), LABEL, font=f, fill=(255, 255, 255))
    out = path.with_name(path.stem + ".labelled.jpg")
    img.save(out, quality=92)
    return out
