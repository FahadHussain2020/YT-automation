"""Script checks. Each returns a dict: {name, passed, score, problems: [...]}."""
from . import copying, facts, kids_safety, quality, timing


def run_all(script: dict, sources: list[dict], *, video_dir, target_minutes: float, wpm: int,
            own_scripts: list[str], reference_transcripts: list[dict]) -> list[dict]:
    return [
        facts.check(script, sources),
        timing.check(script, target_minutes, wpm),
        copying.check(script, sources, own_scripts, reference_transcripts),
        quality.check(script),
    ]


def script_text(script: dict) -> str:
    return "\n".join(line["text"] for sec in script.get("sections", []) for line in sec.get("lines", []))


def lines(script: dict):
    for sec in script.get("sections", []):
        for line in sec.get("lines", []):
            yield sec, line
