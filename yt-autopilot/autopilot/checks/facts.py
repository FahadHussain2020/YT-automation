"""Fact check: every factual line cites a real source, and every number or year in
the line also appears in a cited source. Lines without facts (opinion, transitions)
are marked "kind": "opinion" or "transition" by the writer and skipped."""
import re

NUM = re.compile(r"\b\d[\d,.]*\b")


def _numbers(text: str) -> set[str]:
    out = set()
    for n in NUM.findall(text):
        n = n.rstrip(".,").replace(",", "")
        if n and not (len(n) == 1 and n in "0123456789"):  # single digits are too common to check
            out.add(n)
    return out


def check(script: dict, sources: list[dict]) -> dict:
    from . import lines

    by_id = {s["id"]: s for s in sources}
    source_numbers = {sid: _numbers(s["text"]) for sid, s in by_id.items()}
    problems, factual, ok = [], 0, 0
    for sec, line in lines(script):
        if line.get("kind") in ("opinion", "transition", "commentary"):
            continue
        factual += 1
        cites = line.get("sources") or []
        bad = [c for c in cites if c not in by_id]
        if not cites:
            problems.append(f"No source: \"{line['text'][:90]}\"")
            continue
        if bad:
            problems.append(f"Unknown source {bad}: \"{line['text'][:90]}\"")
            continue
        cited_nums = set().union(*(source_numbers[c] for c in cites))
        missing = [n for n in _numbers(line["text"]) if n not in cited_nums]
        if missing:
            problems.append(f"Number(s) {missing} not found in {cites}: \"{line['text'][:90]}\"")
            continue
        ok += 1
    score = ok / factual if factual else 0.0
    return {"name": "facts", "passed": factual > 0 and score >= 0.95, "score": round(score, 3), "problems": problems}
