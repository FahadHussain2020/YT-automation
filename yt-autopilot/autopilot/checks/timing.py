"""Timing check: narration length lands near the target, and no section drags."""


def check(script: dict, target_minutes: float, wpm: int) -> dict:
    words_per_section = [sum(len(l["text"].split()) for l in s.get("lines", [])) for s in script.get("sections", [])]
    words = sum(words_per_section)
    # kids mode: pauses for the child to answer are part of the running time
    pauses = sum(min(max(float(l.get("pause") or 0), 0), 3) for s in script.get("sections", []) for l in s.get("lines", []))
    minutes = (words / wpm if wpm else 0) + pauses / 60
    problems = []
    low, high = target_minutes * 0.85, target_minutes * 1.15
    if not low <= minutes <= high:
        problems.append(f"Narration is {minutes:.1f} min ({words} words{f' + {pauses:.0f}s of pauses' if pauses else ''}); "
                        f"target is {target_minutes} min ({int(low * wpm - pauses / 60 * wpm)}-{int(high * wpm - pauses / 60 * wpm)} words).")
    if words_per_section:
        hook = words_per_section[0]
        if hook > wpm * 0.75:
            problems.append(f"Opening section is {hook} words; keep the hook under {int(wpm * 0.75)} words (~45s).")
        avg = words / len(words_per_section)
        for i, w in enumerate(words_per_section):
            if w > avg * 2.2 and len(words_per_section) > 2:
                problems.append(f"Section {i + 1} is {w} words, much longer than the others; split it.")
    return {"name": "timing", "passed": not problems, "score": round(minutes, 2), "problems": problems}
