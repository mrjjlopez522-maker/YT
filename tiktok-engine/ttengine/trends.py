"""Trend Discovery Engine.

Legitimate inputs only:
  * observations  — trends YOU recorded (e.g. from TikTok Creative Center or your
                    feed), with whatever numbers you actually saw
  * manual        — your own editorial ideas (no signal attached)
  * wikipedia_pageviews / rss / youtube_most_popular — measured public data (studio providers)
  * own_analytics — topics that performed well on this account
There is no TikTok scraping and no use of the academic-only Research API.
A trend without a measured number keeps trend_signal = NULL.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import yaml

from studio.errors import ProviderError
from studio.logging_setup import get_logger
from studio.research.topic_research import get_or_create_topic
from studio.research.trends import (ManualTrendProvider, RSSTrendProvider, WikipediaPageviewsProvider,
                                    YouTubeMostPopularProvider)
from studio.textutil import now_iso, stable_id, today

log = get_logger("tiktok.trends")
EXPIRY_DAYS = {"breaking": 3, "cultural_moment": 5, "rising": 14, "emerging": 21, "seasonal": 30, "format": 30,
               "question": 60, "search": 60}
TREND_TYPES = ("rising", "emerging", "evergreen", "seasonal", "cultural_moment", "search", "question", "format", "sound")


@dataclass
class Trend:
    topic: str
    trend_source: str
    trend_type: str
    category: str | None = None
    trend_signal: float | None = None
    growth_signal: float | None = None
    content_volume: float | None = None
    potential_angle: str | None = None
    expiration_estimate: str | None = None
    evidence: dict = field(default_factory=dict)
    format: dict | None = None


def expiry_for(trend_type: str, detected: dt.date, default_days: int) -> str:
    if trend_type == "evergreen":
        return "evergreen"
    return (detected + dt.timedelta(days=EXPIRY_DAYS.get(trend_type, default_days))).isoformat()


class ObservationsProvider:
    name = "observation"

    def __init__(self, path):
        self.path = path

    def discover(self, limit: int) -> list[Trend]:
        if not self.path.is_file():
            return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        out = []
        for o in (data.get("observations") or [])[:limit]:
            tt = o.get("trend_type") or "rising"
            if tt not in TREND_TYPES:
                raise ProviderError(f"Unknown trend_type {tt!r} in {self.path.name}")
            out.append(Trend(
                topic=o["topic"], trend_source=self.name, trend_type=tt, category=o.get("category"),
                trend_signal=o.get("signal"), growth_signal=o.get("growth"), content_volume=o.get("content_volume"),
                potential_angle=o.get("potential_angle"),
                expiration_estimate=str(o["expires"]) if o.get("expires") else None,
                evidence={"method": "recorded by you", "where": o.get("where"),
                          "observed_at": str(o.get("observed_at") or "")},
                format=o.get("format")))
        return out


class _StudioAdapter:
    """Wraps a studio TrendProvider and maps its topics onto TikTok trend records."""

    def __init__(self, provider):
        self.provider = provider
        self.name = provider.name

    def discover(self, limit: int) -> list[Trend]:
        out = []
        for t in self.provider.discover(limit):
            ev = t.evidence or {}
            growth = round(t.trend_signal - 1.0, 3) if (t.trend_signal is not None and self.name == "wikipedia_pageviews") \
                else None
            tt = {"breaking": "cultural_moment", "rising": "rising", "seasonal": "seasonal", "evergreen": "evergreen",
                  "recurring": "search"}.get(t.timeliness, "evergreen" if self.name == "manual" else "rising")
            out.append(Trend(topic=t.topic, trend_source=self.name, trend_type=tt, category=t.category,
                             trend_signal=t.trend_signal, growth_signal=growth,
                             content_volume=ev.get("recent_mean"), potential_angle=t.potential_angle, evidence=ev))
        return out


def build_providers(ctx) -> list:
    cfg = ctx.cfg
    reg = {
        "observations": lambda: ObservationsProvider(cfg.config_file(cfg.get("trends.observations_file"))),
        "manual": lambda: _StudioAdapter(ManualTrendProvider(cfg.config_file(cfg.get("trends.manual_file")))),
        "wikipedia_pageviews": lambda: _StudioAdapter(WikipediaPageviewsProvider(ctx.http, cfg.get("trends.wikipedia_project"))),
        "rss": lambda: _StudioAdapter(RSSTrendProvider(ctx.http, cfg.get("trends.rss_feeds") or [])),
        "youtube_most_popular": lambda: _StudioAdapter(YouTubeMostPopularProvider(
            ctx.http, cfg.secret("YOUTUBE_API_KEY"), cfg.get("trends.youtube_region"))),
    }
    return [reg[n]() for n in cfg.get("trends.providers") if n in reg]


def store(ctx, t: Trend) -> dict:
    detected = today()
    topic = get_or_create_topic(ctx, t.topic, category=t.category, potential_angle=t.potential_angle,
                                trend_signal=t.trend_signal, trend_source=t.trend_source, trend_evidence=t.evidence,
                                timeliness=t.trend_type)
    row = {
        "trend_id": stable_id("trd", t.trend_source, t.topic.lower(), detected.isoformat()), "topic": t.topic,
        "category": t.category, "date_detected": detected.isoformat(), "trend_source": t.trend_source,
        "trend_type": t.trend_type, "trend_signal": t.trend_signal, "growth_signal": t.growth_signal,
        "content_volume": t.content_volume, "potential_angle": t.potential_angle,
        "expiration_estimate": t.expiration_estimate or expiry_for(t.trend_type, detected,
                                                                   int(ctx.cfg.get("trends.default_expiry_days"))),
        "evidence_json": t.evidence, "topic_id": topic["topic_id"], "status": "NEW", "created_at": now_iso(),
    }
    existing = ctx.db.get("trends", row["trend_id"])
    if existing:
        row["status"] = existing["status"]
    ctx.db.insert("trends", row, or_replace=True)
    if t.format:
        from .formats import record_observation
        record_observation(ctx, trend_id=row["trend_id"], observer="you", **t.format)
    return row


def discover(ctx, providers: list | None = None, limit: int = 25) -> dict:
    providers = providers if providers is not None else build_providers(ctx)
    stored, errors = [], {}
    for p in providers:
        if isinstance(getattr(p, "provider", None), RSSTrendProvider) and not p.provider.feeds:
            continue
        try:
            found = p.discover(limit)
        except ProviderError as exc:
            log.warning("trend provider %s failed: %s", p.name, exc)
            errors[p.name] = str(exc)
            ctx.db.record_error(stage="trends", exc=exc)
            continue
        stored += [store(ctx, t) for t in found]
    expire(ctx)
    return {"trends": stored, "provider_errors": errors}


def expire(ctx) -> int:
    cur = ctx.db.conn.execute("UPDATE trends SET status = 'EXPIRED' WHERE status = 'NEW' AND expiration_estimate "
                              "!= 'evergreen' AND expiration_estimate < ?", (today().isoformat(),))
    return cur.rowcount


def active(ctx) -> list[dict]:
    """Current trends: measured signals first, then by freshness. No invented ordering signal."""
    rows = ctx.db.query("SELECT * FROM trends WHERE status = 'NEW' ORDER BY (trend_signal IS NULL), trend_signal DESC, "
                        "date_detected DESC")
    return rows
