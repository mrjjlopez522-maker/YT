import json
from types import SimpleNamespace

import pytest
import yaml

from studio.content import factcheck, metadata, style
from studio.content.llm import AnthropicLLM
from studio.content.script import generate_script
from studio.errors import BudgetExceededError, ProviderError, ValidationError
from studio.research.topic_research import get_or_create_topic, load_facts, research_topic
from studio.textutil import now_iso, word_count

from .conftest import REPO


def researched(ctx, topic="Conway's Game of Life"):
    t = get_or_create_topic(ctx, topic)
    research_topic(ctx, t["topic_id"])
    return t


def style_cfg():
    return yaml.safe_load((REPO / "config" / "style.yaml").read_text())


# -- fact checking ------------------------------------------------------------------
FACT = {"fact_id": "f1", "text": "Conway offered fifty dollars in 1970 to anyone who found a pattern that grows forever.",
        "source_url": "https://example.org/a", "source_title": "A", "reliability": "secondary"}


@pytest.mark.parametrize("claim,expected", [
    ("In 1970 Conway offered fifty dollars for a pattern that grows forever.", "VERIFIED"),
    ("Conway offered five hundred dollars for a growing pattern.", "REJECTED"),   # 500 not in source
    ("In 1971 Conway offered the prize.", "REJECTED"),
    ("Gardner offered fifty dollars for a pattern that grows forever.", "NEEDS_REVIEW"),  # name not in source
    ("Bees communicate by dancing in hives.", "UNVERIFIED"),
])
def test_check_claim(claim, expected):
    assert factcheck.check_claim(claim, [FACT]).status == expected


def test_uncited_claim_and_questions():
    assert factcheck.check_claim("Something happened.", []).status == "UNVERIFIED"
    assert not factcheck.is_claim("Why does it keep going?")
    assert factcheck.is_claim("Why did 1970 matter?")  # specifics make it checkable
    assert factcheck.check_claim(FACT["text"], [FACT], min_sources=2).status == "NEEDS_REVIEW"


# -- style ------------------------------------------------------------------------------
def test_style_linter_flags_slop():
    rep = style.lint({"HOOK": ["Did you know this is mind-blowing!!"], "PAYOFF": ["Insane. Crazy. 🚀"]}, style_cfg())
    rules = {i["rule"] for i in rep["issues"]}
    assert {"banned_opening", "banned_phrase", "hype_words", "exclamations", "emojis"} <= rules
    clean = style.lint({"HOOK": ["This game has no players."], "PAYOFF": ["It can compute."]}, style_cfg(),
                       recent_openings=["this game has no players"])
    assert [i["rule"] for i in clean["issues"]] == ["repeated_opening_across_videos"]
    assert style.title_issues("You WON'T believe this SHOCKING bridge", style_cfg())


# -- offline writer -------------------------------------------------------------------------
def test_offline_script_end_to_end(ctx_with_library):
    ctx = ctx_with_library
    t = researched(ctx)
    s = generate_script(ctx, t["topic_id"], use_configured_llm=False)
    assert s["llm_provider"] == "offline"
    assert len(s["hooks_json"]) == 5
    assert all("criteria" in h and "score" in h for h in s["hooks_json"])
    assert s["hooks_json"][0]["score"] >= s["hooks_json"][-1]["score"]
    assert s["selected_hook"] == s["hooks_json"][0]["text"]
    names = [sec["name"] for sec in s["sections_json"]]
    assert names[0] == "HOOK" and "PAYOFF" in names and ("SETUP" in names or "DEVELOPMENT" in names)
    assert s["factcheck_status"] == "PASSED"
    claims = ctx.db.select("claims", {"script_id": s["script_id"]})
    assert claims and all(c["status"] == "VERIFIED" and (c["source_url"] or c["source"]) for c in claims)
    assert s["style_report_json"]["passed"], s["style_report_json"]["issues"]
    assert 45 * 0.75 <= s["est_duration"] <= 45 * 1.25
    # the chosen hook differs next time: novelty penalises reuse
    s2 = generate_script(ctx, t["topic_id"], use_configured_llm=False)
    assert s2["version"] == 2
    reused = next(h for h in s2["hooks_json"] if h["text"] == s["selected_hook"])
    assert reused["criteria"]["novelty"] < 0.1


