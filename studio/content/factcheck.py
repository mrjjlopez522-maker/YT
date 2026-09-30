"""Fact checking: every factual sentence must trace to recorded research.

A claim is checked *independently* of the writer's say-so against the facts it
cites:
  * a number in the claim that appears in none of the cited facts -> REJECTED
  * a named entity missing from the cited facts                   -> NEEDS_REVIEW
  * content-word support (light stemming) >= 0.5                  -> VERIFIED
  * support between 0.25 and 0.5                                  -> NEEDS_REVIEW
  * no citation, or support < 0.25                                -> UNVERIFIED
  * fewer independent sources than factcheck.min_sources_for_verified -> NEEDS_REVIEW

This is a traceability check, not a truth oracle: it proves each sentence is
backed by a cited source record. The reviewer still sees every claim with its
source before approval. Citations are never generated — they come only from
research records.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..textutil import (STOPWORDS, capitalized_terms, content_words, new_id, norm_words, now_iso, numbers_in,
                        split_sentences)

STATUSES = ("VERIFIED", "NEEDS_REVIEW", "UNVERIFIED", "REJECTED")
_SUFFIXES = ("ations", "ation", "ers", "ing", "ed", "er", "es", "s")


def stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def stems(text: str) -> set[str]:
    return {stem(w) for w in content_words(text)}


def name_candidates(text: str) -> set[str]:
    """Capitalised words, including sentence-initial ones that are not stopwords (names often lead a claim)."""
    out = set(capitalized_terms(text))
    for sent in split_sentences(text) or [text]:
        words = norm_words(sent)
        raw = sent.lstrip("\"'([ ")
        if words and raw[:1].isupper() and words[0] not in STOPWORDS and words[0].isalpha():
            out.add(words[0])
    return out


def is_claim(sentence: str) -> bool:
    """Questions without specifics and pure CTAs are not factual claims."""
    s = sentence.strip()
    if not norm_words(s):
        return False
    if s.endswith("?") and not numbers_in(s) and not capitalized_terms(s):
        return False
    return not re.match(r"(?i)^(follow|subscribe|comment|tell me|let me know)\b", s)


@dataclass
class ClaimResult:
    claim: str
    status: str
    confidence: float
    fact_ids: list[str]
    notes: list[str] = field(default_factory=list)


def check_claim(claim: str, cited: list[dict], *, min_sources: int = 1) -> ClaimResult:
    ids = [f["fact_id"] for f in cited]
    if not cited:
        return ClaimResult(claim, "UNVERIFIED", 0.0, ids, ["no research fact cited"])
    fact_text = " ".join(f["text"] for f in cited)
    notes = []
    missing_numbers = numbers_in(claim) - numbers_in(fact_text)
    if missing_numbers:
        return ClaimResult(claim, "REJECTED", 0.1, ids,
                           [f"number(s) not in cited sources: {', '.join(sorted(missing_numbers))}"])
    fact_words = set(norm_words(fact_text))
    fact_stems = stems(fact_text)
    missing_entities = {e for e in name_candidates(claim)
                        if e not in fact_words and stem(e.split("'")[0]) not in fact_stems}
    claim_stems = stems(claim)
    support = len(claim_stems & fact_stems) / len(claim_stems) if claim_stems else 1.0
    urls = set()
    for f in cited:
        if f.get("source_url") or f.get("source_title"):
            urls.add(f.get("source_url") or f.get("source_title"))
        for extra in f.get("extra_sources_json") or []:
            urls.add(extra.get("url") or extra.get("title"))
    reliability = {f.get("reliability") for f in cited}

    if support < 0.25:
        return ClaimResult(claim, "UNVERIFIED", round(support, 2), ids, [f"weak support ({support:.2f})"])
    status = "VERIFIED" if support >= 0.5 else "NEEDS_REVIEW"
    if support < 0.5:
        notes.append(f"partial support ({support:.2f})")
    if missing_entities:
        status = "NEEDS_REVIEW"
        notes.append(f"names not in cited sources: {', '.join(sorted(missing_entities))}")
    if len(urls) < min_sources:
        status = "NEEDS_REVIEW" if status == "VERIFIED" else status
        notes.append(f"{len(urls)} source(s); {min_sources} required")
    confidence = 0.5 + 0.5 * min(1.0, support)
    if reliability <= {"tertiary"}:
        confidence = min(confidence, 0.8)
        notes.append("tertiary source only (e.g. an encyclopedia)")
    return ClaimResult(claim, status, round(confidence, 2), ids, notes)


def check_sections(sections: list[dict], facts_by_id: dict[str, dict], *, min_sources: int = 1) -> list[dict]:
    """sections: [{name, sentences:[{text, fact_ids}]}] -> list of per-sentence claim results."""
    results = []
    for sec in sections:
        for i, sent in enumerate(sec["sentences"]):
            cited = [facts_by_id[fid] for fid in sent.get("fact_ids", []) if fid in facts_by_id]
            for piece in split_sentences(sent["text"]) or [sent["text"]]:
                if not is_claim(piece):
                    continue
                r = check_claim(piece, cited, min_sources=min_sources)
                results.append({"section": sec["name"], "sentence_index": i, **r.__dict__})
    return results


def store_claims(ctx, script_id: str, results: list[dict], facts_by_id: dict[str, dict]) -> None:
    ctx.db.delete("claims", {"script_id": script_id})
    for r in results:
        fid = r["fact_ids"][0] if r["fact_ids"] else None
        fact = facts_by_id.get(fid) if fid else None
        ctx.db.insert("claims", {
            "claim_id": new_id("clm"), "script_id": script_id, "claim": r["claim"], "section": r["section"],
            "fact_id": fid, "source": fact.get("source_title") if fact else None,
            "source_url": fact.get("source_url") if fact else None, "confidence": r["confidence"],
            "status": r["status"], "notes": "; ".join(r["notes"]) or None, "created_at": now_iso(),
        })


def summarize(results: list[dict], *, allow_needs_review: bool) -> dict:
    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUSES}
    blocking = counts["UNVERIFIED"] + counts["REJECTED"] + (0 if allow_needs_review else counts["NEEDS_REVIEW"])
    return {"counts": counts, "passed": blocking == 0 and bool(results), "blocking": blocking}
