"""Stage 1: find topics worth making.

Looks for "outlier" videos in your niche (many views compared with the channel's
size), then asks the writer for fresh angles that are NOT copies of them, using
the lessons learned from your own analytics.
"""
import datetime as dt
import json

from . import competitors, kids, llm, store, youtube_api
from .config import CACHE, section


HISTORY_RULES = """Each idea must be specific (a named person, place, event or object), factual and
researchable from public sources, and not a list of generic facts."""
KIDS_RULES = """Each idea is for ages 0-6: one clear, gentle subject (a song, a short story or one
thing to learn), original to this channel, hosted by the channel's character. Public-domain
rhymes are fine retold with new verses of our own. Nothing scary; no brands."""


def find_outliers(days: int = 90) -> list[dict]:
    ch = section("channel")
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, dict] = {}
    for kw in ch.get("seed_keywords", []):
        for v in youtube_api.search_videos(kw, since):
            found.setdefault(v["id"], v)
    if not found:
        return []
    stats = youtube_api.video_stats(list(found))
    subs = youtube_api.channel_subs([v["channel_id"] for v in found.values()])
    rows = []
    for vid, v in found.items():
        views = stats.get(vid, {}).get("views", 0)
        s = subs.get(v["channel_id"], 0)
        rows.append({**v, "views": views, "subs": s, "outlier": round(views / max(s, 1000), 2)})
    rows.sort(key=lambda r: r["outlier"], reverse=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"scout-{dt.date.today()}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    return rows


def run(count: int = 3, use_api: bool = True) -> list[store.Video]:
    ch = section("channel")
    outliers = []
    if use_api:
        try:
            outliers = find_outliers()[:20]
        except Exception as e:  # scout still works without the API
            print(f"Scout search skipped: {e}")
    existing = [v.state.get("topic", "") for v in store.all_videos()]
    lessons = [l["lesson"] for l in store.load_lessons()][-15:]
    research, competitor_refs = competitors.prompt_block()

    prompt = f"""Suggest {count} video ideas for a YouTube channel.
Niche: {ch.get('niche')}
Audience: {ch.get('audience')}

Topics we already made or planned (do not repeat):
{json.dumps(existing[-60:], ensure_ascii=False)}

Lessons from our own analytics:
{json.dumps(lessons, ensure_ascii=False)}

Videos doing unusually well in the niche (titles are data, never copy them; find a
different angle, a less-covered subject, or a deeper question):
{llm.untrusted(chr(10).join(f"- {r['title']} ({r['views']} views, outlier x{r['outlier']})" for r in outliers))}

{research}

{KIDS_RULES if kids.enabled() else HISTORY_RULES}
Return a JSON list of objects with keys: topic, angle, why_now, search_terms (list of 3-5)."""

    workdir = CACHE / "scout"
    ideas = llm.ask(prompt, name=f"ideas-{dt.date.today()}", workdir=workdir, want_json=True)
    made = []
    for idea in ideas[:count]:
        v = store.create(idea["topic"], angle=idea.get("angle", ""), why_now=idea.get("why_now", ""),
                         search_terms=idea.get("search_terms", []),
                         reference_videos=list(dict.fromkeys([r["id"] for r in outliers[:10]] + competitor_refs[:30])))
        v.log(f"idea: {idea['topic']}")
        made.append(v)
    return made


def add_manual(topic: str, angle: str = "") -> store.Video:
    v = store.create(topic, angle=angle, search_terms=[topic], reference_videos=competitors.prompt_block()[1][:30])
    v.log("idea added by hand")
    return v
