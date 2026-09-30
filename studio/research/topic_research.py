"""Topic creation and research collection."""
from __future__ import annotations

import hashlib
import json

from ..errors import ProviderError, ValidationError
from ..logging_setup import get_logger
from ..textutil import new_id, now_iso, slugify, stable_id
from .providers import ResearchProvider, build_research_providers

log = get_logger("research")


def get_or_create_topic(ctx, topic: str, *, category: str | None = None, potential_angle: str | None = None,
                        trend_signal: float | None = None, trend_source: str | None = None,
                        trend_evidence: dict | None = None, evergreen_score: float | None = None,
                        timeliness: str | None = None) -> dict:
    topic = topic.strip()
    if not topic:
        raise ValidationError("Topic must not be empty")
    slug = slugify(topic)
    rows = ctx.db.select("topics", {"channel_id": ctx.cfg.channel_id, "slug": slug})
    if rows:
        return rows[0]
    now = now_iso()
    row = {
        "topic_id": stable_id("top", ctx.cfg.channel_id, slug), "channel_id": ctx.cfg.channel_id, "topic": topic,
        "slug": slug, "category": category, "trend_signal": trend_signal, "trend_source": trend_source,
        "trend_evidence_json": trend_evidence, "date_detected": now, "source_count": 0,
        "potential_angle": potential_angle, "evergreen_score": evergreen_score, "timeliness": timeliness or "unknown",
        "research_status": "NEW", "created_at": now, "updated_at": now,
    }
    ctx.db.insert("topics", row)
    return row


def research_topic(ctx, topic_id: str, providers: list[ResearchProvider] | None = None) -> dict:
    """Run research providers; store docs + facts. Returns {facts, docs, hook_ideas, provider_errors}."""
    topic = ctx.db.require("topics", topic_id)
    providers = providers if providers is not None else build_research_providers(ctx)
    ctx.db.update("topics", topic_id, {"research_status": "RESEARCHING", "updated_at": now_iso()})
    out_dir = ctx.ws.dir("research") / topic["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    provider_errors, hook_ideas, n_facts, n_docs = {}, [], 0, 0
    # Re-running research replaces earlier facts from the same provider.
    for provider in providers:
        try:
            bundle = provider.research(topic["topic"])
        except ProviderError as exc:
            log.warning("research provider %s failed: %s", provider.name, exc)
            provider_errors[provider.name] = str(exc)
            ctx.db.record_error(stage="research", exc=exc, topic_id=topic_id)
            continue
        if not bundle.docs:
            continue
        in_use = ctx.db.scalar(
            "SELECT COUNT(*) FROM claims c JOIN research_facts f ON f.fact_id = c.fact_id "
            "JOIN research r ON r.research_id = f.research_id WHERE r.topic_id = ? AND r.provider = ?",
            (topic_id, provider.name))
        if in_use:
            log.info("research from %s is referenced by existing scripts; keeping the recorded version", provider.name)
            hook_ideas.extend(bundle.hook_ideas)
            continue
        for old in ctx.db.select("research", {"topic_id": topic_id, "provider": provider.name}):
            ctx.db.delete("research", {"research_id": old["research_id"]})
        hook_ideas.extend(bundle.hook_ideas)
        if bundle.category and not topic.get("category"):
            ctx.db.update("topics", topic_id, {"category": bundle.category})
        snapshot = out_dir / f"{provider.name}.json"
        snapshot.write_text(json.dumps([{"title": d.title, "url": d.url, "reliability": d.reliability,
                                         "text_license": d.text_license, "content": d.content,
                                         "facts": [f.__dict__ for f in d.facts]} for d in bundle.docs],
                                       indent=2, ensure_ascii=False), encoding="utf-8")
        for doc in bundle.docs:
            rid = new_id("res")
            ctx.db.insert("research", {
                "research_id": rid, "topic_id": topic_id, "provider": provider.name, "title": doc.title,
                "url": doc.url, "retrieved_at": now_iso(), "content_path": str(snapshot),
                "content_hash": hashlib.sha256(doc.content.encode("utf-8")).hexdigest(),
                "text_license": doc.text_license, "reliability": doc.reliability, "summary": doc.content[:500],
            })
            n_docs += 1
            for fact in doc.facts:
                ctx.db.insert("research_facts", {
                    "fact_id": new_id("fact"), "research_id": rid, "topic_id": topic_id, "local_key": fact.local_key,
                    "text": fact.text, "own_words": int(fact.own_words), "source_title": fact.source_title,
                    "source_url": fact.source_url, "extra_sources_json": fact.extra_sources or None,
                    "tags_json": {"tags": fact.tags, "question": fact.question} if (fact.tags or fact.question) else None,
                    "fact_date": fact.fact_date, "created_at": now_iso(),
                })
                n_facts += 1
    total = ctx.db.scalar("SELECT COUNT(*) FROM research_facts WHERE topic_id = ?", (topic_id,))
    status = "RESEARCHED" if total >= int(ctx.cfg.get("research.min_facts")) else "INSUFFICIENT"
    ctx.db.update("topics", topic_id, {"research_status": status, "updated_at": now_iso()})
    (out_dir / "hook_ideas.json").write_text(json.dumps(hook_ideas, indent=2), encoding="utf-8")
    return {"facts": total, "new_facts": n_facts, "docs": n_docs, "hook_ideas": hook_ideas,
            "provider_errors": provider_errors, "status": status}


def load_facts(ctx, topic_id: str) -> list[dict]:
    rows = ctx.db.query(
        "SELECT f.*, r.reliability, r.text_license, r.provider FROM research_facts f "
        "JOIN research r ON r.research_id = f.research_id WHERE f.topic_id = ? ORDER BY f.created_at, f.rowid",
        (topic_id,))
    for r in rows:
        meta = r.get("tags_json") or {}
        r["tags"] = meta.get("tags", []) if isinstance(meta, dict) else []
        r["question"] = meta.get("question") if isinstance(meta, dict) else None
    return rows


def load_hook_ideas(ctx, topic_id: str) -> list[str]:
    topic = ctx.db.require("topics", topic_id)
    path = ctx.ws.dir("research") / topic["slug"] / "hook_ideas.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
