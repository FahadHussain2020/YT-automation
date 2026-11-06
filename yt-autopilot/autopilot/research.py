"""Collects sources for a topic, each with an id (S1, S2...) the script must cite.

Automatic: Wikipedia articles found from the topic's search terms.
By hand:  put extra sources in <video>/sources_extra.md like this:

    ## Title of the source
    url: https://...
    The text or notes you want the writer to use...

Text from the internet is stored and passed on as untrusted data.
"""
import re
import time

import requests

from .store import Video

UA = {"User-Agent": "yt-autopilot/1.0 (personal research script)"}


def wiki_get(lang: str, params: dict) -> requests.Response:
    """Wikipedia answers 429 when asked too fast; wait and try again."""
    for attempt in range(4):
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=30, params=params)
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("Retry-After") or 0) or 2 ** (attempt + 1))
    return r


def wiki_search(term: str, lang: str = "en", limit: int = 3) -> list[str]:
    r = wiki_get(lang, {"action": "query", "list": "search", "srsearch": term, "srlimit": limit, "format": "json"})
    r.raise_for_status()
    return [h["title"] for h in r.json()["query"]["search"]]


def wiki_text(title: str, lang: str = "en") -> dict | None:
    r = wiki_get(lang, {"action": "query", "prop": "extracts|info", "explaintext": 1, "inprop": "url",
                        "titles": title, "format": "json", "redirects": 1})
    r.raise_for_status()
    page = next(iter(r.json()["query"]["pages"].values()))
    if "extract" not in page:
        return None
    text = re.split(r"\n== (See also|References|Further reading|External links|Notes) ==", page["extract"])[0]
    return {"title": page["title"], "url": page.get("fullurl", ""), "text": text[:30000], "kind": "wikipedia"}


def parse_extra(md: str) -> list[dict]:
    out = []
    for block in re.split(r"^## ", md, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        m = re.search(r"^url:\s*(\S+)", body, re.M)
        out.append({"title": title.strip(), "url": m.group(1) if m else "",
                    "text": re.sub(r"^url:.*$", "", body, flags=re.M).strip(), "kind": "manual"})
    return out


def run(v: Video, max_sources: int = 6) -> list[dict]:
    sources: list[dict] = []
    seen = set()
    terms = v.state.get("search_terms") or [v.state["topic"]]
    for term in [v.state["topic"], *terms]:
        try:
            titles = wiki_search(term)
        except requests.RequestException as e:
            v.log(f"wikipedia search failed for {term!r}: {e}")
            continue
        for t in titles:
            if t in seen or len(sources) >= max_sources:
                continue
            seen.add(t)
            page = wiki_text(t)
            if page and len(page["text"]) > 1500:
                sources.append(page)
    extra = v.read("sources_extra.md")
    if extra:
        sources = parse_extra(extra) + sources
    for i, s in enumerate(sources, 1):
        s["id"] = f"S{i}"
    v.write("sources.json", sources)
    v.log(f"research: {len(sources)} sources")
    return sources
