"""Quality check: catches the habits that make narration sound mass-produced."""
import re
from collections import Counter

FILLER = [
    "in this video", "let's dive in", "dive into", "delve", "tapestry", "buckle up",
    "without further ado", "smash that like", "don't forget to subscribe", "in today's video",
    "it's important to note", "in conclusion", "a testament to", "stands as a", "fast forward to",
    "little did they know", "the rest is history", "you won't believe", "game-changer",
    "ever-evolving", "rich history", "navigate the complexities", "shocking truth",
]
SPECIFIC = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|\d+)\b|\b[A-Z][a-z]+ [A-Z][a-z]+\b")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def check(script: dict) -> dict:
    from . import script_text

    text = script_text(script)
    low = text.lower()
    problems = []
    for f in FILLER:
        if f in low:
            problems.append(f"Filler phrase: \"{f}\"")
    sents = sentences(text)
    if not sents:
        return {"name": "quality", "passed": False, "score": 0, "problems": ["Script is empty"]}
    starts = Counter(" ".join(s.split()[:2]).lower() for s in sents)
    for start, n in starts.items():
        if n >= max(4, len(sents) * 0.06):
            problems.append(f"{n} sentences start with \"{start}\"")
    lengths = [len(s.split()) for s in sents]
    long = [s for s in sents if len(s.split()) > 38]
    if long:
        problems.append(f"{len(long)} sentence(s) over 38 words are hard to follow when spoken")
    avg = sum(lengths) / len(lengths)
    spread = (sum((l - avg) ** 2 for l in lengths) / len(lengths)) ** 0.5
    if spread < 4 and len(sents) > 20:
        problems.append("Sentence lengths are too uniform; vary the rhythm")
    hook = " ".join(sents[:2])
    if not SPECIFIC.search(hook):
        problems.append("Hook has no concrete detail (a name, date or number) in its first two sentences")
    if not any(l.get("kind") in ("opinion", "commentary") for sec in script.get("sections", []) for l in sec.get("lines", [])):
        problems.append("No line of your own view or analysis (kind: opinion/commentary); pure recitation reads as generic")
    score = max(0.0, 1 - 0.1 * len(problems))
    return {"name": "quality", "passed": len(problems) <= 2 and not any(p.startswith("Filler") for p in problems),
            "score": round(score, 2), "problems": problems}
