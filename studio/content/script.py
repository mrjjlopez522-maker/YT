"""Script generator: HOOK -> SETUP -> DEVELOPMENT -> PAYOFF [-> CTA].

Two writers share one pipeline:
  * LLM writer (Anthropic): drafts 5 hooks + sections from the verified facts,
    citing fact ids, with titles/descriptions.
  * Offline writer: arranges research facts that are already written in your
    own words (local notes). It never narrates third-party prose (e.g. CC BY-SA
    Wikipedia text) — for that it needs an LLM or your own notes.

Whichever writer runs, the studio itself scores the 5 hooks on measurable
criteria, fact-checks every sentence, lints style, and stores the result.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import yaml

from ..analytics.costs import CostTracker
from ..errors import ValidationError
from ..logging_setup import get_logger
from ..research.topic_research import load_facts, load_hook_ideas
from ..textutil import (capitalized_terms, longest_common_run, new_id, norm_words, now_iso, numbers_in,
                        split_sentences, text_similarity, word_count)
from . import factcheck, originality, style as style_mod
from .llm import LLMProvider, build_llm

log = get_logger("content.script")

SECTION_TAGS = {
    "SETUP": {"setup", "origin", "definition", "context", "history"},
    "DEVELOPMENT": {"development", "mechanism", "rule", "pattern", "stakes", "visual", "cause", "glider"},
    "PAYOFF": {"payoff", "significance", "effect", "conclusion"},
}
DEFAULT_HOOK_WEIGHTS = {"length": 1.0, "specificity": 1.5, "curiosity": 1.0, "novelty": 1.5, "front_loaded": 0.5,
                        "grounded": 2.0}


@dataclass
class HookCandidate:
    text: str
    strategy: str
    fact_ids: list[str]
    score: float = 0.0
    criteria: dict = field(default_factory=dict)
    factcheck: dict = field(default_factory=dict)


def word_budget(duration: int, wpm: int) -> int:
    return round(duration * wpm / 60 * 0.9)  # ~10% of runtime goes to pauses


def estimate_duration(sections: list[dict], cfg) -> float:
    wpm = cfg.get("voice.words_per_minute")
    words = sum(word_count(s["text"]) for sec in sections for s in sec["sentences"])
    n_sent = sum(len(split_sentences(s["text"]) or [1]) for sec in sections for s in sec["sentences"])
    pauses = max(0, n_sent - 1) * cfg.get("voice.sentence_pause_ms") / 1000 \
        + max(0, len(sections) - 1) * cfg.get("voice.section_pause_ms") / 1000
    return round(words / wpm * 60 + pauses, 2)


def cite_facts_for(text: str, facts: list[dict], k: int = 2) -> list[str]:
    """Greedy: pick up to k facts that best cover the text's numbers, names and content stems."""
    want_nums, want_ents = numbers_in(text), capitalized_terms(text)
    want_stems = factcheck.stems(text)
    chosen: list[dict] = []
    for _ in range(k):
        best, best_gain = None, 0.0
        covered_nums = set().union(*(numbers_in(f["text"]) for f in chosen)) if chosen else set()
        covered_stems = set().union(*(factcheck.stems(f["text"]) for f in chosen)) if chosen else set()
        covered_words = set().union(*(set(norm_words(f["text"])) for f in chosen)) if chosen else set()
        for f in facts:
            if f in chosen:
                continue
            nums = (numbers_in(f["text"]) & want_nums) - covered_nums
            ents = {e for e in want_ents if e in norm_words(f["text"]) and e not in covered_words}
            st = (factcheck.stems(f["text"]) & want_stems) - covered_stems
            gain = 3 * len(nums) + 2 * len(ents) + len(st)
            if gain > best_gain:
                best, best_gain = f, gain
        if best is None:
            break
        chosen.append(best)
    return [f["fact_id"] for f in chosen]


# -- hooks -----------------------------------------------------------------------
def offline_hooks(facts: list[dict], hook_ideas: list[str]) -> list[HookCandidate]:
    out: list[HookCandidate] = []
    seen: set[str] = set()

    def add(text, strategy, fact_ids):
        t = " ".join(text.split())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(HookCandidate(t, strategy, fact_ids))

    for idea in hook_ideas:
        add(idea, "editor_idea", cite_facts_for(idea, facts))
    for f in facts:
        if f.get("question"):
            add(f["question"], "question", [f["fact_id"]])
    tagged = [f for f in facts if set(f.get("tags", [])) & {"hook", "stakes", "contrast", "definition"}]
    for f in sorted(tagged, key=lambda f: word_count(f["text"])):
        add(split_sentences(f["text"])[0], "first_sentence_of_tagged_fact", [f["fact_id"]])
    by_specificity = sorted(facts, key=lambda f: -(len(numbers_in(f["text"])) * 2 + len(capitalized_terms(f["text"]))))
    for f in by_specificity:
        if len(out) >= 5:
            break
        add(split_sentences(f["text"])[0], "most_specific_fact", [f["fact_id"]])
    return out[:5]


