"""Licence rules for every picture and clip.

We only use media whose licence allows reuse, including commercially (a monetised
video is commercial) and with changes (we crop, zoom and cut). That rules out
NonCommercial (NC) and NoDerivatives (ND) licences. Every item used is recorded in
<video>/licences.json with its author, licence and link, and the ones that require
credit are listed in the video description automatically.
"""
import re

FREE_NO_CREDIT = ("public domain", "pd", "cc0", "pdm", "no restrictions", "pexels license", "pixabay content license",
                  "own work by channel", "ai generated")


def normalise(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower().replace("-", " "))


def allowed(licence: str) -> bool:
    n = normalise(licence)
    if not n:
        return False
    if re.search(r"\bnc\b|non ?commercial|\bnd\b|no ?deriv|fair use|all rights reserved", n):
        return False
    return any(k in n for k in FREE_NO_CREDIT) or bool(re.match(r"cc by( sa)?( \d\.\d)?", n))


def needs_credit(licence: str) -> bool:
    n = normalise(licence)
    return n.startswith("cc by")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def credit_line(item: dict) -> str:
    author = item.get("author") or "Unknown author"
    return f"{item.get('title') or 'Image'} by {author}, {item['licence']} ({item.get('licence_url') or item['page_url']}), via {item['source']}"


def description_block(items: list[dict], labelled: bool = True) -> str:
    credits = sorted({credit_line(i) for i in items if needs_credit(i["licence"])})
    others = sorted({i["source"] for i in items if not needs_credit(i["licence"]) and i["source"] not in ("AI", "local")})
    out = []
    if credits:
        out.append("Credits:\n" + "\n".join(f"- {c}" for c in credits))
    if others:
        out.append("Additional footage: " + ", ".join(others) + ".")
    if any(i["source"] == "AI" for i in items):
        out.append("Some illustrations are AI-generated and labelled on screen." if labelled else
                   "The illustrations are AI-generated.")
    return "\n\n".join(out)