def test_offline_writer_refuses_third_party_prose(ctx):
    t = get_or_create_topic(ctx, "Tacoma Narrows Bridge")
    rid = "res_x"
    ctx.db.insert("research", {"research_id": rid, "topic_id": t["topic_id"], "provider": "wikipedia",
                               "title": "Wiki", "url": "https://en.wikipedia.org/wiki/X", "retrieved_at": now_iso(),
                               "reliability": "tertiary", "text_license": "CC-BY-SA-4.0"})
    for i in range(6):
        ctx.db.insert("research_facts", {"fact_id": f"fx{i}", "research_id": rid, "topic_id": t["topic_id"],
                                         "text": f"The bridge opened in 194{i} and moved in the wind.", "own_words": 0,
                                         "source_url": "https://en.wikipedia.org/wiki/X", "created_at": now_iso()})
    with pytest.raises(ValidationError) as err:
        generate_script(ctx, t["topic_id"], use_configured_llm=False)
    assert "own words" in str(err.value)


# -- LLM writer (fake Anthropic client; real request shape) ------------------------------------
class FakeAnthropic:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop_reason, stop_details=SimpleNamespace(category="cyber"),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=800), model="claude-opus-5-5")


def llm_payload(facts, copy_text=None):
    """Build a model response citing facts the way the prompt numbers them (F1.. in load order)."""
    key = {(f["local_key"] or f["fact_id"]): f"F{i + 1}" for i, f in enumerate(facts)}

    def F(*local):
        return [key.get(k, "F999") for k in local]
    return {
        "hooks": [{"text": "This game has rules, a board, and no players.", "strategy": "contrast", "fact_ids": F("f3", "f4")},
                  {"text": "Conway offered fifty dollars in 1970 for a pattern that never stops growing.", "strategy": "stakes",
                   "fact_ids": F("f8", "f1")},
                  {"text": "Did you know this game is mind-blowing?", "strategy": "slop", "fact_ids": F("f1")},
                  {"text": "In 1850 a game changed maths.", "strategy": "wrong", "fact_ids": F("f1")},
                  {"text": "Five cells can crawl across a grid forever.", "strategy": "visual", "fact_ids": F("f7")}],
        "sections": [
            {"name": "SETUP", "sentences": [{"text": "John Conway, a British mathematician, came up with it in 1970.", "fact_ids": F("f1")}]},
            {"name": "DEVELOPMENT", "sentences": [
                {"text": copy_text or "Each cell on the grid is either alive or dead.",
                 "fact_ids": F("fw") if copy_text else F("f4")},
                {"text": "A living cell survives with two or three living neighbours.", "fact_ids": F("f5")}]},
            {"name": "PAYOFF", "sentences": [{"text": "Streams of gliders can carry signals, so Life can work as a computer.",
                                              "fact_ids": F("f10")}]},
        ],
        "titles": ["The game with no players", "You won't believe this game"],
        "descriptions": ["A game that runs itself, explained."],
    }


