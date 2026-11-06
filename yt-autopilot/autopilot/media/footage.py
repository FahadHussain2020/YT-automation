"""Finds real pictures and clips for each line, archive and stock first.

Each provider returns candidates: {kind: image|video, url, page_url, title, author,
licence, licence_url, source}. Only candidates whose licence passes
licences.allowed() are kept.
"""
import hashlib
from pathlib import Path

import requests

from ..config import env
from . import licences

UA = {"User-Agent": "yt-autopilot/1.0 (personal video research)"}
MAX_MB = 60  # a huge archive file costs minutes to fetch for a few seconds on screen
USABLE = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".mov", ".ogv")


def wikimedia(query: str, limit: int = 6) -> list[dict]:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap|video", "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1920})
    r.raise_for_status()
    out = []
    for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if info.get("width", 0) < 800:
            continue
        video = info.get("mime", "").startswith("video")
        out.append({"kind": "video" if video else "image",
                    "url": info.get("url") if video else info.get("thumburl") or info.get("url"),
                    "page_url": info.get("descriptionurl", ""), "title": page["title"].removeprefix("File:"),
                    "author": licences.strip_html(meta.get("Artist", {}).get("value", "")),
                    "licence": lic, "licence_url": meta.get("LicenseUrl", {}).get("value", ""),
                    "source": "Wikimedia Commons"})
    return out


def internet_archive(query: str, limit: int = 4) -> list[dict]:
    r = requests.get("https://archive.org/advancedsearch.php", headers=UA, timeout=30, params={
        "q": f"({query}) AND mediatype:(movies OR image) AND licenseurl:*",
        "fl[]": ["identifier", "title", "creator", "licenseurl", "mediatype"], "rows": limit, "output": "json"})
    r.raise_for_status()
    out = []
    for d in r.json().get("response", {}).get("docs", []):
        lic_url = d.get("licenseurl", "")
        lic = _licence_from_url(lic_url)
        if not licences.allowed(lic):
            continue
        files = requests.get(f"https://archive.org/metadata/{d['identifier']}", headers=UA, timeout=30).json().get("files", [])
        want = (".mp4",) if d.get("mediatype") == "movies" else (".jpg", ".jpeg", ".png")
        f = next((f for f in files if f.get("name", "").lower().endswith(want)
                  and 0 < int(f.get("size") or 0) < MAX_MB * 1024 * 1024), None)
        if not f:
            continue
        out.append({"kind": "video" if want == (".mp4",) else "image",
                    "url": f"https://archive.org/download/{d['identifier']}/{f['name']}",
                    "page_url": f"https://archive.org/details/{d['identifier']}", "title": d.get("title", ""),
                    "author": ", ".join(d["creator"]) if isinstance(d.get("creator"), list) else d.get("creator", ""),
                    "licence": lic, "licence_url": lic_url, "source": "Internet Archive"})
    return out


def wikipedia_images(titles: list[str], lang: str = "en") -> list[dict]:
    """Pictures used on the Wikipedia articles the script was researched from: usually the
    most relevant ones there are. Asked through Wikipedia's API (reachable even where
    commons.wikimedia.org is blocked); the files themselves mostly live on Commons."""
    out = []
    for title in titles[:4]:
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "titles": title, "redirects": 1, "generator": "images",
            "gimlimit": 30, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1920})
        r.raise_for_status()
        for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 800:
                continue
            out.append({"kind": "image", "url": info.get("thumburl") or info.get("url"),
                        "page_url": info.get("descriptionurl", ""), "title": page["title"].split(":", 1)[-1],
                        "author": licences.strip_html(meta.get("Artist", {}).get("value", "")),
                        "licence": meta.get("LicenseShortName", {}).get("value", ""),
                        "licence_url": meta.get("LicenseUrl", {}).get("value", ""), "source": "Wikimedia Commons"})
    return [c for c in out if licences.allowed(c["licence"])]


OPENVERSE_LICENCES = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY", "by-sa": "CC BY-SA"}


def openverse(query: str, limit: int = 6) -> list[dict]:
    """Openverse (WordPress): CC-licensed photos from Flickr, museums and more. No key needed."""
    r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30, params={
        "q": query, "license_type": "commercial,modification", "page_size": limit, "mature": "false"})
    r.raise_for_status()
    out = []
    for d in r.json().get("results", []):
        lic = OPENVERSE_LICENCES.get(d.get("license", ""))
        if not lic or (d.get("width") or 0) < 800:
            continue
        if d.get("license_version") and lic.startswith("CC BY"):
            lic += f" {d['license_version']}"
        out.append({"kind": "image", "url": d["url"], "page_url": d.get("foreign_landing_url", ""),
                    "title": d.get("title") or query, "author": d.get("creator") or "",
                    "licence": lic, "licence_url": d.get("license_url", ""), "source": f"Openverse ({d.get('source', '')})"})
    return out


def _licence_from_url(url: str) -> str:
    u = url.lower()
    if "publicdomain/zero" in u:
        return "CC0"
    if "publicdomain/mark" in u:
        return "Public Domain"
    for code in ("by-nc-nd", "by-nc-sa", "by-nc", "by-nd", "by-sa", "by"):
        if f"/licenses/{code}/" in u:
            return "CC " + code.upper()
    return ""


