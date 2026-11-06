"""Stage 5: upload approved videos as PRIVATE, scheduled to go public later.

Important: a Google Cloud project that has not passed YouTube's API compliance
audit uploads every video as private-locked; the schedule then does nothing and
you publish by hand in YouTube Studio. See README "YouTube API audit".
"""
import datetime as dt

from . import youtube_api
from .config import section
from .store import Video, all_videos


def next_slot() -> dt.datetime:
    pub = section("publish")
    hours = sorted(pub.get("schedule_hours_utc", [15]))
    gap = pub.get("days_between_videos", 2)
    taken = [dt.datetime.fromisoformat(v.state["publish_at"]) for v in all_videos() if v.state.get("publish_at")]
    now = dt.datetime.now(dt.timezone.utc)
    start = max([now + dt.timedelta(hours=3), *(t + dt.timedelta(days=gap) for t in taken)])
    day = start.date()
    while True:
        for h in hours:
            slot = dt.datetime.combine(day, dt.time(h), dt.timezone.utc)
            if slot >= start:
                return slot
        day += dt.timedelta(days=1)


def uses_synthetic_media(v: Video) -> bool:
    """YouTube asks for disclosure of realistic altered or synthetic content. We flag
    any video with AI images or an AI voice: over-disclosing costs nothing."""
    return v.state.get("ai_image_share", 0) > 0 or v.state.get("own_voice_share", 0) < 1


def upload(v: Video, lang: str = "en", file_name: str | None = None, title: str | None = None,
           description: str | None = None, publish_at: dt.datetime | None = None) -> str:
    from googleapiclient.http import MediaFileUpload

    pub = section("publish")
    yt = youtube_api.service()
    body = {
        "snippet": {
            "title": (title or v.state["title"])[:100],
            "description": (description or v.read("description.txt") or "")[:5000],
            "tags": (v.read("package.json") or {}).get("tags", [])[:15],
            "categoryId": pub.get("category_id", "27"),
            "defaultLanguage": lang, "defaultAudioLanguage": lang,
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": pub.get("made_for_kids", False),
            "containsSyntheticMedia": uses_synthetic_media(v),
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    media = MediaFileUpload(str(v.path(file_name or f"final_{lang}.mp4")), chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")
    return resp["id"]


def run(v: Video, lang: str = "en") -> str:
    if v.stage != "approved":
        raise SystemExit(f"{v.id} is not approved")
    yt = youtube_api.service()
    slot = next_slot()
    vid = upload(v, lang, publish_at=slot)
    srt = v.path(f"captions_{lang}.srt")
    if srt.exists():
        from googleapiclient.http import MediaFileUpload

        yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": lang, "name": lang.upper()}},
                             media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute()
    thumb = v.path(f"thumbnails/thumb_{v.state.get('thumbnail', 1)}.jpg")
    if thumb.exists():
        from googleapiclient.http import MediaFileUpload

        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except Exception as e:  # custom thumbnails need a phone-verified channel
            v.log(f"thumbnail not set: {e}")
    v.set_stage("published", youtube_id=vid, publish_at=slot.isoformat())
    v.log(f"uploaded https://youtu.be/{vid} private, scheduled public at {slot:%Y-%m-%d %H:%M} UTC")
    return vid
