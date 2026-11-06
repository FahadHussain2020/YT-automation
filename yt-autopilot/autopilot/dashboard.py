"""Local review dashboard: python run.py dashboard  ->  http://127.0.0.1:8000

Only listens on this computer (127.0.0.1) and asks for DASHBOARD_USER /
DASHBOARD_PASSWORD from .env. Here you watch each video, read its checks,
pick a title and thumbnail, and approve or send it back.
"""
import html
import secrets


from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import review, store
from .config import env

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()
SERVABLE = {".mp4", ".jpg", ".png", ".srt", ".md", ".txt", ".json"}


def auth(creds: HTTPBasicCredentials = Depends(security)) -> str:
    user, pw = env("DASHBOARD_USER", "admin"), env("DASHBOARD_PASSWORD")
    ok = pw and secrets.compare_digest(creds.username.encode(), user.encode()) and \
        secrets.compare_digest(creds.password.encode(), pw.encode())
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return creds.username


def same_origin(request: Request) -> None:
    """Blocks other websites from submitting forms to the dashboard."""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    host = request.headers.get("host", "")
    if origin and host not in origin:
        raise HTTPException(403, "cross-site request blocked")


e = html.escape
STYLE = """<style>body{font:15px system-ui;margin:0;background:#f6f6f4;color:#222}main{max-width:1100px;margin:auto;padding:16px}
table{width:100%;border-collapse:collapse;background:#fff}td,th{padding:8px;border-bottom:1px solid #eee;text-align:left}
.ok{color:#16794a}.bad{color:#b42318}.card{background:#fff;padding:16px;margin:12px 0;border-radius:8px}
video{width:100%;max-height:60vh;background:#000}img.t{width:240px;margin:4px;border:3px solid transparent}
button{padding:8px 14px;margin:4px 4px 0 0}pre{white-space:pre-wrap}</style>"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{e(title)}</title>{STYLE}<main>{body}</main>")


@app.get("/", response_class=HTMLResponse)
def index(_: str = Depends(auth)):
    rows = "".join(
        f"<tr><td><a href='/v/{e(v.id)}'>{e(v.state.get('topic', v.id))}</a></td><td>{e(v.stage)}</td>"
        f"<td class={'ok' if v.state.get('review_passed') else 'bad'}>{'pass' if v.state.get('review_passed') else ('fail' if 'review_passed' in v.state else '')}</td>"
        f"<td>{e(v.state.get('publish_at', ''))}</td></tr>"
        for v in reversed(store.all_videos()))
    return page("YT Autopilot", f"<h1>YT Autopilot</h1><table><tr><th>Video</th><th>Stage</th><th>Auto review</th>"
                                f"<th>Publishes</th></tr>{rows}</table>")


@app.get("/v/{vid}", response_class=HTMLResponse)
def detail(vid: str, _: str = Depends(auth)):
    v = store.get(vid)
    rv = v.read("review.json") or {"rules": []}
    package = v.read("package.json") or {}
    rules = "".join(f"<tr><td class={'ok' if r['ok'] else 'bad'}>{'✓' if r['ok'] else '✗'}</td><td>{e(r['rule'])}"
                    f"{'' if r['blocking'] else ' (advice)'}</td><td>{e(r['detail'])}</td></tr>" for r in rv["rules"])
    titles = "".join(f"<label><input type=radio name=title value='{e(t)}' {'checked' if i == 0 else ''}> {e(t)}</label><br>"
                     for i, t in enumerate(package.get("titles", [])))
    thumbs = "".join(f"<label><input type=radio name=thumbnail value={n} {'checked' if n == 1 else ''}>"
                     f"<img class=t src='/f/{e(vid)}/thumbnails/thumb_{n}.jpg'></label>"
                     for n in (1, 2, 3) if v.path(f"thumbnails/thumb_{n}.jpg").exists())
    actions = ""
    if v.stage == "reviewed" and v.state.get("review_passed"):
        actions = (f"<form method=post action='/v/{e(vid)}/approve'><h3>Title</h3>{titles}<h3>Thumbnail</h3>{thumbs}"
                   f"<p><input name=note placeholder='note (optional)' size=60></p><button>Approve for upload</button></form>")
    if v.stage in ("reviewed", "produced", "approved"):
        actions += (f"<form method=post action='/v/{e(vid)}/reject'><input name=note placeholder='what to fix' size=60>"
                    f"<button>Send back to script</button></form>")
    video = f"<video controls src='/f/{e(vid)}/final_en.mp4'></video>" if v.path("final_en.mp4").exists() else ""
    return page(vid, f"<p><a href='/'>← all videos</a></p><h1>{e(v.state.get('topic', vid))}</h1>"
                     f"<p>Stage: <b>{e(v.stage)}</b></p>{video}<div class=card>{actions}</div>"
                     f"<div class=card><h2>Auto review</h2><table>{rules}</table></div>"
                     f"<div class=card><h2>Script</h2><pre>{e(v.read('script.md') or '')}</pre></div>"
                     f"<div class=card><h2>Description</h2><pre>{e(v.read('description.txt') or '')}</pre></div>")


@app.post("/v/{vid}/approve")
def approve(vid: str, request: Request, title: str = Form(""), thumbnail: int = Form(1), note: str = Form(""),
            _: str = Depends(auth)):
    same_origin(request)
    review.approve(store.get(vid), title or None, thumbnail, note)
    return RedirectResponse(f"/v/{vid}", status_code=303)


@app.post("/v/{vid}/reject")
def reject(vid: str, request: Request, note: str = Form(""), _: str = Depends(auth)):
    same_origin(request)
    review.reject(store.get(vid), note=note)
    return RedirectResponse(f"/v/{vid}", status_code=303)


@app.get("/f/{vid}/{name:path}")
def file(vid: str, name: str, _: str = Depends(auth)):
    v = store.get(vid)
    p = (v.dir / name).resolve()
    if not p.is_relative_to(v.dir.resolve()) or p.suffix.lower() not in SERVABLE or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


def serve(port: int = 8000) -> None:
    import uvicorn

    if not env("DASHBOARD_PASSWORD"):
        raise SystemExit("Set DASHBOARD_PASSWORD in .env first (a long random one).")
    uvicorn.run(app, host="127.0.0.1", port=port)
