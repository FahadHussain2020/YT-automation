"""Looks at every picture with a local vision model (Ollama) before it is used:
does it show what the line is about, is it free of watermarks and burned-in text,
and is it nothing graphic. Videos are checked from a frame one second in."""
import base64
import json
import subprocess
from pathlib import Path

import requests

from ..config import env


def frame_of(path: Path) -> Path:
    if path.suffix.lower() not in (".mp4", ".mov", ".webm", ".mkv", ".ogv"):
        return path
    out = path.with_suffix(".check.jpg")
    if not out.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=768:-2", str(out)], check=True)
    return out


def check(path: Path, line: str, shot: str) -> dict:
    img = base64.b64encode(frame_of(path).read_bytes()).decode()
    prompt = (
        "You check pictures for a documentary video. The narration line is:\n"
        f"\"{line}\"\nThe intended shot: \"{shot}\"\n"
        "Answer JSON with keys: matches (true if the picture fits the line or shot), "
        "watermark (true if a stock watermark or logo is visible), text_heavy (true if large burned-in text), "
        "graphic (true if gore or disturbing content), reason (short)."
    )
    try:
        r = requests.post(env("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/generate", timeout=300, json={
            "model": env("OLLAMA_VISION_MODEL", "llava:13b"), "prompt": prompt, "images": [img],
            "format": "json", "stream": False})
        r.raise_for_status()
        res = json.loads(r.json()["response"])
    except (requests.RequestException, ValueError, KeyError) as e:
        return {"ok": None, "reason": f"vision check unavailable: {e}"}
    ok = bool(res.get("matches")) and not res.get("watermark") and not res.get("graphic") and not res.get("text_heavy")
    return {"ok": ok, **res}


def ollama_up() -> bool:
    try:
        requests.get(env("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=2).raise_for_status()
        return True
    except requests.RequestException:
        return False


def _clip():
    if not hasattr(_clip, "model"):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        name = env("CLIP_MODEL", "openai/clip-vit-base-patch16")
        # CLIP_DEVICE=cpu keeps the GPU free when another model (e.g. SDXL) needs all of it
        device = env("CLIP_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
        _clip.model = CLIPModel.from_pretrained(name).to(device).eval()
        _clip.proc = CLIPProcessor.from_pretrained(name)
        _clip.device = device
    return _clip.model, _clip.proc, _clip.device


def clip_scores(paths: list[Path], text: str) -> list[float] | None:
    """How well each picture matches the text (cosine similarity, roughly 0.15-0.35).
    None when torch/transformers aren't installed."""
    try:
        import torch
        from PIL import Image

        model, proc, device = _clip()
    except ImportError:
        return None
    images, broken = [], set()
    for n, p in enumerate(paths):
        try:
            images.append(Image.open(frame_of(p)).convert("RGB"))
        except Exception:
            images.append(Image.new("RGB", (64, 64)))
            broken.add(n)
    with torch.no_grad():
        inp = proc(text=[text], images=images, return_tensors="pt", padding=True, truncation=True).to(device)
        out = model(**inp)
        img = torch.nn.functional.normalize(out.image_embeds, dim=-1)
        txt = torch.nn.functional.normalize(out.text_embeds, dim=-1)
        scores = (img @ txt.T).squeeze(1).tolist()
    return [-1.0 if n in broken else s for n, s in enumerate(scores)]
