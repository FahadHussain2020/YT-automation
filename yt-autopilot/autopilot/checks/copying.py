"""Copy check. A script fails if it reuses long word runs from:
- the sources (Wikipedia etc.: we retell, we don't recite),
- your own earlier scripts (stops the channel turning repetitive),
- transcripts of the competitor/outlier videos the idea came from.
"""
import re

SHINGLE = 8          # an 8-word run in common counts as copied
MAX_RUN_WORDS = 14   # any single copied run longer than this fails
MAX_SHARE = 0.04     # more than 4% of the script's 8-grams copied fails


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9؀-ۿ']+", text.lower())


def shingles(ws: list[str], n: int = SHINGLE) -> set[tuple]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def longest_run(a: list[str], b_shingles: set[tuple], n: int = SHINGLE) -> tuple[int, str]:
    best, best_at, run = 0, 0, 0
    for i in range(len(a) - n + 1):
        if tuple(a[i:i + n]) in b_shingles:
            run += 1
            if run > best:
                best, best_at = run, i - run + 1
        else:
            run = 0
    length = best + n - 1 if best else 0
    return length, " ".join(a[best_at:best_at + length])


def compare(script_words: list[str], other: str, allowed: set[tuple] = frozenset()) -> dict:
    other_sh = shingles(words(other)) - allowed  # traditional public-domain lyrics are not copying
    mine = shingles(script_words)
    shared = len(mine & other_sh) / len(mine) if mine else 0
    run, sample = longest_run(script_words, other_sh)
    return {"share": round(shared, 4), "longest_run": run, "sample": sample[:160]}


def check(script: dict, sources: list[dict], own_scripts: list[str], reference_transcripts: list[dict],
          traditional: list[str] = ()) -> dict:
    from . import script_text

    sw = words(script_text(script))
    against = [(f"source {s['id']} ({s['title'][:40]})", s["text"]) for s in sources]
    against += [(f"own earlier script #{i + 1}", t) for i, t in enumerate(own_scripts)]
    against += [(f"video {t['video_id']} transcript", t["text"]) for t in reference_transcripts]
    allowed = set().union(*(shingles(words(t)) for t in traditional)) if traditional else set()
    problems, worst = [], 0.0
    for label, text in against:
        r = compare(sw, text, allowed)
        worst = max(worst, r["share"])
        if r["longest_run"] > MAX_RUN_WORDS or r["share"] > MAX_SHARE:
            problems.append(f"Too close to {label}: {r['share']:.1%} shared, run of {r['longest_run']} words: "
                            f"\"{r['sample']}\"")
    return {"name": "copying", "passed": not problems, "score": worst, "problems": problems,
            "compared_against": len(against)}


def fetch_transcripts(video_ids: list[str], languages=("en",)) -> list[dict]:
    """Transcripts of the reference videos (competitor research caches them first).
    Missing ones are skipped quietly."""
    import json

    from .. import config

    out, todo = [], []
    for vid in video_ids:
        cache = config.DATA / "competitors" / "transcripts" / f"{vid}.json"
        cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
        if cached and cached.get("text"):
            out.append({"video_id": vid, "text": cached["text"]})
        elif cached is None:
            todo.append(vid)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return out
    api = YouTubeTranscriptApi()
    for vid in todo:
        try:
            t = api.fetch(vid, languages=list(languages))
            out.append({"video_id": vid, "text": " ".join(s.text for s in t)})
        except Exception:
            continue
    return out
