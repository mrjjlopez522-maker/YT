"""Idea evaluation: measurable characteristics, never a virality prediction.

Every signal is {value 0..1 or None, evidence}. None means "not measured" and is
never filled with a guess. The shortlist ordering is a transparent weighted sum
of the measured characteristics — a way to decide what to research first, not
a forecast of views.
"""
from __future__ import annotations

import datetime as dt

from studio.textutil import text_similarity, today

SIGNALS = ("topic_relevance", "trend_freshness", "search_demand", "hook_strength", "story_clarity",
           "payoff_strength", "visual_interest", "novelty", "production_feasibility", "audience_relevance")
DISCLAIMER = "Characteristics of the idea, not a prediction of performance."


def _sig(value, evidence):
    return {"value": None if value is None else round(max(0.0, min(1.0, float(value))), 3), "evidence": evidence}


def evaluate(ctx, idea: dict, *, facts: list[dict], trend: dict | None, past_hooks: list[str], past_topics: list[str],
             hook_criteria: dict | None, available_generators: set[str]) -> dict:
    niche = str(ctx.cfg.get("channel.niche") or "")
    cat = (trend or {}).get("category") or idea.get("category")
    sig = {}
    sig["topic_relevance"] = _sig(1.0 if niche in ("", "undecided") or cat == niche else 0.4,
                                  f"category {cat!r} vs channel niche {niche!r}")
    if trend and trend.get("expiration_estimate") and trend["expiration_estimate"] != "evergreen":
        detected = dt.date.fromisoformat(trend["date_detected"])
        expires = dt.date.fromisoformat(trend["expiration_estimate"])
        life = max(1, (expires - detected).days)
        sig["trend_freshness"] = _sig(1 - (today() - detected).days / life, f"detected {detected}, expires {expires}")
    else:
        sig["trend_freshness"] = _sig(None, "evergreen or no trend attached (time-insensitive)")
    ts = (trend or {}).get("trend_signal")
    sig["search_demand"] = _sig(min(1.0, ts / 3.0) if ts else None,
                                f"measured trend signal {ts} ({(trend or {}).get('trend_source')})" if ts
                                else "no measured demand signal")
    if hook_criteria:
        keys = ("length", "specificity", "curiosity", "front_loaded", "grounded")
        sig["hook_strength"] = _sig(sum(hook_criteria.get(k, 0) for k in keys) / len(keys),
                                    "studio hook criteria: length, specificity, curiosity, front-loading, grounding")
    else:
        sig["hook_strength"] = _sig(None, "hook not yet grounded in research")
    tags = {t for f in facts for t in f.get("tags", [])}
    have = [s for s in ("setup", "development", "payoff") if s in tags or (s == "setup" and "definition" in tags)]
    sig["story_clarity"] = _sig(len(have) / 3 if facts else None, f"research covers {have or 'nothing yet'}")
    payoff = [f for f in facts if {"payoff", "significance"} & set(f.get("tags", []))]
    sig["payoff_strength"] = _sig(min(1.0, len(payoff) / 2) if facts else None,
                                  f"{len(payoff)} payoff/significance facts")
    visuals = [f["visual"]["generator"] for f in facts if f.get("visual")]
    ok = [g for g in visuals if g in available_generators]
    sig["visual_interest"] = _sig(len(set(ok)) / 5 if facts else None, f"{len(set(ok))} distinct producible visuals")
    sim = max([text_similarity(idea["hook"], h) for h in past_hooks] + [0.0])
    tsim = max([text_similarity(idea["topic"], t) for t in past_topics] + [0.0])
    sig["novelty"] = _sig(1 - max(sim, 0.5 * tsim), f"max hook similarity {sim:.2f}, topic similarity {tsim:.2f}")
    words = sum(len(f["text"].split()) for f in facts if f.get("own_words"))
    needed = idea["target_length"] * float(ctx.cfg.get("voice.words_per_minute")) / 60 * 0.8
    feas = (min(1.0, words / needed) if needed else 0) * (1.0 if len(ok) == len(visuals) else 0.5)
    sig["production_feasibility"] = _sig(feas if facts else 0.0,
                                         f"{words} researched words for ~{needed:.0f} needed; visuals producible: "
                                         f"{len(ok)}/{len(visuals)}")
    sig["audience_relevance"] = _sig(None if not idea.get("audience") else 0.7,
                                     idea.get("audience") or "no audience defined")
    return {"signals": sig, "disclaimer": DISCLAIMER}


def shortlist_order(signals: dict) -> float:
    """Transparent research-priority order over measured characteristics only."""
    weights = {"story_clarity": 2, "payoff_strength": 2, "production_feasibility": 2, "hook_strength": 1.5,
               "novelty": 1.5, "visual_interest": 1, "topic_relevance": 1, "trend_freshness": 0.5,
               "search_demand": 0.5, "audience_relevance": 0.5}
    measured = {k: v["value"] for k, v in signals.items() if v["value"] is not None}
    return round(sum(weights[k] * v for k, v in measured.items()) / sum(weights[k] for k in measured), 3) \
        if measured else 0.0
