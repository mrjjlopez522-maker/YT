"""Originality Engine: the Original Content Blueprint.

For every video it answers: "What new information, explanation, perspective,
story or context do we provide?" and fixes measurable transformation limits
that QC later enforces. Source footage supports the story; it is not the story.
"""
from __future__ import annotations

from collections import Counter

from ..textutil import longest_common_run

FORMATS = ("DOCUMENTARY", "EXPLAINER", "COMMENTARY", "HISTORICAL_CONTEXT", "MYTH_VS_FACT", "TIMELINE",
           "BREAKDOWN", "STORY", "CASE_STUDY", "COMPARISON", "EDUCATIONAL_EXPLANATION")

# tag -> formats it supports
_TAG_SIGNALS = {
    "myth": ["MYTH_VS_FACT"], "misconception": ["MYTH_VS_FACT"],
    "mechanism": ["EXPLAINER", "BREAKDOWN"], "rule": ["EXPLAINER", "EDUCATIONAL_EXPLANATION"],
    "definition": ["EXPLAINER", "EDUCATIONAL_EXPLANATION"],
    "history": ["HISTORICAL_CONTEXT", "TIMELINE"], "origin": ["HISTORICAL_CONTEXT", "STORY"],
    "person": ["STORY"], "stakes": ["STORY", "CASE_STUDY"], "contrast": ["COMPARISON"],
    "comparison": ["COMPARISON"], "case": ["CASE_STUDY"], "cause": ["BREAKDOWN"], "effect": ["BREAKDOWN"],
    "visual": ["DOCUMENTARY"],
}
STANDALONE_RED_FLAGS = ("as you can see in this clip", "in this video from", "watch what happens", "as shown by")


def choose_format(facts: list[dict], *, recent_formats: list[str] | None = None) -> tuple[str, dict]:
    score: Counter[str] = Counter({"EXPLAINER": 0.5})
    for f in facts:
        for tag in f.get("tags", []):
            for fmt in _TAG_SIGNALS.get(tag, []):
                score[fmt] += 1
    dated = {str(f["fact_date"])[:4] for f in facts if f.get("fact_date")}
    if len(dated) >= 3:
        score["TIMELINE"] += len(dated)
    # variety: gently penalise the formats used most recently
    for i, fmt in enumerate((recent_formats or [])[:5]):
        score[fmt] -= 0.6 / (i + 1)
    best = max(score.items(), key=lambda kv: (kv[1], kv[0] == "EXPLAINER"))[0]
    return best, {k: round(v, 2) for k, v in score.most_common()}


def planned_graphics(fmt: str, facts: list[dict]) -> list[dict]:
    graphics = [{"type": "title_card", "purpose": "state the hook in text for sound-off viewers"}]
    dated = sorted({str(f["fact_date"])[:4] for f in facts if f.get("fact_date")})
    if fmt == "TIMELINE" or len(dated) >= 2:
        graphics.append({"type": "timeline", "years": dated, "purpose": "place events in order"})
    if any("rule" in f.get("tags", []) or "mechanism" in f.get("tags", []) for f in facts):
        graphics.append({"type": "fact_card", "purpose": "spell out the rules/mechanism on screen"})
    if any(f.get("tags") and "payoff" in f["tags"] for f in facts):
        graphics.append({"type": "highlight_box", "purpose": "draw attention to the payoff visual"})
    graphics.append({"type": "progress_bar", "purpose": "pacing cue"})
    return graphics


def build_blueprint(topic: dict, facts: list[dict], sources: list[dict], cfg, *,
                    recent_formats: list[str] | None = None) -> dict:
    fmt, scores = choose_format(facts, recent_formats=recent_formats)
    source_text = " ".join(filter(None, [(s.get("description") or "") + " " +
                                         str(((s.get("analysis_json") or {}).get("transcript") or {}).get("text", ""))
                                         for s in sources]))
    # a fact is "new information" if the footage itself does not already say it
    new_info = [f["text"] for f in facts if not source_text.strip() or longest_common_run(f["text"], source_text) < 5]
    context = [f["text"] for f in facts if set(f.get("tags", [])) & {"origin", "history", "context", "setup"}]
    editorial = [f["text"] for f in facts if set(f.get("tags", [])) & {"payoff", "significance"}]
    question = next((f["question"] for f in facts if f.get("question")), None) \
        or f"What makes {topic['topic']} worth understanding?"
    angle = topic.get("potential_angle") or (
        f"{fmt.replace('_', ' ').title()}: {topic['topic']}, from its origin to "
        f"{'why it matters' if editorial else 'how it works'}")
    graphics = planned_graphics(fmt, facts)
    checks = {
        "has_new_information": len(new_info) >= 3,
        "has_context": bool(context),
        "has_payoff_material": bool(editorial) or len(facts) >= 3,
        "has_original_graphics": len(graphics) >= 1,
    }
    return {
        "format": fmt, "format_scores": scores, "angle": angle, "viewer_question": question,
        "new_value": {
            "NEW_INFORMATION": new_info[:8], "NEW_CONTEXT": context[:4],
            "NEW_NARRATION": f"original script, narrated with voice provider '{cfg.get('voice.provider')}'",
            "NEW_STORY_STRUCTURE": f"HOOK -> SETUP -> DEVELOPMENT -> PAYOFF as a {fmt.lower()}",
            "NEW_EDITORIAL_VALUE": editorial[:3], "NEW_GRAPHICS": graphics,
            "NEW_PRESENTATION": "vertical 9:16 reframing, timed captions, paced cuts",
        },
        "source_role": "supporting visuals only; the narration carries the story",
        "standalone_test": {
            "passes": checks["has_new_information"] and checks["has_payoff_material"],
            "rule": "the Short must make sense to someone who never sees the source footage",
            "red_flag_phrases": list(STANDALONE_RED_FLAGS),
        },
        "limits": {
            "max_continuous_source_seconds": float(cfg.get("source_policy.max_continuous_source_seconds")),
            "max_source_screen_ratio": float(cfg.get("source_policy.max_source_screen_ratio")),
            "min_narration_coverage": float(cfg.get("qc.min_narration_coverage")),
        },
        "checks": checks,
        "status": "OK" if all(checks.values()) else "INSUFFICIENT_ORIGINALITY",
    }
