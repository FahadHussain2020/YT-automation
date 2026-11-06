#!/usr/bin/env python3
"""YT Autopilot. Run `python run.py --help` for every command.

One command, niche in, finished video out (stops before upload for your approval):
  python run.py make --niche "untold history stories"
  python run.py make --topic "The Library of Alexandria" --minutes 5

Typical day:
  python run.py scout            # new ideas (or: python run.py idea "Topic")
  python run.py script           # research + write + check every idea
  python run.py produce          # voice, visuals, render, thumbnails
  python run.py review           # automatic review
  python run.py dashboard        # YOU watch and approve at http://127.0.0.1:8000
  python run.py publish          # upload approved videos (private, scheduled)
  python run.py shorts           # Shorts from published videos
  python run.py analytics        # numbers + comments -> lessons for next time
  python run.py competitors @ChuChuTV   # what other channels' winners do (last 72 h)
  python run.py daily            # all of the above except the dashboard, in order
"""
import argparse
import sys
import traceback

from autopilot import store
from autopilot.llm import WaitingForHuman


def each(stage: str, fn, only: str | None):
    videos = [store.get(only)] if only else store.at_stage(stage)
    if not videos:
        print(f"Nothing at stage '{stage}'.")
    for v in videos:
        try:
            fn(v)
        except WaitingForHuman as e:
            v.log(f"waiting for you: {e}")
        except Exception as e:  # one broken video must not stop the others
            v.log(f"ERROR {type(e).__name__}: {e}")
            traceback.print_exc()


def cmd_status(_):
    vids = store.all_videos()
    if not vids:
        print("No videos yet. Start with: python run.py idea \"Your topic\"  or  python run.py scout")
    for v in vids:
        flags = []
        if "checks_passed" in v.state:
            flags.append("checks ok" if v.state["checks_passed"] else "checks FAIL")
        if "review_passed" in v.state:
            flags.append("review ok" if v.state["review_passed"] else "review FAIL")
        if v.state.get("youtube_id"):
            flags.append(f"https://youtu.be/{v.state['youtube_id']}")
        print(f"{v.stage:10} {v.id}  {' | '.join(flags)}")


def cmd_idea(a):
    v = store.create(a.topic, angle=a.angle or "", search_terms=[a.topic], reference_videos=a.ref or [])
    v.log("idea added by hand")
    print(f"Created {v.id}. Optional: write your own view in {v.path('my_take.md')}")


def cmd_scout(a):
    from autopilot import scout
    try:
        for v in scout.run(a.count, use_api=not a.no_api):
            print(f"idea: {v.id}")
    except WaitingForHuman as e:
        print(e)


def cmd_script(a):
    from autopilot import script
    each("idea", script.run, a.id)


def cmd_recheck(a):
    from autopilot import script
    for r in script.recheck(store.get(a.id)):
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['name']}: " + "; ".join(r["problems"][:4]))


def cmd_produce(a):
    from autopilot import produce

    def go(v):
        if not v.state.get("checks_passed") and not a.force:
            v.log("skipped: script checks failing (fix script.json and run recheck, or use --force)")
            return
        produce.run(v)
    each("scripted", go, a.id)


def cmd_review(a):
    from autopilot import review
    each("produced", review.run, a.id)


def cmd_approve(a):
    from autopilot import review
    review.approve(store.get(a.id), a.title, a.thumbnail, a.note or "")
    print("Approved.")


def cmd_publish(a):
    from autopilot import publish
    each("approved", publish.run, a.id)


def cmd_shorts(a):
    from autopilot import shorts
    videos = [store.get(a.id)] if a.id else [v for v in store.at_stage("published")
                                             if not v.state.get("shorts") and not v.state.get("short")]
    for v in videos:
        try:
            shorts.run(v, upload=not a.no_upload)
        except Exception as e:
            v.log(f"ERROR shorts: {e}")


def cmd_analytics(_):
    from autopilot import analytics
    try:
        analytics.run()
    except WaitingForHuman as e:
        print(e)


def cmd_daily(a):
    for fn in (cmd_script, cmd_produce, cmd_review, cmd_publish, cmd_shorts):
        fn(a)


