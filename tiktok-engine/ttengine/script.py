"""TikTok script engine: HOOK → CONTEXT → DEVELOPMENT → PAYOFF [→ CTA].

Builds on the studio writer (fact-grounded hooks, coherent trimming, fact
checking, style lint) and adds:
  * typed hooks: CURIOSITY, CONTRADICTION, SURPRISE, QUESTION, STATEMENT, STORY,
    UNEXPECTED_FACT, VISUAL_HOOK
  * template pacing from the chosen format (slot windows)
  * a "promise kept" check: the payoff must answer the hook's premise
  * engagement-bait / fake-urgency screening
"""
from __future__ import annotations

import json
from dataclasses import asdict

import yaml

from studio.content import factcheck, originality
from studio.content import style as style_mod
from studio.content.script import (DEFAULT_HOOK_WEIGHTS, HookCandidate, cite_facts_for, estimate_duration,
                                   offline_sections, score_hook, verbatim_issues, word_budget)
from studio.errors import ValidationError
from studio.logging_setup import get_logger
from studio.research.topic_research import load_facts
from studio.textutil import new_id, now_iso, split_sentences, word_count
from . import formats as formats_mod
from . import packet as packet_mod

log = get_logger("tiktok.script")
HOOK_TYPES = ("CURIOSITY", "CONTRADICTION", "SURPRISE", "QUESTION", "STATEMENT", "STORY", "UNEXPECTED_FACT",
              "VISUAL_HOOK")


def load_style(ctx) -> dict:
    return yaml.safe_load(ctx.cfg.config_file(ctx.cfg.get("content.style_file")).read_text(encoding="utf-8"))


def bait_issues(texts: list[str], style: dict) -> list[str]:
    phrases = list(style.get("engagement_bait", [])) + list(style.get("fake_urgency", []))
    return [p for t in texts for p in style_mod._contains(t, phrases)]


def typed_hooks(facts: list[dict], packet: dict) -> list[tuple[HookCandidate, str]]:
    out: list[tuple[HookCandidate, str]] = []
    seen: set[str] = set()

    def add(text: str, htype: str, fact_ids: list[str], strategy: str):
        t = " ".join(text.split())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append((HookCandidate(t, strategy, fact_ids), htype))

    for h in packet.get("hooks") or []:
        htype = str(h.get("type", "STATEMENT")).upper()
        if htype not in HOOK_TYPES:
            raise ValidationError(f"Unknown hook type {htype!r} in research notes")
        add(h["text"], htype, cite_facts_for(h["text"], facts), "editor_idea")
    for f in facts:
        tags = set(f.get("tags", []))
        first = split_sentences(f["text"])[0]
        if f.get("question"):
            add(f["question"], "QUESTION", [f["fact_id"]], "question")
        if "hook" in tags and "visual" in tags:
            add(first, "VISUAL_HOOK", [f["fact_id"]], "first_sentence_of_tagged_fact")
        elif "hook" in tags:
            add(first, "UNEXPECTED_FACT", [f["fact_id"]], "first_sentence_of_tagged_fact")
        if "contrast" in tags:
            add(first, "CONTRADICTION", [f["fact_id"]], "first_sentence_of_tagged_fact")
        if "surprising" in tags:
            add(first, "SURPRISE", [f["fact_id"]], "first_sentence_of_tagged_fact")
        if "definition" in tags and "hook" not in tags:
            add(first, "STATEMENT", [f["fact_id"]], "first_sentence_of_tagged_fact")
        if {"person"} & tags and f.get("fact_date"):
            add(first, "STORY", [f["fact_id"]], "first_sentence_of_tagged_fact")
    return out


def promise_kept(hook: str, sections: list[dict]) -> dict:
    """Does the payoff (or, for a question hook, the answer) pick up what the hook set up?"""
    hook_stems = factcheck.stems(hook)
    payoff = " ".join(x["text"] for s in sections if s["name"] == "PAYOFF" for x in s["sentences"])
    answer = " ".join(x["text"] for s in sections if s["name"] in ("CONTEXT", "DEVELOPMENT") for x in s["sentences"])
    shared_payoff = sorted(hook_stems & factcheck.stems(payoff))
    shared_answer = sorted(hook_stems & factcheck.stems(answer))
    is_question = hook.strip().endswith("?")
    kept = bool(shared_payoff) or (is_question and bool(shared_answer))
    return {"kept": kept, "shared_with_payoff": shared_payoff, "shared_with_body": shared_answer[:10],
            "rule": "the payoff must answer the premise the hook opened"}


