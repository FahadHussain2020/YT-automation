"""Stage 4: automatic review. Produces review.json with a pass/fail per rule.

A video that passes still needs YOU to approve it in the dashboard (or with
`python run.py approve <id>`). Nothing is uploaded without that approval.
"""
from . import render
from .config import section
from .media import licences
from .store import Video


def run(v: Video, lang: str = "en") -> dict:
    from . import kids

    kids_mode = kids.enabled()
    fmt, orig, vis = kids.video_format(v), section("originality"), section("visuals")
    checks = v.read("checks.json") or []
    package = v.read("package.json") or {}
    items = v.read("licences.json") or []
    timeline = v.read(f"timeline_{lang}.json") or []
    final = v.path(f"final_{lang}.mp4")
    rules = []

    def rule(name: str, ok: bool, detail: str = "", blocking: bool = True):
        rules.append({"rule": name, "ok": bool(ok), "detail": detail, "blocking": blocking})

    for c in checks:
        rule(f"script {c['name']} check", c["passed"], "; ".join(c["problems"][:3]))
    has_take = bool((v.read("my_take.md") or "").strip())
    own = v.state.get("own_voice_share", 0)
    rule("creator input (my_take.md or own voice)", has_take or own > 0 or not orig.get("require_human_note", True),
         f"own voice {own:.0%}; my_take.md {'present' if has_take else 'missing'}")
    share = v.state.get("ai_image_share", 0)
    if kids_mode:  # cartoons are AI by design; YouTube's synthetic-media disclosure is set on upload
        rule("AI disclosure on upload", True, f"{share:.0%} AI cartoon scenes; containsSyntheticMedia set", blocking=False)
    else:
        rule("AI image share", share <= vis.get("max_ai_image_share", 0.25), f"{share:.0%} of lines use AI images")
    missing = v.state.get("missing_visuals", 0)
    rule("visual coverage", missing <= max(1, len(timeline) * 0.1), f"{missing} line(s) without their own visual")
    bad = [i for i in items if not licences.allowed(i["licence"])]
    rule("every image has a reuse licence", not bad, ", ".join(i["title"] for i in bad[:5]))
    nocredit = [i for i in items if licences.needs_credit(i["licence"]) and not i.get("author")]
    rule("credited items have an author", not nocredit, f"{len(nocredit)} item(s) missing author", blocking=False)
    rule("video rendered", final.exists())
    if final.exists():
        minutes = render.probe_duration(final) / 60
        target = fmt.get("target_minutes", 9)
        rule("length", target * 0.7 <= minutes <= target * 1.4, f"{minutes:.1f} min (target {target})", blocking=False)
    if not v.state.get("short"):
        rule("chapters", len(v.read("chapters.json") or []) >= 3, "YouTube needs 3+ chapters of 10s+", blocking=False)
    titles = package.get("titles") or []
    rule("title under 70 chars", bool(titles) and all(len(t) <= 70 for t in titles), "", blocking=False)
    rule("thumbnail made", v.path("thumbnails/thumb_1.jpg").exists())
    desc = v.read("description.txt") or ""
    if kids_mode:
        rule("made for kids set", bool(section("publish").get("made_for_kids")), "publish.made_for_kids in channel.yaml")
    else:
        rule("description lists sources", "Sources:" in desc)

    blocking_fail = [r for r in rules if r["blocking"] and not r["ok"]]
    result = {"passed": not blocking_fail, "rules": rules}
    v.write("review.json", result)
    v.set_stage("reviewed", review_passed=result["passed"])
    v.log("auto review " + ("passed: approve it in the dashboard" if result["passed"] else
                            f"FAILED: {', '.join(r['rule'] for r in blocking_fail)}"))
    return result


def approve(v: Video, title: str | None = None, thumbnail: int = 1, note: str = "") -> None:
    if v.stage != "reviewed":
        raise SystemExit(f"{v.id} is at stage {v.stage}; only reviewed videos can be approved")
    if not v.state.get("review_passed"):
        raise SystemExit("Auto review failed; fix the problems in review.json first")
    package = v.read("package.json") or {}
    v.set_stage("approved", title=title or (package.get("titles") or [v.state["topic"]])[0],
                thumbnail=thumbnail, approval_note=note)


def reject(v: Video, back_to: str = "scripted", note: str = "") -> None:
    v.set_stage(back_to, rejection_note=note)