def score_hook(h: HookCandidate, facts_by_id: dict, style_cfg: dict, recent_hooks: list[str], *,
               weights: dict, min_sources: int, allow_needs_review: bool) -> HookCandidate:
    n = word_count(h.text)
    banned = style_mod._starts_with(h.text, style_cfg.get("banned_openings", [])) or \
        style_mod._contains(h.text, style_cfg.get("banned_phrases", []))
    cited = [facts_by_id[i] for i in h.fact_ids if i in facts_by_id]
    fc = factcheck.check_claim(h.text, cited, min_sources=min_sources) if factcheck.is_claim(h.text) else \
        factcheck.ClaimResult(h.text, "VERIFIED", 1.0, h.fact_ids, ["question: not a factual claim"])
    ok_status = {"VERIFIED"} | ({"NEEDS_REVIEW"} if allow_needs_review else set())
    words = norm_words(h.text)
    crit = {
        "length": 1.0 if 5 <= n <= 14 else 0.6 if n <= 18 else 0.2,
        "specificity": min(1.0, (len(numbers_in(h.text)) + len(capitalized_terms(h.text))) / 2),
        "curiosity": 1.0 if h.text.strip().endswith("?") or {"but", "yet", "no", "nobody", "without", "zero"} & set(words)
        else 0.5,
        "novelty": round(1.0 - max([text_similarity(h.text, r) for r in recent_hooks] or [0.0]), 3),
        "front_loaded": 1.0 if (numbers_in(" ".join(words[:6])) or capitalized_terms(" ".join(h.text.split()[:6]))
                                or h.text.strip().endswith("?")) else 0.5,
        "grounded": 1.0 if fc.status in ok_status else 0.0,
    }
    h.criteria = crit
    h.factcheck = {"status": fc.status, "notes": fc.notes}
    h.score = 0.0 if banned or crit["grounded"] == 0 else round(sum(weights.get(k, 0) * v for k, v in crit.items()), 3)
    if banned:
        h.criteria["banned"] = banned
    return h


# -- offline sections --------------------------------------------------------------
def _section_for(f: dict) -> str | None:
    tags = set(f.get("tags", []))
    for name in ("PAYOFF", "SETUP", "DEVELOPMENT"):
        if tags & SECTION_TAGS[name]:
            return name
    return None


def _relevance(f: dict, payoff_stems: set[str], hook_stems: set[str], fmt: str) -> float:
    """How much a fact holds the story together: terms shared with the payoff (fully) and the hook
    (half — overlap with the hook is partly repetition), plus its narrative role."""
    st = factcheck.stems(f["text"])
    score = len(st & payoff_stems) + 0.5 * len(st & hook_stems)
    tags = set(f.get("tags", []))
    if "definition" in tags:
        score += 2.0
    if tags & {"hook", "stakes"}:
        score += 0.5
    if fmt in ("EXPLAINER", "EDUCATIONAL_EXPLANATION", "BREAKDOWN") and tags & {"rule", "mechanism"}:
        score += 0.5
    return score