def cmd_make(a):
    """Topic -> script -> voice, visuals, music, captions, render, thumbnails -> review."""
    import re

    from autopilot import produce, review, scout, script
    from autopilot.config import ROOT, channel, env

    cfg = channel()
    if a.niche:
        cfg["channel"]["niche"] = a.niche
        cfg["channel"]["audience"] = a.audience or f"people interested in {a.niche}"
        cfg["channel"]["seed_keywords"] = [a.niche]
        if a.save:
            path = ROOT / "config" / "channel.yaml"
            text = path.read_text(encoding="utf-8")
            text = re.sub(r'^(  niche: ).*$', lambda m: m.group(1) + f'"{a.niche}"', text, count=1, flags=re.M)
            path.write_text(text, encoding="utf-8")
            print(f"Saved niche to {path}")
    if a.minutes:
        cfg["format"]["target_minutes"] = a.minutes
    if a.id:
        v = store.get(a.id)
    elif a.topic:
        from autopilot import competitors
        v = store.create(a.topic, angle=a.angle or "", search_terms=[a.topic],
                         reference_videos=competitors.prompt_block()[1][:30])
    else:
        print(f"Finding a topic for: {cfg['channel']['niche']}")
        v = scout.run(1, use_api=bool(env("YOUTUBE_API_KEY")))[0]
    if a.minutes and v.stage == "idea":  # kept with the video, so later checks use the same target
        v.update(target_minutes=a.minutes)
    if a.structure and v.stage == "idea":
        v.update(structure=a.structure)
    if a.short and v.stage == "idea":  # a vertical Short of about 45 seconds
        v.update(short=True, resolution=[1080, 1920], target_minutes=a.minutes or 0.75)
    v.log(f"make: {v.state['topic']}")
    if v.stage == "idea":
        script.run(v)
    if v.stage == "scripted":
        produce.run(v)
    if v.stage == "produced":
        review.run(v)
    final = v.path("final_en.mp4")
    print(f"\nVideo:      {final}" if final.exists() else "\nNo video rendered; see " + str(v.path("log.txt")))
    print(f"Thumbnails: {v.path('thumbnails')}")
    print(f"Title idea: {(v.read('package.json') or {}).get('titles', [''])[0]}")
    print(f"Review:     {'passed' if v.state.get('review_passed') else 'needs attention, see review.json'}")
    print("Next: python run.py dashboard  (watch it, pick a title and thumbnail, approve), then python run.py publish")


def cmd_competitors(a):
    """Study other channels: what took off in the last --hours, patterns, a strategy for us."""
    from autopilot import competitors
    competitors.run(a.channels, hours=a.hours, max_videos=a.max_videos, top=a.top, strategy=not a.no_strategy)


def cmd_dashboard(a):
    from autopilot import dashboard
    dashboard.serve(a.port)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="list videos and their stage").set_defaults(fn=cmd_status)
    s = sub.add_parser("idea", help="add a topic by hand")
    s.add_argument("topic")
    s.add_argument("--angle")
    s.add_argument("--ref", nargs="*", help="YouTube video IDs your script must not copy")
    s.set_defaults(fn=cmd_idea)
    s = sub.add_parser("scout", help="find topics")
    s.add_argument("--count", type=int, default=3)
    s.add_argument("--no-api", action="store_true", help="skip the YouTube search")
    s.set_defaults(fn=cmd_scout)
    for name, fn, extra in (("script", cmd_script, None), ("produce", cmd_produce, "force"),
                            ("review", cmd_review, None), ("publish", cmd_publish, None)):
        s = sub.add_parser(name)
        s.add_argument("--id", help="only this video")
        if extra:
            s.add_argument("--force", action="store_true")
        s.set_defaults(fn=fn)
    s = sub.add_parser("recheck", help="re-run script checks after editing script.json")
    s.add_argument("id")
    s.set_defaults(fn=cmd_recheck)
    s = sub.add_parser("approve", help="approve without the dashboard")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--thumbnail", type=int, default=1)
    s.add_argument("--note")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("shorts")
    s.add_argument("--id")
    s.add_argument("--no-upload", action="store_true")
    s.set_defaults(fn=cmd_shorts)
    sub.add_parser("analytics").set_defaults(fn=cmd_analytics)
    s = sub.add_parser("daily", help="script -> produce -> review -> publish approved -> shorts")
    s.set_defaults(fn=cmd_daily, id=None, force=False, no_upload=False)
    s = sub.add_parser("make", help="niche or topic in, finished video out (one command)")
    s.add_argument("--niche", help="channel niche for this run (default: config/channel.yaml)")
    s.add_argument("--audience", help="who the channel is for")
    s.add_argument("--save", action="store_true", help="also save --niche to config/channel.yaml")
    s.add_argument("--topic", help="skip topic finding and make this")
    s.add_argument("--angle")
    s.add_argument("--minutes", type=float, help="target length (default from config)")
    s.add_argument("--id", help="resume an existing video")
    s.add_argument("--short", action="store_true", help="vertical Short (~45 s) instead of a long video")
    s.add_argument("--structure", help="story structure name from channel.yaml (default: rotate)")
    s.set_defaults(fn=cmd_make)
    s = sub.add_parser("competitors", help="research other channels: 72h winners, patterns, strategy")
    s.add_argument("channels", nargs="+", help="@handle, channel URL or UC... id")
    s.add_argument("--hours", type=int, default=72, help="window for 'taking off now'")
    s.add_argument("--max-videos", type=int, default=150, help="recent uploads to read per channel")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--no-strategy", action="store_true", help="numbers only, no AI strategy")
    s.set_defaults(fn=cmd_competitors)
    s = sub.add_parser("dashboard")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_dashboard)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
