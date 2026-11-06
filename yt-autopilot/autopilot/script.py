"""Stage 2: research, write, check, revise, package.

Output in the video folder:
  sources.json   numbered sources
  script.json    sections -> lines, each line with sources, kind and a shot idea
  script.md      the same, readable (edit script.json, not this)
  checks.json    fact / timing / copying / quality results
  package.json   titles, description, tags, thumbnail text
"""
import json
from collections import Counter

from . import checks, competitors, kids, llm, research, store
from .checks import copying
from .config import section

MAX_REVISIONS = 2

SCRIPT_SHAPE = """{
  "structure": "<structure name>",
  "sections": [
    {"heading": "short chapter title",
     "beat": "which beat of the structure this is",
     "lines": [
        {"text": "one or two spoken sentences",
         "kind": "fact | opinion | commentary | transition",
         "sources": ["S1"],
         "shot": "what the viewer should see: a real photo, map, document, place or footage",
         "search": "2-5 word search query for archive/stock footage"}
     ]}
  ]
}"""


def pick_structure(cfg: dict) -> dict:
    """Least recently used structure, so consecutive videos never share a template."""
    used = Counter(v.state.get("structure") for v in store.all_videos()[-len(cfg["structures"]) * 2:])
    return min(cfg["structures"], key=lambda s: used.get(s["name"], 0))


def pick_hook(cfg: dict, n: int) -> str:
    hooks = cfg.get("hooks") or ["Start with a concrete, surprising detail."]
    return hooks[n % len(hooks)]


def build_prompt(v: store.Video, sources: list[dict], structure: dict, hook: str, cfg: dict) -> str:
    fmt = cfg["format"]
    words = int(fmt["target_minutes"] * fmt["words_per_minute"])
    lessons = [l["lesson"] for l in store.load_lessons()][-10:]
    my_take = v.read("my_take.md") or ""
    src = "\n\n".join(f"[{s['id']}] {s['title']} ({s['url']})\n{s['text'][:9000]}" for s in sources)
    return f"""Write a narration script for a YouTube video.

Channel niche: {cfg['channel']['niche']}
Audience: {cfg['channel']['audience']}
Topic: {v.state['topic']}
Angle: {v.state.get('angle', '')}
Length: about {words} spoken words.

Story structure "{structure['name']}", beats in this order:
{json.dumps(structure['beats'])}

Hook rule: {hook}

The creator's own take (weave it in as kind "opinion" lines, in their voice):
{my_take or '(none yet: add 2-3 short lines of genuine analysis, marked kind "opinion")'}

Lessons from this channel's analytics:
{json.dumps(lessons)}

{competitors.prompt_block()[0]}

Rules:
- Every "fact" line cites the source ids that support it. Every number and year must appear in a cited source.
- Retell in your own words. Never copy a phrase of more than 6 words from a source.
- Spoken English: short sentences, varied rhythm, no filler ("in this video", "let's dive in", "delve").
- No clickbait the video doesn't pay off. No distressing content for shock value.
- For every line, describe a real shot (photo, map, document, location, archival footage).

Sources:
{llm.untrusted(src)}

Return JSON in exactly this shape:
{SCRIPT_SHAPE}"""


def revision_prompt(script: dict, results: list[dict]) -> str:
    problems = [f"[{r['name']}] {p}" for r in results if not r["passed"] for p in r["problems"]]
    return f"""Revise this script to fix every problem listed. Keep the same JSON shape,
keep what works, change only what is needed.

Problems:
{chr(10).join(problems)}

Script:
{json.dumps(script, ensure_ascii=False)}"""


def package_prompt(v: store.Video, script: dict) -> str:
    outline = [s["heading"] for s in script["sections"]]
    return f"""Write YouTube packaging for this video.
Topic: {v.state['topic']}
Chapters: {json.dumps(outline)}
Opening lines: {json.dumps([l['text'] for l in script['sections'][0]['lines'][:3]])}

Return JSON: {{
 "titles": [3 options, under 60 characters, honest, curiosity without clickbait],
 "thumbnail_text": [3 options, 2-4 words each],
 "description": "2 short paragraphs a person would write, no hashtag spam",
 "tags": [10-15 tags],
 "pinned_comment": "a genuine question to start discussion"
}}"""