def test_llm_writer_request_shape_costs_and_scoring(ctx_with_library):
    ctx = ctx_with_library
    t = researched(ctx)
    client = FakeAnthropic(llm_payload(load_facts(ctx, t["topic_id"])))
    llm = AnthropicLLM(model="claude-opus-5-5", client=client)
    s = generate_script(ctx, t["topic_id"], llm=llm)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    hooks = {h["text"]: h for h in s["hooks_json"]}
    assert hooks["Did you know this game is mind-blowing?"]["score"] == 0          # banned
    assert hooks["In 1850 a game changed maths."]["score"] == 0                    # number not in sources
    assert s["selected_hook"] in {"This game has rules, a board, and no players.",
                                  "Conway offered fifty dollars in 1970 for a pattern that never stops growing."}
    assert s["factcheck_status"] == "PASSED"
    cost = ctx.db.scalar("SELECT SUM(estimated_usd) FROM costs WHERE topic_id = ?", (t["topic_id"],))
    assert cost == pytest.approx((2000 * 4 + 800 * 20) / 1e6)


def test_llm_budget_and_refusal(ctx_with_library):
    ctx = ctx_with_library
    t = researched(ctx)
    client = FakeAnthropic(llm_payload(load_facts(ctx, t["topic_id"])))
    ctx.cfg.data["costs"]["max_api_cost_per_video"] = 0.01
    with pytest.raises(BudgetExceededError):
        generate_script(ctx, t["topic_id"], llm=AnthropicLLM(model="claude-opus-5-5", client=client))
    assert client.calls == []  # refused before spending anything
    ctx.cfg.data["costs"]["max_api_cost_per_video"] = 1.0
    refusing = AnthropicLLM(model="claude-opus-5-5", client=FakeAnthropic({}, stop_reason="refusal"))
    with pytest.raises(ProviderError) as err:
        generate_script(ctx, t["topic_id"], llm=refusing)
    assert "declined" in str(err.value)


def test_verbatim_copy_of_third_party_text_is_flagged(ctx_with_library):
    ctx = ctx_with_library
    t = researched(ctx)
    wiki = "The Game of Life is a cellular automaton devised by the British mathematician John Horton Conway in 1970."
    rid = "res_w"
    ctx.db.insert("research", {"research_id": rid, "topic_id": t["topic_id"], "provider": "wikipedia", "title": "W",
                               "url": "https://en.wikipedia.org/wiki/Conway%27s_Game_of_Life", "retrieved_at": now_iso(),
                               "reliability": "tertiary", "text_license": "CC-BY-SA-4.0"})
    ctx.db.insert("research_facts", {"fact_id": "fw", "research_id": rid, "topic_id": t["topic_id"], "text": wiki,
                                     "own_words": 0, "source_url": "https://en.wikipedia.org/wiki/x",
                                     "created_at": now_iso()})
    llm = AnthropicLLM(model="claude-opus-5-5", client=FakeAnthropic(llm_payload(load_facts(ctx, t["topic_id"]), copy_text=wiki)))
    s = generate_script(ctx, t["topic_id"], llm=llm)
    assert any(i["rule"] == "verbatim_copy" for i in s["style_report_json"]["issues"])
    assert not s["style_report_json"]["passed"]


# -- metadata ----------------------------------------------------------------------------------
def test_metadata_generation(ctx_with_library):
    ctx = ctx_with_library
    t = researched(ctx)
    s = generate_script(ctx, t["topic_id"], use_configured_llm=False)
    facts = load_facts(ctx, t["topic_id"])
    md = metadata.build_metadata(topic=ctx.db.get("topics", t["topic_id"]), script=s, facts=facts, sources=[],
                                 licenses={}, past_titles=[], style_cfg=style_cfg(), duration=44.0, synthetic_voice=True)
    assert 3 <= len(md["titles"]) <= 5
    assert all(len(x["title"]) <= 70 and not style.title_issues(x["title"], style_cfg()) for x in md["titles"])
    assert len(md["descriptions"]) == 3 and all("Sources:" in d and "synthetic" in d for d in md["descriptions"])
    assert len(md["keywords"]) == 10
    assert len(md["hashtag_sets"]) == 5 and all(1 <= len(h) <= 3 for h in md["hashtag_sets"])
    assert len(md["thumbnail_concepts"]) == 3
    assert "conwaylife.com" in md["selected_description"]