def offline_sections(facts: list[dict], hook: HookCandidate, budget: int, include_cta: bool,
                     fmt: str = "EXPLAINER", max_setup: int = 2) -> list[dict]:
    used = set(hook.fact_ids) if hook.strategy != "editor_idea" else set()
    pool = [f for f in facts if f["fact_id"] not in used]
    buckets: dict[str, list[dict]] = {"SETUP": [], "DEVELOPMENT": [], "PAYOFF": []}
    untagged = []
    for f in pool:
        sec = _section_for(f)
        (buckets[sec] if sec else untagged).append(f)
    buckets["DEVELOPMENT"].extend(untagged)
    if not buckets["PAYOFF"] and pool:  # the last fact becomes the payoff if none is tagged
        last = (buckets["DEVELOPMENT"] or buckets["SETUP"]).pop()
        buckets["PAYOFF"].append(last)

    payoff_stems = set().union(*(factcheck.stems(f["text"]) for f in buckets["PAYOFF"]))
    rel = {f["fact_id"]: _relevance(f, payoff_stems, factcheck.stems(hook.text), fmt) for f in pool}

    def drop_weakest(name: str) -> None:
        buckets[name].remove(min(buckets[name], key=lambda f: rel[f["fact_id"]]))

    while len(buckets["SETUP"]) > max_setup:
        drop_weakest("SETUP")

    def total() -> int:
        return word_count(hook.text) + sum(word_count(f["text"]) for v in buckets.values() for f in v)

    # Trim to the word budget by removing the least connected fact anywhere (one per section minimum).
    while total() > budget:
        candidates = [(rel[f["fact_id"]], name, f) for name, fs in buckets.items() if len(fs) > 1 for f in fs]
        if not candidates:
            break
        _, name, weakest = min(candidates, key=lambda c: c[0])
        buckets[name].remove(weakest)
    for name in buckets:  # keep the order the researcher wrote
        buckets[name].sort(key=lambda f: (f.get("position", 0), str(f.get("fact_date") or "")))
    sections = [{"name": "HOOK", "sentences": [{"text": hook.text, "fact_ids": hook.fact_ids}]}]
    for name in ("SETUP", "DEVELOPMENT", "PAYOFF"):
        if buckets[name]:
            sections.append({"name": name, "sentences": [{"text": f["text"], "fact_ids": [f["fact_id"]]}
                                                         for f in buckets[name]]})
    if include_cta:
        sections.append({"name": "CTA", "sentences": [{"text": "More stories like this are on the channel.",
                                                       "fact_ids": []}]})
    return sections


# -- LLM writer ------------------------------------------------------------------------
_SENTENCE = {"type": "object", "properties": {"text": {"type": "string"},
                                              "fact_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["text", "fact_ids"], "additionalProperties": False}
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "hooks": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "strategy": {"type": "string"},
            "fact_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "strategy", "fact_ids"], "additionalProperties": False}},
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "enum": ["SETUP", "DEVELOPMENT", "PAYOFF", "CTA"]},
            "sentences": {"type": "array", "items": _SENTENCE}},
            "required": ["name", "sentences"], "additionalProperties": False}},
        "titles": {"type": "array", "items": {"type": "string"}},
        "descriptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hooks", "sections", "titles", "descriptions"],
    "additionalProperties": False,
}

WRITER_SYSTEM = """You write narration for short vertical educational videos (YouTube Shorts).
Write like a good documentary narrator: plain words, concrete detail, short sentences where they help, real narrative progression from hook to payoff.

Hard rules:
- Use ONLY the numbered facts provided. Every sentence cites the fact ids (e.g. "F3") it relies on. Never add a fact, number, name or date that is not in the cited facts.
- Restate facts in fresh wording. Never copy more than five consecutive words from any fact.
- No fake suspense, invented statistics, manufactured controversy, or emotional reactions.
- Avoid stock openings and filler: "Did you know", "You won't believe", "Here's something crazy", "Imagine this", "Let's dive in", "mind-blowing", "game-changer".
- At most one exclamation mark, no emojis, no hashtags in narration.
- The video must make sense to someone who never sees the footage; do not say "as you can see in this clip".
- Only include a CTA section if the brief asks for one."""


