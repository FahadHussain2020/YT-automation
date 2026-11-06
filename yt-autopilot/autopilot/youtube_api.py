"""Thin wrappers over the YouTube Data/Analytics APIs.

Read-only scout calls use YOUTUBE_API_KEY. Uploads and analytics use OAuth
(client_secret.json + a token saved on first login).
"""
import requests

from .config import env, env_path

API = "https://www.googleapis.com/youtube/v3"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _get(endpoint: str, **params) -> dict:
    key = env("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set in .env")
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": key}, timeout=30)
    r.raise_for_status()
    return r.json()


def search_videos(query: str, published_after: str, max_results: int = 25) -> list[dict]:
    items = _get("search", part="snippet", q=query, type="video", order="viewCount",
                 publishedAfter=published_after, maxResults=max_results).get("items", [])
    return [{"id": i["id"]["videoId"], "title": i["snippet"]["title"],
             "channel_id": i["snippet"]["channelId"], "channel": i["snippet"]["channelTitle"]}
            for i in items]


def video_stats(ids: list[str]) -> dict[str, dict]:
    out = {}
    for n in range(0, len(ids), 50):
        for i in _get("videos", part="statistics,contentDetails", id=",".join(ids[n:n + 50])).get("items", []):
            out[i["id"]] = {"views": int(i["statistics"].get("viewCount", 0)),
                            "duration": i["contentDetails"]["duration"]}
    return out


def channel_subs(ids: list[str]) -> dict[str, int]:
    out = {}
    ids = list(dict.fromkeys(ids))
    for n in range(0, len(ids), 50):
        for i in _get("channels", part="statistics", id=",".join(ids[n:n + 50])).get("items", []):
            out[i["id"]] = int(i["statistics"].get("subscriberCount", 0) or 0)
    return out


def oauth_credentials():
    """Opens a browser once to log in; afterwards reuses the saved token."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = env_path("YOUTUBE_TOKEN_FILE", "secrets/token.json")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        secret = env_path("YOUTUBE_CLIENT_SECRET", "secrets/client_secret.json")
        if not secret.exists():
            raise SystemExit(f"Missing {secret}. See README, section 'YouTube API'.")
        creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json())
    try:
        token.chmod(0o600)
    except OSError:
        pass
    return creds


def service(name: str = "youtube", version: str = "v3"):
    from googleapiclient.discovery import build

    return build(name, version, credentials=oauth_credentials(), cache_discovery=False)
