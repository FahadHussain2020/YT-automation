"""Stage 3: voice, visuals, render, thumbnails, final description."""
from . import media, render, thumbnail, tts
from .config import section
from .media import licences
from .store import Video


def build_description(v: Video) -> str:
    package = v.read("package.json") or {}
    sources = v.read("sources.json") or []
    chs = v.read("chapters.json") or []
    parts = [package.get("description", "").strip()]
    if chs:
        parts.append(render.chapter_text(chs))
    if sources:
        parts.append("Sources:\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in sources if s.get("url")))
    from . import kids

    credits = licences.description_block(v.read("licences.json") or [], labelled=not kids.enabled())
    own_music = [i["title"] for i in v.read("licences.json") or [] if i.get("kind") == "audio" and i.get("source") == "local"]
    if own_music:
        credits = (credits + "\n\n" if credits else "") + "Music: " + "; ".join(own_music) + "."
    if credits:
        parts.append(credits)
    if v.state.get("own_voice_share", 0) < 1:
        parts.append("Narration uses a synthetic voice" +
                     (" together with the creator's own commentary." if v.state.get("own_voice_share", 0) > 0 else "."))
    return "\n\n".join(p for p in parts if p)


def run(v: Video, lang: str = "en") -> None:
    timeline = tts.run(v, lang)
    plan = v.read("visuals.json") if v.path("visuals.json").exists() else media.run(v, timeline)
    render.run(v, plan, timeline, lang)
    thumbnail.run(v)
    v.write("description.txt", build_description(v))
    for other, cfg in section("languages").items():
        if other != lang and cfg.get("enabled") and v.path(f"script_{other}.json").exists():
            other_tl = tts.run(v, other)
            render.run(v, plan, other_tl, other)
    v.set_stage("produced")
