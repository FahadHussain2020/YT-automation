"""Kids safety check (kids mode, replaces the fact check): simple words, nothing scary,
no brands or other channels, no claims about making children smarter, no greeting before
the content, every line has a cartoon shot."""
import re

SCARY = ["kill", "killed", "dead", "die", "dies", "death", "blood", "bloody", "gun", "knife", "sword", "weapon", "fight",
         "punch", "hit you", "monster", "ghost", "zombie", "witch", "devil", "demon", "scary", "scream", "nightmare",
         "bleed", "poison", "burn", "drown", "lost forever", "stupid", "hate", "shut up", "idiot",
         "eat you", "bite you", "creepy", "horror"]
BRANDS = ["chuchu", "cocomelon", "pinkfong", "baby shark", "little baby bum", "super simple", "blippi", "peppa",
          "bluey", "paw patrol", "disney", "pixar", "barbie", "lego", "mcdonald", "youtube kids", "hey bear",
          "mickey", "elsa", "spider-man", "spiderman", "superman", "pokemon", "sesame"]
CLAIMS = re.compile(r"\b(boosts? (iq|brain)|smarter|genius|brain development|develop(s)? (the )?brain|"
                    r"proven|clinically|guaranteed|doctor recommended|scientifically)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|welcome)\b", re.I)
MAX_WORDS = 14  # a sentence a toddler can follow
UNSPEAKABLE = re.compile(r"\b(shh+|zzz+|psst|hmm+|brr+)\b", re.I)  # the voice spells these out ("S-H-H")


def sentences(text: str) -> list[str]:
    """Sentences, and every script line counts as its own (a song verse is short lines ending in commas)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


PEOPLE = re.compile(r"\b(boy|girl|kid|child|children|toddler|man|woman|lady|mom|mum|dad|grandma|grandpa|person|"
                    r"people|farmer|teacher)s?\b", re.I)


def check(script: dict, characters: dict | None = None) -> dict:
    from . import lines, script_text

    text = script_text(script)
    low = text.lower()
    problems, hard = [], []
    for w in SCARY:
        if re.search(rf"\b{re.escape(w)}\b", low):
            hard.append(f"Not for ages 0-6: \"{w}\"")
    for b in BRANDS:
        if b in low:
            hard.append(f"Brand or other channel named: \"{b}\"")
    for m in CLAIMS.finditer(text):
        hard.append(f"Claim we can't back: \"{m.group(0)}\"")
    # people on screen only as the channel's recurring characters (a new face each shot looks wrong)
    characters = characters or {}
    for name, c in (script.get("cast") or {}).items():
        look = f"{name} {c.get('look', '') if isinstance(c, dict) else c}"
        if name.lower() not in characters and PEOPLE.search(look):
            boys = [ch.get("name", k) for k, ch in characters.items() if ch.get("kind") == "boy"]
            hard.append(f"Person in the cast (\"{name}\"): " +
                        (f"use {boys[0]} for a boy; " if boys else "") + "no other people on screen")
    for m in sorted({m.group(0).lower() for m in UNSPEAKABLE.finditer(text)}):
        problems.append(f"The voice spells out \"{m}\"; use a real word (e.g. \"hush\")")
    first = next((l["text"] for _, l in lines(script)), "")
    if GREETING.match(first):
        hard.append(f"Opens with a greeting; start with the content: \"{first[:60]}\"")
    sents = sentences(text)
    if not sents:
        return {"name": "kids_safety", "passed": False, "score": 0, "problems": ["Script is empty"]}
    long = [s for s in sents if len(s.split()) > MAX_WORDS]
    if len(long) > max(1, len(sents) // 10):
        problems.append(f"{len(long)} sentence(s) over {MAX_WORDS} words, too long for toddlers: \"{long[0][:80]}\"")
    noshot = [l["text"] for _, l in lines(script) if not (l.get("shot") or "").strip()]
    if noshot:
        problems.append(f"{len(noshot)} line(s) without a cartoon shot: \"{noshot[0][:60]}\"")
    avg = sum(len(s.split()) for s in sents) / len(sents)
    score = max(0.0, 1 - 0.2 * len(hard) - 0.1 * len(problems))
    return {"name": "kids_safety", "passed": not hard and not problems, "score": round(score, 2),
            "problems": hard + problems, "avg_sentence_words": round(avg, 1)}
