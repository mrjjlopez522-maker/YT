"""Research packet: everything the writer needs, assembled before any script exists.

Sections: important facts, dates, people, locations, quotes, statistics, historical
context, contradictions (with resolutions) and primary sources. Completeness is
judged against config (minimum facts, independent sources, payoff material,
resolved contradictions); an incomplete packet stops the pipeline.
"""
from __future__ import annotations

import json
import re

import yaml

from studio.research.providers import LocalNotesProvider
from studio.research.topic_research import load_facts
from studio.textutil import new_id, now_iso, numbers_in


def _people(text: str) -> list[str]:
    return re.findall(r"\b([A-Z][a-z]+(?:\s+(?:[A-Z]\.\s*)?[A-Z][a-z]+)+)\b", text)


def notes_for(ctx, topic: str) -> dict:
    path = LocalNotesProvider(ctx.cfg.path(ctx.cfg.get("research.notes_dir"))).find(topic)
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path else {}


def build(ctx, topic_id: str) -> dict:
    topic = ctx.db.require("topics", topic_id)
    facts = load_facts(ctx, topic_id)
    notes = notes_for(ctx, topic["topic"])
    sources = {}
    for f in facts:
        for title, url, rel in [(f.get("source_title"), f.get("source_url"), f.get("reliability")),
                                *[(e.get("title"), e.get("url"), None) for e in (f.get("extra_sources_json") or [])]]:
            key = url or title
            if key:
                sources.setdefault(key, {"title": title, "url": url, "reliability": rel})
    for s in notes.get("sources", []):  # the notes know each source's reliability
        key = s.get("url") or s.get("title")
        if key in sources:
            sources[key]["reliability"] = s.get("reliability") or sources[key]["reliability"]
    people, dates, stats = set(), {}, []
    for f in facts:
        people.update(p for p in _people(f["text"]) if p.split()[0] not in {"The", "In", "And", "It"})
        if f.get("fact_date"):
            dates.setdefault(str(f["fact_date"]), []).append(f["text"])
        if numbers_in(f["text"]) - {str(f.get("fact_date") or "")}:
            stats.append(f["text"])
    contradictions = notes.get("contradictions") or []
    primary = [s for s in sources.values() if s.get("reliability") == "primary"]
    min_facts = int(ctx.cfg.get("research.min_facts"))
    min_sources = int(ctx.cfg.get("research.min_independent_sources"))
    checks = {
        "enough_facts": len(facts) >= min_facts,
        "independent_sources": len(sources) >= min_sources,
        "has_payoff_material": any({"payoff", "significance"} & set(f.get("tags", [])) for f in facts),
        "contradictions_resolved": all(c.get("resolution") for c in contradictions),
        "all_facts_cited": all(f.get("source_url") or f.get("source_title") for f in facts),
    }
    packet = {
        "topic": topic["topic"], "topic_id": topic_id, "created_at": now_iso(),
        "audience": notes.get("audience"), "suggested_format": notes.get("suggested_format"),
        "series": notes.get("series"),
        "important_facts": [{"fact_id": f["fact_id"], "key": f.get("local_key"), "text": f["text"],
                             "source": f.get("source_title"), "url": f.get("source_url"), "tags": f.get("tags"),
                             "requires": f.get("requires"), "visual": f.get("visual")} for f in facts],
        "dates": dict(sorted(dates.items())), "people": sorted(people),
        "locations": notes.get("locations") or [], "quotes": notes.get("quotes") or [],
        "statistics": stats,
        "historical_context": [f["text"] for f in facts if {"history", "origin", "context"} & set(f.get("tags", []))],
        "contradictions": contradictions, "sources": list(sources.values()),
        "primary_sources": primary,
        "hooks": notes.get("hooks") or [], "comment_prompts": notes.get("comment_prompts") or [],
        "caption_ideas": notes.get("caption_ideas") or [],
        "timeline": {str(k): v for k, v in (notes.get("timeline") or {}).items()}
        or {d: " ".join(v[0].split()[:4]) for d, v in dates.items()},
        "checks": checks, "complete": all(checks.values()),
        "warnings": ([] if primary else ["no primary source — rely on tertiary sources with care"])
        + [f"only {len(sources)} independent sources" for _ in [0] if len(sources) < min_sources],
    }
    out = ctx.ws.dir("research") / topic["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "packet.json").write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "packet.md").write_text(to_markdown(packet), encoding="utf-8")
    ctx.db.delete("research_packets", {"topic_id": topic_id})
    ctx.db.insert("research_packets", {"packet_id": new_id("pkt"), "topic_id": topic_id, "path": str(out / "packet.json"),
                                       "facts": len(facts), "sources": len(sources), "primary_sources": len(primary),
                                       "contradictions": len(contradictions), "complete": int(packet["complete"]),
                                       "created_at": now_iso()})
    return packet


def load(ctx, topic_id: str) -> dict | None:
    rows = ctx.db.select("research_packets", {"topic_id": topic_id})
    if not rows:
        return None
    return json.loads(open(rows[0]["path"], encoding="utf-8").read())


def to_markdown(p: dict) -> str:
    lines = [f"# Research packet: {p['topic']}", "", f"Complete: **{p['complete']}** · checks: {p['checks']}", ""]
    if p["warnings"]:
        lines += ["**Warnings:** " + "; ".join(p["warnings"]), ""]
    lines += ["## Important facts"] + [f"- {f['text']} — *{f['source']}*" for f in p["important_facts"]]
    lines += ["", "## Dates"] + [f"- **{d}**: {'; '.join(v)}" for d, v in p["dates"].items()]
    lines += ["", "## People", ", ".join(p["people"]) or "—", "", "## Locations"]
    lines += [f"- {loc['name']}" for loc in p["locations"]] or ["—"]
    lines += ["", "## Quotes"] + [f"- \"{q['text']}\" — {q.get('speaker')}" for q in p["quotes"]] or ["—"]
    lines += ["", "## Statistics / numbers"] + [f"- {s}" for s in p["statistics"]]
    lines += ["", "## Contradictions"] + [f"- {c['topic']}: {c['claim_a']} vs {c['claim_b']} → {c.get('resolution')}"
                                          for c in p["contradictions"]] or ["—"]
    lines += ["", "## Sources"] + [f"- [{s.get('reliability')}] {s['title']} {s.get('url') or ''}" for s in p["sources"]]
    return "\n".join(lines) + "\n"