def render_markdown(script: dict, sources: list[dict]) -> str:
    out = [f"# Script ({script.get('structure', '')})\n"]
    for sec in script["sections"]:
        out.append(f"\n## {sec['heading']}\n")
        for l in sec["lines"]:
            cites = " ".join(f"[{c}]" for c in l.get("sources", []))
            out.append(f"{l['text']} {cites}  \n  _shot: {l.get('shot', '')}_ ({l.get('kind', 'fact')})\n")
    out.append("\n## Sources\n")
    out += [f"- [{s['id']}] {s['title']}: {s['url']}" for s in sources]
    return "\n".join(out)


def run_checks(v: store.Video, script: dict, sources: list[dict], cfg: dict) -> list[dict]:
    if kids.enabled():
        return kids.checks(v, script, cfg)
    own = [o.read("script.md") or "" for o in store.all_videos() if o.id != v.id and o.path("script.md").exists()][-30:]
    refs = v.read("reference_transcripts.json")
    if refs is None:
        refs = copying.fetch_transcripts(v.state.get("reference_videos", []))
        v.write("reference_transcripts.json", refs)
    fmt = cfg["format"]
    return checks.run_all(script, sources, video_dir=v.dir, target_minutes=fmt["target_minutes"],
                          wpm=fmt["words_per_minute"], own_scripts=own, reference_transcripts=refs)


def run(v: store.Video) -> bool:
    from .config import channel

    cfg = channel()
    kids_mode = kids.enabled()
    sources = [] if kids_mode else v.read("sources.json") or research.run(v)  # kids: original, nothing to research
    if not sources and not kids_mode:
        v.log("no sources found; add some to sources_extra.md")
        return False
    structure = next((s for s in cfg["structures"] if s["name"] == v.state.get("structure")), None) or \
        (kids.pick_structure(cfg, bool(v.state.get("short"))) if kids_mode else pick_structure(cfg))
    hook = pick_hook(cfg, len(store.all_videos()))
    if kids_mode and any(k in structure["name"] for k in ("bedtime", "lullaby")):
        # winding down: no clapping or "join in" openers
        hook = "Open softly on the calm, cosy scene itself. No questions, no clapping, no excitement."
    v.update(structure=structure["name"], hook_rule=hook)

    if kids_mode:
        fmt = kids.video_format(v)
        prompt = kids.script_prompt(v, structure, hook, cfg, int(fmt["target_minutes"] * fmt["words_per_minute"]))
    else:
        prompt = build_prompt(v, sources, structure, hook, cfg)
    script = llm.ask(prompt, name="script", workdir=v.dir, want_json=True)
    results = run_checks(v, script, sources, cfg)
    for n in range(1, MAX_REVISIONS + 1):
        if all(r["passed"] for r in results):
            break
        v.log(f"checks failed, revision {n}")
        v.write("checks.json", results)
        v.write("script.json", script)
        script = llm.ask(revision_prompt(script, results), name=f"script-rev{n}", workdir=v.dir, want_json=True)
        results = run_checks(v, script, sources, cfg)

    v.write("script.json", script)
    v.write("script.md", render_markdown(script, sources))
    v.write("checks.json", results)
    package = llm.ask(kids.package_prompt(v, script) if kids_mode else package_prompt(v, script),
                      name="package", workdir=v.dir, want_json=True)
    v.write("package.json", package)
    passed = all(r["passed"] for r in results)
    v.set_stage("scripted", checks_passed=passed)
    v.log("script done" + ("" if passed else " (some checks still failing: see checks.json)"))
    return passed


def recheck(v: store.Video) -> list[dict]:
    """Run the checks again after you edit script.json by hand."""
    from .config import channel

    script, sources = v.read("script.json"), v.read("sources.json") or []
    results = run_checks(v, script, sources, channel())
    v.write("checks.json", results)
    v.write("script.md", render_markdown(script, sources))
    v.update(checks_passed=all(r["passed"] for r in results))
    return results
