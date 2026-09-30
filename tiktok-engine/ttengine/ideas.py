"""Content idea generator: many ideas, few productions.

  batch of N ideas (topic × format × hook type)
    → evaluate (signals) → eliminate weak ones (reason recorded)
    → shortlist K → develop (research packet) → produce P → human review
Nothing is published automatically.
"""
from __future__ import annotations

from studio.content.script import DEFAULT_HOOK_WEIGHTS, score_hook
from studio.research.topic_research import load_facts
from studio.textutil import new_id, now_iso, stable_id
from . import packet as packet_mod
from . import signals as signals_mod
from .script import bait_issues, load_style, typed_hooks
from .visuals import GENERATORS
from .voice import effective_wpm


def _mode_for(trend: dict | None) -> str:
    return "TREND_RESPONSE" if trend and trend.get("expiration_estimate") != "evergreen" else "EVERGREEN"


def generate_batch(ctx, topics: list[dict], *, n: int | None = None, mode: str | None = "EVERGREEN",
                   series_id: str | None = None, trends_by_topic: dict | None = None) -> dict:
    """mode=None derives it per topic: TREND_RESPONSE for a dated trend, EVERGREEN otherwise."""
    n = n or int(ctx.cfg.get("ideas.batch_size"))
    batch_id = new_id("batch")
    style = load_style(ctx)
    past_hooks = [r["selected_hook"] for r in ctx.db.query("SELECT selected_hook FROM scripts")]
    past_topics = [r["topic"] for r in ctx.db.query("SELECT t.topic FROM videos v JOIN topics t ON t.topic_id = v.topic_id")]
    min_facts = int(ctx.cfg.get("research.min_facts"))
    weights = {**DEFAULT_HOOK_WEIGHTS, **(style.get("hook_weights") or {})}
    wpm = effective_wpm(ctx)  # hooks must be sayable in time by the voice that will read them
    ideas = []
    for topic in topics:
        facts = [f for f in load_facts(ctx, topic["topic_id"]) if f.get("own_words")]
        notes = packet_mod.notes_for(ctx, topic["topic"])
        hooks = typed_hooks(facts, {"hooks": notes.get("hooks") or []}) if facts else []
        trend = (trends_by_topic or {}).get(topic["topic_id"])
        for fmt in ctx.formats.values():
            ranked = sorted(hooks, key=lambda h: h[1] != fmt["hook_style"])
            for hook, htype in (ranked or [(None, fmt["hook_style"])])[:3]:
                if len(ideas) >= n:
                    break
                text = hook.text if hook else (topic.get("potential_angle") or f"What {topic['topic']} actually is")
                criteria = None
                if hook:
                    score_hook(hook, {f["fact_id"]: f for f in facts}, style, past_hooks, weights=weights,
                               min_sources=int(ctx.cfg.get("factcheck.min_sources_for_verified")),
                               allow_needs_review=bool(ctx.cfg.get("factcheck.allow_needs_review_claims")),
                               wpm=wpm, max_seconds=float(ctx.cfg.get("qc.max_hook_seconds")))
                    criteria = hook.criteria
                idea = {
                    "idea_id": stable_id("idea", batch_id, topic["topic_id"], fmt["format_id"], text),
                    "batch_id": batch_id, "trend_id": (trend or {}).get("trend_id"), "topic_id": topic["topic_id"],
                    "topic": topic["topic"], "hook": text, "hook_type": htype, "format_id": fmt["format_id"],
                    "target_length": int(fmt["target_length"]), "audience": notes.get("audience"),
                    "source_requirements_json": ["original generated visuals for each beat",
                                                 "licensed footage only with a verified rights record (optional)"],
                    "original_angle": f"{fmt['content_format'].replace('_', ' ').lower()}: "
                                      f"{topic.get('potential_angle') or topic['topic']}",
                    "research_requirements_json": [f">= {min_facts} cited facts written in our own words",
                                                   ">= 2 independent sources, primary where available",
                                                   "resolve contradictions before scripting"],
                    "visual_requirements_json": [f["visual"] for f in facts if f.get("visual")],
                    "mode": mode or _mode_for(trend), "series_id": series_id or notes.get("series"),
                    "category": topic.get("category"),
                }
                sig = signals_mod.evaluate(ctx, idea, facts=facts, trend=trend, past_hooks=past_hooks,
                                           past_topics=past_topics, hook_criteria=criteria,
                                           available_generators=set(GENERATORS))
                reason = None
                s = sig["signals"]
                if hook is None:
                    reason = "no researched hook yet (needs research first)"
                elif hook.score == 0 or bait_issues([text], style):
                    why = [k for k in ("too_long", "banned") if k in hook.criteria] or \
                        (["not grounded in a cited fact"] if not hook.criteria.get("grounded") else ["engagement bait"])
                    reason = "hook failed: " + "; ".join(str(hook.criteria.get(k, k)) for k in why)
                elif (s["production_feasibility"]["value"] or 0) < 0.5:
                    reason = "not enough researched material or producible visuals"
                elif (s["novelty"]["value"] or 0) < 0.3:
                    reason = "too similar to past videos"
                ideas.append({**idea, "signals_json": sig, "order": signals_mod.shortlist_order(s),
                              "elimination_reason": reason})
    shortlist_k = int(ctx.cfg.get("ideas.shortlist"))
    viable = sorted((i for i in ideas if not i["elimination_reason"]), key=lambda i: i["order"], reverse=True)
    shortlisted = {i["idea_id"] for i in viable[:shortlist_k]}
    now = now_iso()
    for i in ideas:
        status = "ELIMINATED" if i["elimination_reason"] else "SHORTLISTED" if i["idea_id"] in shortlisted else "NEW"
        row = {k: v for k, v in i.items() if k not in ("order", "category")}
        ctx.db.insert("ideas", {**row, "status": status, "created_at": now, "updated_at": now}, or_replace=True)
    return {"batch_id": batch_id, "generated": len(ideas), "eliminated": sum(1 for i in ideas if i["elimination_reason"]),
            "shortlisted": [i for i in viable[:shortlist_k]], "disclaimer": signals_mod.DISCLAIMER}