def pexels(query: str, limit: int = 4) -> list[dict]:
    key = env("PEXELS_API_KEY")
    if not key:
        return []
    h = {"Authorization": key}
    out = []
    vids = requests.get("https://api.pexels.com/videos/search", headers=h, timeout=30,
                        params={"query": query, "per_page": limit, "orientation": "landscape"}).json()
    for v in vids.get("videos", []):
        files = sorted([f for f in v["video_files"] if (f.get("width") or 0) >= 1280], key=lambda f: f["width"])
        if files:
            out.append({"kind": "video", "url": files[0]["link"], "page_url": v["url"], "title": query,
                        "author": v.get("user", {}).get("name", ""), "licence": "Pexels License",
                        "licence_url": "https://www.pexels.com/license/", "source": "Pexels"})
    photos = requests.get("https://api.pexels.com/v1/search", headers=h, timeout=30,
                          params={"query": query, "per_page": limit, "orientation": "landscape"}).json()
    for p in photos.get("photos", []):
        out.append({"kind": "image", "url": p["src"]["large2x"], "page_url": p["url"], "title": p.get("alt") or query,
                    "author": p.get("photographer", ""), "licence": "Pexels License",
                    "licence_url": "https://www.pexels.com/license/", "source": "Pexels"})
    return out


def pixabay(query: str, limit: int = 4) -> list[dict]:
    key = env("PIXABAY_API_KEY")
    if not key:
        return []
    out = []
    vids = requests.get("https://pixabay.com/api/videos/", timeout=30, params={"key": key, "q": query, "per_page": max(limit, 3)}).json()
    for v in vids.get("hits", [])[:limit]:
        f = v["videos"].get("large") or v["videos"].get("medium")
        if f and f.get("url"):
            out.append({"kind": "video", "url": f["url"], "page_url": v["pageURL"], "title": query, "author": v.get("user", ""),
                        "licence": "Pixabay Content License", "licence_url": "https://pixabay.com/service/license-summary/",
                        "source": "Pixabay"})
    imgs = requests.get("https://pixabay.com/api/", timeout=30,
                        params={"key": key, "q": query, "image_type": "photo", "per_page": max(limit, 3)}).json()
    for p in imgs.get("hits", [])[:limit]:
        out.append({"kind": "image", "url": p["largeImageURL"], "page_url": p["pageURL"], "title": query, "author": p.get("user", ""),
                    "licence": "Pixabay Content License", "licence_url": "https://pixabay.com/service/license-summary/",
                    "source": "Pixabay"})
    return out


def local(video_dir: Path, line_index: int) -> list[dict]:
    """Your own footage/photos: put media_local/line_007.jpg (or .mp4) in the video folder."""
    out = []
    for p in sorted((video_dir / "media_local").glob(f"line_{line_index:03d}*")):
        kind = "video" if p.suffix.lower() in (".mp4", ".mov", ".mkv") else "image"
        out.append({"kind": kind, "url": p.as_uri(), "path": str(p), "page_url": "", "title": p.name, "author": "channel",
                    "licence": "Own work by channel", "licence_url": "", "source": "local"})
    return out


PROVIDERS = {"wikimedia": wikimedia, "openverse": openverse, "internet_archive": internet_archive,
             "pexels": pexels, "pixabay": pixabay}


def search(query: str, order: list[str]):
    """Yields allowed candidates provider by provider, so callers can stop early."""
    for name in order:
        fn = PROVIDERS.get(name)
        if not fn:
            continue
        try:
            found = [c for c in fn(query) if licences.allowed(c["licence"])]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  {name} search failed for {query!r}: {e}")
            continue
        yield from found


def download(c: dict, folder: Path) -> Path:
    if c.get("path"):
        return Path(c["path"])
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(c["url"].split("?")[0]).suffix.lower() or (".mp4" if c["kind"] == "video" else ".jpg")
    if c["kind"] in ("image", "video") and ext not in USABLE:
        raise ValueError(f"unsupported file type {ext}")
    dest = folder / (hashlib.sha1(c["url"].encode()).hexdigest()[:16] + ext)
    if not dest.exists():
        part = dest.with_name(dest.name + ".part")
        try:
            with requests.get(c["url"], headers=UA, timeout=(15, 60), stream=True) as r:
                r.raise_for_status()
                if int(r.headers.get("Content-Length") or 0) > MAX_MB * 1024 * 1024:
                    raise ValueError(f"file over {MAX_MB} MB")
                size = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        size += len(chunk)
                        if size > MAX_MB * 1024 * 1024:
                            raise ValueError(f"file over {MAX_MB} MB")
                        f.write(chunk)
            if c["kind"] == "image" and not usable_image(part):
                raise ValueError("not a readable image (often an HTML error page)")
            if c["kind"] == "video" and part.read_bytes()[:64].lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise ValueError("got a web page, not a video")
            part.rename(dest)
        finally:
            part.unlink(missing_ok=True)
    return dest


def usable_image(path: Path) -> bool:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.load()
            return im.width >= 200 and im.height >= 200
    except Exception:
        return False