def generate(ctx, topic_id: str, *, format_id: str, target_duration: int | None = None,
             video_id: str | None = None, preferred_hook_type: str | None = None) -> dict:
    cfg = ctx.cfg
    topic = ctx.db.require("topics", topic_id)
    fmt = formats_mod.get(ctx, format_id)
    packet = packet_mod.load(ctx, topic_id) or packet_mod.build(ctx, topic_id)
    if not packet["complete"]:
        failed = [k for k, v in packet["checks"].items() if not v]
        raise ValidationError(f"Research packet for '{topic['topic']}' is incomplete: {failed}",
                              hint="extend the research notes before scripting")
    facts = load_facts(ctx, topic_id)
    own = [f for f in facts if f.get("own_words")]
    if len(own) < 3:
        raise ValidationError("The offline writer narrates only facts written in your own words (need 3+)",
                              hint="add research/notes/<topic>.yaml or configure the LLM writer")
    style = load_style(ctx)
    duration = int(target_duration or fmt.get("target_length") or cfg.get("production.target_duration"))
    wpm = int(cfg.get("voice.words_per_minute"))
    tol = float(cfg.get("production.duration_tolerance"))
    upper = word_budget(round(duration * (1 + 0.75 * tol)), wpm)
    min_sources = int(cfg.get("factcheck.min_sources_for_verified"))
    allow_nr = bool(cfg.get("factcheck.allow_needs_review_claims"))
    facts_by_id = {f["fact_id"]: f for f in facts}
    recent = [r["selected_hook"] for r in ctx.db.query("SELECT selected_hook FROM scripts ORDER BY created_at DESC "
                                                       "LIMIT 30")]

    weights = {**DEFAULT_HOOK_WEIGHTS, **(style.get("hook_weights") or {})}
    candidates = typed_hooks(own, packet)
    scored = []
    for hook, htype in candidates:
        score_hook(hook, facts_by_id, style, recent, weights=weights, min_sources=min_sources,
                   allow_needs_review=allow_nr, wpm=wpm, max_seconds=float(cfg.get("qc.max_hook_seconds")))
        if hook.score > 0:
            if htype == fmt.get("hook_style"):
                hook.score += 0.5
                hook.criteria["matches_format_hook_style"] = True
            if bait_issues([hook.text], style):
                hook.score, hook.criteria["bait"] = 0.0, True
        scored.append((hook, htype))
    scored.sort(key=lambda h: h[0].score, reverse=True)
    viable = [(h, t) for h, t in scored if h.score > 0]
    # the template decides the hook type; other types are a fallback, not a competition
    wanted = preferred_hook_type or fmt.get("hook_style")
    viable = [x for x in viable if x[1] == wanted] + [x for x in viable if x[1] != wanted]
    if not viable:
        raise ValidationError("No hook passed the style, speed and fact checks")

    # try hooks in order until one yields a script whose payoff keeps the hook's promise
    chosen = None
    for hook, htype in viable[:5]:
        sections = offline_sections(own, hook, upper, include_cta=False, fmt=fmt["content_format"],
                                    max_setup=max(2, round(duration / 22)))
        for s in sections:
            if s["name"] == "SETUP":
                s["name"] = "CONTEXT"
        promise = promise_kept(hook.text, sections)
        if promise["kept"]:
            chosen = (hook, htype, sections, promise)
            break
    if chosen is None:
        hook, htype = viable[0]
        sections = [dict(s, name="CONTEXT" if s["name"] == "SETUP" else s["name"])
                    for s in offline_sections(own, hook, upper, include_cta=False, fmt=fmt["content_format"],
                                              max_setup=max(2, round(duration / 22)))]
        chosen = (hook, htype, sections, promise_kept(hook.text, sections))
    hook, htype, sections, promise = chosen

    results = factcheck.check_sections(sections, facts_by_id, min_sources=min_sources)
    bad_status = {"UNVERIFIED", "REJECTED"} | (set() if allow_nr else {"NEEDS_REVIEW"})
    bad = {(r["section"], r["sentence_index"]) for r in results if r["status"] in bad_status and r["section"] != "HOOK"}
    dropped = []
    for sec in sections:
        keep = []
        for i, s in enumerate(sec["sentences"]):
            (dropped.append(s["text"]) if (sec["name"], i) in bad else keep.append(s))
        sec["sentences"] = keep
    sections = [s for s in sections if s["sentences"]]
    results = factcheck.check_sections(sections, facts_by_id, min_sources=min_sources)
    summary = factcheck.summarize(results, allow_needs_review=allow_nr)
    names = [s["name"] for s in sections]
    if "PAYOFF" not in names or not {"CONTEXT", "DEVELOPMENT"} & set(names):
        raise ValidationError("The script lost its story arc after removing unverifiable claims", hint=str(dropped))

    lint = style_mod.lint({s["name"]: [x["text"] for x in s["sentences"]] for s in sections}, style,
                          recent_openings=[style_mod.opening(h) for h in recent])
    lint["issues"] += verbatim_issues(sections, facts, int(cfg.get("content.max_ngram_overlap")))
    lint["issues"] += [{"rule": "engagement_bait", "detail": b}
                       for b in bait_issues([x["text"] for s in sections for x in s["sentences"]], style)]
    lint["passed"] = not lint["issues"]
    sources = ctx.db.select("sources", {"topic_id": topic_id, "status": ["APPROVED", "INGESTED"]})
    blueprint = originality.build_blueprint(topic, facts, sources, cfg)
    blueprint.update({"format": fmt["content_format"], "format_id": format_id, "hook_type": htype,
                      "slots": formats_mod.slots(fmt, duration), "promise": promise})
    full = " ".join(x["text"] for s in sections for x in s["sentences"])
    est = estimate_duration(sections, cfg)
    version = int(ctx.db.scalar("SELECT COUNT(*) FROM scripts WHERE topic_id = ?", (topic_id,))) + 1
    hooks_json = []
    for h, t in scored:
        d = asdict(h)
        d["hook_type"] = t
        hooks_json.append(d)
    row = {"script_id": new_id("scr"), "topic_id": topic_id, "version": version, "format": fmt["content_format"],
           "angle": topic.get("potential_angle") or blueprint["angle"], "blueprint_json": blueprint,
           "hooks_json": hooks_json, "selected_hook": hook.text, "sections_json": sections, "full_text": full,
           "word_count": word_count(full), "est_duration": est, "target_duration": duration,
           "llm_provider": "offline", "style_report_json": {**lint, "dropped_sentences": dropped},
           "factcheck_status": "PASSED" if summary["passed"] else "FAILED", "created_at": now_iso()}
    ctx.db.insert("scripts", row)
    factcheck.store_claims(ctx, row["script_id"], results, facts_by_id)
    out = ctx.ws.dir("scripts") / f"{topic['slug']}_tiktok-v{version}.json"
    out.write_text(json.dumps({**row, "claims": results}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if video_id:
        ctx.db.update("videos", video_id, {"script_id": row["script_id"], "updated_at": now_iso()})
    log.info("tiktok script %s: %s hook %r, %d words ~%.0fs (target %ds), promise kept: %s", row["script_id"], htype,
             hook.text, row["word_count"], est, duration, promise["kept"])
    return {**row, "claims": results, "factcheck_summary": summary, "hook_type": htype, "path": str(out)}


def comment_prompts(ctx, packet: dict, fmt: dict, n: int = 3) -> list[dict]:
    """Relevant, genuine conversation prompts — never bait, never fake comments."""
    style = load_style(ctx)
    pool = [(p, "researched") for p in packet.get("comment_prompts") or []]
    pool += [(q, "format") for q in ("Which part surprised you?", "Did you already know this?",
                                     "What would you want explained next?")]
    out = []
    for text, kind in pool:
        if bait_issues([text], style) or not text.strip().endswith("?"):
            continue
        out.append({"text": text, "kind": kind})
        if len(out) >= n:
            break
    return out