def develop(ctx, idea_id: str) -> dict:
    idea = ctx.db.require("ideas", idea_id)
    pk = packet_mod.build(ctx, idea["topic_id"])
    ctx.db.update("ideas", idea_id, {"status": "DEVELOPING", "updated_at": now_iso()})
    return pk


def produce(ctx, idea_id: str) -> dict:
    from .pipeline import run
    idea = ctx.db.require("ideas", idea_id)
    res = run(ctx, topic_id=idea["topic_id"], format_id=idea["format_id"], series_id=idea.get("series_id"),
              mode=idea["mode"], idea_id=idea_id)
    ctx.db.update("ideas", idea_id, {"status": "PRODUCED", "updated_at": now_iso()})
    return res


def trend_mode(ctx, *, providers: list | None = None, max_topics: int | None = None) -> dict:
    """trends -> research the top trend topics -> batch of ideas -> shortlist -> develop -> produce a few.

    Produces at most `ideas.produce` videos, never more than today's remaining
    `calendar.videos_per_day`, and at most one per topic. Each produced video
    stops at REVIEW for a human decision.
    """
    from studio.research.topic_research import research_topic
    from . import trends as trends_mod
    from .pipeline import videos_today
    found = trends_mod.discover(ctx, providers=providers)
    max_topics = max_topics or int(ctx.cfg.get("ideas.shortlist"))
    topics, by_topic, research = [], {}, {}
    for t in trends_mod.active(ctx):
        if t["topic_id"] in by_topic:
            continue
        if len(topics) >= max_topics:
            break
        res = research_topic(ctx, t["topic_id"])
        research[t["topic"]] = {"facts": res["facts"], "provider_errors": res["provider_errors"]}
        topics.append(ctx.db.require("topics", t["topic_id"]))
        by_topic[t["topic_id"]] = t
    batch = generate_batch(ctx, topics, mode=None, trends_by_topic=by_topic)
    remaining = int(ctx.cfg.get("calendar.videos_per_day")) - videos_today(ctx)
    budget = max(0, min(int(ctx.cfg.get("ideas.produce")), remaining))
    produced, skipped, used_topics = [], [], set()
    for idea in batch["shortlisted"]:
        if len(produced) >= budget:
            break
        if idea["topic_id"] in used_topics:
            continue
        pk = develop(ctx, idea["idea_id"])
        if not pk["complete"]:
            skipped.append({"idea_id": idea["idea_id"], "topic": idea["topic"],
                            "reason": "research packet incomplete: "
                                      + ", ".join(k for k, ok in pk["checks"].items() if not ok)})
            continue
        used_topics.add(idea["topic_id"])
        res = produce(ctx, idea["idea_id"])
        if idea.get("trend_id"):
            ctx.db.update("trends", idea["trend_id"], {"status": "USED"})
        produced.append({"idea_id": idea["idea_id"], "topic": idea["topic"], "format_id": idea["format_id"],
                         **{k: res.get(k) for k in ("video_id", "status", "failed_stage", "error", "review_page")}})
    return {"trends_found": len(found["trends"]), "trend_provider_errors": found["provider_errors"],
            "topics_researched": research, "batch_id": batch["batch_id"], "ideas_generated": batch["generated"],
            "ideas_eliminated": batch["eliminated"],
            "shortlist": [{k: i[k] for k in ("idea_id", "topic", "format_id", "hook_type", "hook", "order")}
                          for i in batch["shortlisted"]],
            "production_budget": budget, "produced": produced, "skipped": skipped,
            "disclaimer": batch["disclaimer"]}
