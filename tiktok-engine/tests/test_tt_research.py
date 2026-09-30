"""Trends, format templates, research packets, idea batches and signals."""
import datetime as dt

import pytest
import yaml

from studio.errors import ValidationError
from studio.textutil import today
from ttengine import formats, ideas, packet, signals, trends


def _observations(tmp_path, items):
    p = tmp_path / "obs.yaml"
    p.write_text(yaml.safe_dump({"observations": items}))
    return trends.ObservationsProvider(p)


def test_trend_fields_and_unmeasured_signal_stays_null(ctx, tmp_path):
    prov = _observations(tmp_path, [{"topic": "Tiny robots", "category": "science", "trend_type": "rising",
                                     "signal": None, "potential_angle": "what they can actually do",
                                     "format": {"hook_style": "QUESTION", "video_length": 30}}])
    out = trends.discover(ctx, providers=[prov])
    t = out["trends"][0]
    for field in ("trend_id", "topic", "category", "date_detected", "trend_source", "trend_signal", "growth_signal",
                  "content_volume", "potential_angle", "expiration_estimate"):
        assert field in t
    assert t["trend_signal"] is None  # never invented
    assert t["expiration_estimate"] == (today() + dt.timedelta(days=trends.EXPIRY_DAYS["rising"])).isoformat()
    assert ctx.db.select("format_observations")[0]["hook_style"] == "QUESTION"


def test_trends_expire(ctx, tmp_path):
    past = (today() - dt.timedelta(days=1)).isoformat()
    prov = _observations(tmp_path, [{"topic": "Old meme", "trend_type": "cultural_moment", "expires": past},
                                    {"topic": "Fresh one", "trend_type": "rising"}])
    trends.discover(ctx, providers=[prov])
    assert [t["topic"] for t in trends.active(ctx)] == ["Fresh one"]


def test_format_slots_cover_the_video(ctx):
    for fmt in ctx.formats.values():
        s = formats.slots(fmt, 60)
        assert s[0]["start_s"] == 0 and s[-1]["end_s"] == 60
        assert all(a["end"] == b["start"] for a, b in zip(fmt["story_structure"], fmt["story_structure"][1:]))
    assert "hook" in formats.describe(ctx).lower()
    with pytest.raises(ValidationError):
        formats.record_observation(ctx, sparkle="yes")


def test_research_packet_complete_for_fixture(researched):
    ctx, _, pk = researched
    assert pk["complete"], pk["checks"]
    for key in ("important_facts", "dates", "people", "locations", "quotes", "statistics", "historical_context",
                "contradictions", "primary_sources"):
        assert key in pk
    assert len(pk["sources"]) >= 2


def test_research_packet_incomplete_without_notes(ctx):
    from studio.research.topic_research import get_or_create_topic, research_topic
    tid = get_or_create_topic(ctx, "A topic nobody researched")["topic_id"]
    research_topic(ctx, tid)
    pk = packet.build(ctx, tid)
    assert not pk["complete"] and not pk["checks"]["enough_facts"]


def test_idea_batch_eliminates_with_reasons(researched):
    ctx, tid, _ = researched
    from studio.research.topic_research import get_or_create_topic
    other = get_or_create_topic(ctx, "Unresearched topic")
    batch = ideas.generate_batch(ctx, [ctx.db.require("topics", tid), other], n=20)
    assert batch["generated"] <= 20 and batch["disclaimer"] == signals.DISCLAIMER
    rows = ctx.db.select("ideas", {"batch_id": batch["batch_id"]})
    for r in rows:
        for field in ("idea_id", "topic", "hook", "format_id", "target_length", "audience", "source_requirements_json",
                      "original_angle", "research_requirements_json", "visual_requirements_json"):
            assert field in r
        assert (r["status"] == "ELIMINATED") == bool(r["elimination_reason"])
    unresearched = [r for r in rows if r["topic"] == "Unresearched topic"]
    assert unresearched and all("no researched hook" in r["elimination_reason"] for r in unresearched)
    shortlisted = [r for r in rows if r["status"] == "SHORTLISTED"]
    assert 0 < len(shortlisted) <= int(ctx.cfg.get("ideas.shortlist"))
    assert all(r["topic"] == "The Mandelbrot set" for r in shortlisted)


def test_signals_never_guess(ctx):
    idea = {"hook": "A hook", "topic": "x", "target_length": 30, "audience": None}
    sig = signals.evaluate(ctx, idea, facts=[], trend=None, past_hooks=[], past_topics=[], hook_criteria=None,
                           available_generators=set())
    s = sig["signals"]
    assert set(s) == set(signals.SIGNALS)
    for name in ("trend_freshness", "search_demand", "hook_strength", "story_clarity", "audience_relevance"):
        assert s[name]["value"] is None, name
    assert sig["disclaimer"] == signals.DISCLAIMER
    assert signals.shortlist_order({"a": {"value": None}}) == 0.0
