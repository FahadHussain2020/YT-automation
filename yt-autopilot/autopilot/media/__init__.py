"""Picks one or more visuals per narration line and records their licences."""
import itertools
import math
import re

import requests
from pathlib import Path

from ..config import section
from ..store import Video
from . import ai_images, footage, licences, vision


# never generated: pages of text (image models write gibberish letters) and real people
# (an invented face for a named person misleads viewers)
TEXTY = re.compile(r"\b(document|newspaper|headline|report|letter|page|certificate|map|chart|sign|poster|"
                   r"clipping|record|ledger|transcript|text|caption|telegram|form|portrait|memorial|"
                   r"headshot|likeness)s?\b", re.I)


def choose(pool: list[dict], need: int, t: dict, use_ollama: bool, use_clip: bool, min_score: float) -> list[dict]:
    """Keeps the pictures that show what the line is about, best first.

    Ollama running: its vision model judges each picture (also rejects watermarks, gore).
    Otherwise CLIP on this machine scores picture against the intended shot, and weak
    matches are dropped so an AI image or the previous shot is used instead.
    Neither available: candidates are used in search order."""
    own = [c for c in pool if c["source"] == "local"][:need]  # your own media always wins
    pool, need = [c for c in pool if c["source"] != "local"], need - len(own)
    if need <= 0:
        return own
    return own + _best(pool, need, t, use_ollama, use_clip, min_score)


def _best(pool: list[dict], need: int, t: dict, use_ollama: bool, use_clip: bool, min_score: float) -> list[dict]:
    if use_ollama:
        out = []
        for c in pool:
            verdict = vision.check(Path(c["path"]), t["text"], t.get("shot", ""))
            if verdict.get("ok") is not False:
                out.append({**c, "vision": verdict})
            if len(out) >= need:
                break
        return out
    scores = vision.clip_scores([Path(c["path"]) for c in pool], t.get("shot") or t["text"]) if use_clip and pool else None
    if scores is None:
        return pool[:need]
    ranked = sorted(zip(scores, pool), key=lambda x: -x[0])
    return [{**c, "vision": {"clip": round(s, 3)}} for s, c in ranked if s >= min_score][:need]


def run(v: Video, timeline: list[dict]) -> list[dict]:
    from .. import kids

    if kids.enabled():  # cartoon scenes with the channel's host in every shot
        return kids.visuals(v, timeline)
    vis = section("visuals")
    order = vis.get("source_order", ["wikimedia", "internet_archive", "pexels", "pixabay", "local", "ai"])
    max_still = vis.get("max_still_seconds", 6)
    used_urls: set[str] = set()
    plan, ai_count = [], 0
    try:  # pictures on the source articles: usually the most relevant real photos there are
        topic_pics = footage.wikipedia_images([x["title"] for x in v.read("sources.json") or []])
    except (requests.RequestException, ValueError, KeyError) as e:
        v.log(f"wikipedia images failed: {e}")
        topic_pics = []
    use_ollama = vis.get("vision_check", True) and vision.ollama_up()
    use_clip = vis.get("clip_match", True) and not use_ollama
    min_score = float(vis.get("clip_min_score", 0.22))
    for t in timeline:
        dur = t["end"] - t["start"]
        need = max(1, math.ceil(dur / max_still))  # long lines get several shots
        picks = []
        query = t.get("search") or t.get("shot") or v.state["topic"]
        providers = [o for o in order if o not in ("local", "ai")]
        candidates = itertools.chain(footage.local(v.dir, t["i"]) if "local" in order else [],
                                     [c for c in topic_pics if c["url"] not in used_urls][:3],
                                     footage.search(query, providers),
                                     # a narrower query often fails; the topic itself rarely does
                                     footage.search(" ".join(query.split()[:2]), providers))
        pool = []  # downloaded candidates; the best matches are picked from these
        for c in candidates:
            if len(pool) >= max(need * 3, 6):
                break
            if c["url"] in used_urls or any(c["url"] == q["url"] for q in pool):
                continue
            try:
                path = footage.download(c, v.path("media"))
            except Exception as e:
                v.log(f"download failed {c['url']}: {e}")
                continue
            pool.append({**c, "path": str(path)})
        picks = choose(pool, need, t, use_ollama, use_clip, min_score)
        used_urls.update(p["url"] for p in picks)
        allowed_ai = int(vis.get("max_ai_image_share", 0.25) * len(timeline))
        if not picks and "ai" in order and ai_count < allowed_ai and not TEXTY.search(t.get("shot", "")):
            try:
                p = ai_images.generate(t.get("shot") or t["text"], v.path(f"media/ai_{t['i']:03d}.png"))
            except Exception as e:
                v.log(f"AI image failed for line {t['i']}: {e}")
                p = None
            if p:
                if vis.get("label_ai_images", True):
                    p = ai_images.label(p)
                ai_count += 1
                picks.append({"kind": "image", "url": "", "page_url": "", "title": "AI illustration", "author": "AI",
                              "licence": "AI generated", "licence_url": "", "source": "AI", "path": str(p)})
        if not picks:  # nothing for this line: the best unused picture of the topic itself
            pool = []
            for term in [v.state["topic"], *v.state.get("search_terms", [])][:3]:
                for c in itertools.chain(topic_pics, footage.search(term, providers)):
                    if len(pool) >= 8:
                        break
                    if c["url"] in used_urls or c["kind"] != "image" or any(c["url"] == q["url"] for q in pool):
                        continue
                    try:
                        pool.append({**c, "path": str(footage.download(c, v.path("media")))})
                    except Exception:
                        continue
                if len(pool) >= 8:
                    break
            picks = choose(pool, 1, t, use_ollama, use_clip, min_score - 0.04)
            used_urls.update(p["url"] for p in picks)
        if not picks and not plan:  # nothing to fall back on yet: open on a title card
            card = ai_images.title_card(v.state["topic"], v.path("media/title_card.jpg"))
            picks.append({"kind": "image", "url": "", "page_url": "", "title": "Title card", "author": "channel",
                          "licence": "Own work by channel", "licence_url": "", "source": "local", "path": str(card)})
        plan.append({"i": t["i"], "start": t["start"], "end": t["end"], "shots": picks})
        print(f"  visuals {len(plan)}/{len(timeline)}: {len(picks)} shot(s) for {query!r}", flush=True)
        if not picks:
            v.log(f"line {t['i']}: no visual found for {query!r}; add media_local/line_{t['i']:03d}.jpg or it reuses the previous shot")
    used = [s for p in plan for s in p["shots"]]
    v.write("visuals.json", plan)
    v.write("licences.json", [{k: s[k] for k in ("source", "title", "author", "licence", "licence_url", "page_url", "path")}
                              for s in used])
    v.update(ai_image_share=round(ai_count / max(len(timeline), 1), 3),
             missing_visuals=sum(1 for p in plan if not p["shots"]))
    return plan


__all__ = ["run", "licences"]