def llm_draft(llm: LLMProvider, *, topic: dict, blueprint: dict, facts: list[dict], budget: int,
              hook_ideas: list[str], include_cta: bool, costs: CostTracker, cost_owner: dict) -> tuple[list, list, dict]:
    keyed = {f"F{i + 1}": f for i, f in enumerate(facts)}
    fact_lines = "\n".join(f"{k}: {f['text']} (source: {f.get('source_title') or f.get('source_url')})"
                           for k, f in keyed.items())
    prompt = (
        f"Topic: {topic['topic']}\nFormat: {blueprint['format']}\nAngle: {blueprint['angle']}\n"
        f"Viewer question to answer: {blueprint['viewer_question']}\n"
        f"Word budget for the whole narration (hook included): about {budget} words.\n"
        f"CTA wanted: {'yes, one short sentence' if include_cta else 'no'}\n"
        f"Editor's hook ideas (optional inspiration): {json.dumps(hook_ideas)}\n\n"
        f"Facts:\n{fact_lines}\n\n"
        "Return: exactly 5 distinct hook options (each 5-14 words, each using a different strategy such as "
        "question, specific detail, contrast, consequence, mystery-of-mechanism), the SETUP, DEVELOPMENT and "
        "PAYOFF sections (and CTA only if wanted), 5 accurate non-clickbait titles under 70 characters, and 3 "
        "video descriptions (2-4 sentences each, no hashtags)."
    )
    projected = costs.llm_cost(llm.name, input_tokens=len(WRITER_SYSTEM + prompt) // 3, output_tokens=16000)
    costs.check_budget(projected, what="LLM script draft", **cost_owner)
    result = llm.generate_json(system=WRITER_SYSTEM, prompt=prompt, schema=SCRIPT_SCHEMA)
    costs.record("llm", llm.name, units=result.input_tokens + result.output_tokens, unit_type="tokens",
                 usd=costs.llm_cost(llm.name, result.input_tokens, result.output_tokens), **cost_owner)

    def ids(raw):
        return [keyed[r]["fact_id"] for r in raw if r in keyed]
    hooks = [HookCandidate(h["text"].strip(), h.get("strategy", "llm"), ids(h.get("fact_ids", [])))
             for h in result.data.get("hooks", []) if h.get("text")]
    sections = [{"name": s["name"], "sentences": [{"text": x["text"].strip(), "fact_ids": ids(x.get("fact_ids", []))}
                                                   for x in s.get("sentences", []) if x.get("text", "").strip()]}
                for s in result.data.get("sections", []) if s.get("name") != "CTA" or include_cta]
    extras = {"titles": result.data.get("titles", []), "descriptions": result.data.get("descriptions", []),
              "model": result.model}
    return hooks[:5], [s for s in sections if s["sentences"]], extras


# -- orchestration ----------------------------------------------------------------------
def _recent(ctx, limit: int) -> dict:
    rows = ctx.db.query("SELECT s.selected_hook, s.format FROM scripts s JOIN topics t ON t.topic_id = s.topic_id "
                        "WHERE t.channel_id = ? ORDER BY s.created_at DESC LIMIT ?", (ctx.cfg.channel_id, limit))
    return {"hooks": [r["selected_hook"] for r in rows], "formats": [r["format"] for r in rows],
            "openings": [style_mod.opening(r["selected_hook"]) for r in rows]}


def verbatim_issues(sections: list[dict], facts: list[dict], max_run: int) -> list[dict]:
    """Narration must not copy third-party wording (facts not written in our own words)."""
    third_party = [f for f in facts if not f.get("own_words")]
    issues = []
    for sec in sections:
        for s in sec["sentences"]:
            for f in third_party:
                run = longest_common_run(s["text"], f["text"])
                if run > max_run:
                    issues.append({"rule": "verbatim_copy", "detail": f"{run}-word run copied from {f.get('source_title')}",
                                   "sentence": s["text"][:80]})
    return issues


def generate_script(ctx, topic_id: str, *, video_id: str | None = None, llm: LLMProvider | None = None,
                    use_configured_llm: bool = True, target_duration: int | None = None) -> dict:
    cfg = ctx.cfg
    topic = ctx.db.require("topics", topic_id)
    facts = load_facts(ctx, topic_id)
    if not facts:
        raise ValidationError(f"No research facts for '{topic['topic']}'", hint="run research first")
    style_cfg = yaml.safe_load(cfg.config_file(cfg.get("content.style_file")).read_text(encoding="utf-8"))
    recent = _recent(ctx, int(style_cfg.get("limits", {}).get("recent_scripts_window", 30)))
    sources = ctx.db.select("sources", {"topic_id": topic_id, "status": ["APPROVED", "INGESTED"]})
    blueprint = originality.build_blueprint(topic, facts, sources, cfg, recent_formats=recent["formats"])
    if blueprint["status"] != "OK":
        failed = [k for k, v in blueprint["checks"].items() if not v]
        raise ValidationError(f"Not enough original material for '{topic['topic']}': {failed}",
                              hint="add researched facts in your own words (research/notes) before scripting")

    duration = int(target_duration or cfg.get("production.target_duration"))
    budget = word_budget(duration, cfg.get("voice.words_per_minute"))
    include_cta = bool(cfg.get("content.include_cta"))
    hook_ideas = load_hook_ideas(ctx, topic_id)
    min_sources = int(cfg.get("factcheck.min_sources_for_verified"))
    allow_nr = bool(cfg.get("factcheck.allow_needs_review_claims"))
    facts_by_id = {f["fact_id"]: f for f in facts}
    costs = CostTracker(ctx)
    owner = {"video_id": video_id} if video_id else {"topic_id": topic_id}

    if llm is None and use_configured_llm:
        llm = build_llm(ctx)
    extras: dict = {}
    if llm is not None:
        hooks, llm_sections, extras = llm_draft(llm, topic=topic, blueprint=blueprint, facts=facts, budget=budget,
                                                hook_ideas=hook_ideas, include_cta=include_cta, costs=costs,
                                                cost_owner=owner)
        provider = f"{llm.name}:{extras.get('model')}"
    else:
        own = [f for f in facts if f.get("own_words")]
        if len(own) < 3:
            raise ValidationError(
                "The offline writer only narrates facts written in your own words, and fewer than 3 exist",
                hint="add research/notes/<topic>.yaml, or set content.llm_provider: anthropic")
        facts_for_writer = own
        hooks = offline_hooks(facts_for_writer, hook_ideas)
        provider = "offline"
    if len(hooks) < 5:
        log.warning("only %d hook candidates could be produced (5 requested)", len(hooks))

    weights = {**DEFAULT_HOOK_WEIGHTS, **(style_cfg.get("hook_weights") or {})}
    for h in hooks:
        score_hook(h, facts_by_id, style_cfg, recent["hooks"], weights=weights, min_sources=min_sources,
                   allow_needs_review=allow_nr)
    ranked = sorted(hooks, key=lambda h: h.score, reverse=True)
    if not ranked or ranked[0].score <= 0:
        raise ValidationError("None of the hook candidates passed the style and fact checks",
                              hint="add a hook idea to the research notes or adjust the facts")
    hook = ranked[0]

    if llm is not None:
        sections = [{"name": "HOOK", "sentences": [{"text": hook.text, "fact_ids": hook.fact_ids}]}] + llm_sections
    else:
        # use up to three quarters of the duration tolerance before trimming more material
        tol = float(cfg.get("production.duration_tolerance"))
        upper = word_budget(round(duration * (1 + 0.75 * tol)), cfg.get("voice.words_per_minute"))
        sections = offline_sections(facts_for_writer, hook, upper, include_cta, fmt=blueprint["format"])

    results = factcheck.check_sections(sections, facts_by_id, min_sources=min_sources)
    dropped = []
    if cfg.get("factcheck.drop_unverified_claims"):
        bad_status = {"UNVERIFIED", "REJECTED"} | (set() if allow_nr else {"NEEDS_REVIEW"})
        bad = {(r["section"], r["sentence_index"]) for r in results if r["status"] in bad_status and r["section"] != "HOOK"}
        for sec in sections:
            keep = []
            for i, s in enumerate(sec["sentences"]):
                (dropped.append(s["text"]) if (sec["name"], i) in bad else keep.append(s))
            sec["sentences"] = keep
        sections = [s for s in sections if s["sentences"]]
        results = factcheck.check_sections(sections, facts_by_id, min_sources=min_sources)
    names = {s["name"] for s in sections}
    if "PAYOFF" not in names or not names & {"SETUP", "DEVELOPMENT"}:
        raise ValidationError("After removing unverifiable claims the script has no complete story arc",
                              hint=f"removed: {dropped}")

    summary = factcheck.summarize(results, allow_needs_review=allow_nr)
    lint = style_mod.lint({s["name"]: [x["text"] for x in s["sentences"]] for s in sections}, style_cfg,
                          recent_openings=recent["openings"])
    lint["issues"] += verbatim_issues(sections, facts, int(cfg.get("content.max_ngram_overlap")))
    lint["passed"] = not lint["issues"]
    full_text = " ".join(s["text"] for sec in sections for s in sec["sentences"])
    est = estimate_duration(sections, cfg)
    version = int(ctx.db.scalar("SELECT COUNT(*) FROM scripts WHERE topic_id = ?", (topic_id,))) + 1
    script_id = new_id("scr")
    row = {
        "script_id": script_id, "topic_id": topic_id, "version": version, "format": blueprint["format"],
        "angle": blueprint["angle"], "blueprint_json": blueprint,
        "hooks_json": [asdict(h) for h in ranked], "selected_hook": hook.text, "sections_json": sections,
        "full_text": full_text, "word_count": word_count(full_text), "est_duration": est,
        "target_duration": duration, "llm_provider": provider,
        "style_report_json": {**lint, "dropped_sentences": dropped, "extras": extras},
        "factcheck_status": "PASSED" if summary["passed"] else "FAILED", "created_at": now_iso(),
    }
    ctx.db.insert("scripts", row)
    factcheck.store_claims(ctx, script_id, results, facts_by_id)
    out = ctx.ws.dir("scripts") / f"{topic['slug']}_script-v{version}.json"
    out.write_text(json.dumps({**row, "claims": results, "factcheck_summary": summary}, indent=2,
                              ensure_ascii=False, default=str), encoding="utf-8")
    if video_id:
        ctx.db.update("videos", video_id, {"script_id": script_id, "updated_at": now_iso()})
    log.info("script %s (%s): %d words, ~%.1fs, hook=%r, factcheck=%s", script_id, provider, row["word_count"], est,
             hook.text, row["factcheck_status"])
    return {**row, "claims": results, "factcheck_summary": summary, "path": str(out)}
