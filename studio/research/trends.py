"""Trend discovery from legitimate, documented sources.

Trends are measured, never invented: a provider that returns no data yields no
topics. Every topic keeps the evidence (method, numbers, API) that produced
its signal.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import yaml

from ..errors import ProviderError
from ..http import HttpClient
from ..logging_setup import get_logger
from ..textutil import STOPWORDS
from .topic_research import get_or_create_topic

log = get_logger("research.trends")
_SKIP_PREFIXES = ("Special:", "Wikipedia:", "File:", "Portal:", "Help:", "Template:", "Category:", "Talk:", "User:")
_SKIP_TITLES = {"Main_Page", "-", "Undefined"}


@dataclass
class TrendTopic:
    topic: str
    source: str
    trend_signal: float | None
    timeliness: str
    evergreen_score: float | None = None
    category: str | None = None
    potential_angle: str | None = None
    evidence: dict = field(default_factory=dict)


def classify_series(views: list[int], last_year_window: list[int] | None = None,
                    last_year_baseline: list[int] | None = None) -> dict:
    """Describe a daily view series (oldest first). Pure function — unit tested.

    ratio      = mean(last 7 days) / median(the earlier days)   -> trend_signal
    evergreen  = 1 / (1 + coefficient of variation)              -> 0..1, higher = steadier
    timeliness = breaking | rising | seasonal | evergreen | recurring | insufficient_data
    """
    if len(views) < 21:
        return {"timeliness": "insufficient_data", "ratio": None, "evergreen_score": None}
    recent, base = views[-7:], views[:-7]
    base_med = statistics.median(base) or 1.0
    ratio = statistics.mean(recent) / base_med
    mean = statistics.mean(views)
    cv = statistics.pstdev(views) / mean if mean else 0.0
    evergreen = 1.0 / (1.0 + cv)
    spike = max(views[-3:]) / base_med
    seasonal = False
    if last_year_window and last_year_baseline:
        ly_base = statistics.median(last_year_baseline) or 1.0
        seasonal = statistics.mean(last_year_window) / ly_base >= 1.5
    if spike >= 5 and ratio >= 3:
        timeliness = "breaking"
    elif ratio >= 1.5 and seasonal:
        timeliness = "seasonal"
    elif ratio >= 1.5:
        timeliness = "rising"
    elif cv < 0.35:
        timeliness = "evergreen"
    else:
        timeliness = "recurring"
    return {"timeliness": timeliness, "ratio": round(ratio, 3), "evergreen_score": round(evergreen, 3),
            "recent_mean": round(statistics.mean(recent), 1), "baseline_median": round(base_med, 1),
            "cv": round(cv, 3), "days": len(views), "seasonal_last_year": seasonal}


class TrendProvider(ABC):
    name = "base"

    @abstractmethod
    def discover(self, limit: int) -> list[TrendTopic]:
        ...


class ManualTrendProvider(TrendProvider):
    """Your own editorial ideas. No measured signal is attached (trend_signal = None)."""
    name = "manual"

    def __init__(self, path: Path):
        self.path = Path(path)

    def discover(self, limit: int) -> list[TrendTopic]:
        if not self.path.is_file():
            return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        out = []
        for idea in (data.get("ideas") or [])[:limit]:
            out.append(TrendTopic(topic=idea["topic"], source=self.name, trend_signal=None,
                                  timeliness="evergreen" if idea.get("evergreen") else "unknown",
                                  category=idea.get("category"), potential_angle=idea.get("potential_angle"),
                                  evidence={"method": "manual editorial idea", "file": str(self.path)}))
        return out


class WikipediaPageviewsProvider(TrendProvider):
    """Wikimedia REST pageviews API: top articles, then each article's recent history."""
    name = "wikipedia_pageviews"
    BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"

    def __init__(self, http: HttpClient, project: str = "en.wikipedia", *, today: dt.date | None = None,
                 candidates: int = 15, history_days: int = 60, check_last_year: bool = True):
        self.http = http
        self.project = project
        self.today = today or dt.datetime.now(dt.timezone.utc).date()
        self.candidates = candidates
        self.history_days = history_days
        self.check_last_year = check_last_year

    def _daily(self, article: str, start: dt.date, end: dt.date) -> list[int]:
        url = (f"{self.BASE}/per-article/{self.project}/all-access/user/{quote(article, safe='')}/daily/"
               f"{start:%Y%m%d}00/{end:%Y%m%d}00")
        return [int(i["views"]) for i in self.http.get_json(url).get("items", [])]

    def discover(self, limit: int) -> list[TrendTopic]:
        day = self.today - dt.timedelta(days=1)
        top = self.http.get_json(f"{self.BASE}/top/{self.project}/all-access/{day:%Y/%m/%d}")
        articles = (top.get("items") or [{}])[0].get("articles", [])
        picked = [a["article"] for a in articles
                  if a["article"] not in _SKIP_TITLES and not a["article"].startswith(_SKIP_PREFIXES)][: self.candidates]
        out = []
        for art in picked:
            views = self._daily(art, day - dt.timedelta(days=self.history_days - 1), day)
            ly_window = ly_base = None
            if self.check_last_year:
                ly_day = day - dt.timedelta(days=365)
                ly = self._daily(art, ly_day - dt.timedelta(days=self.history_days - 1), ly_day + dt.timedelta(days=7))
                if len(ly) >= 21:
                    ly_window, ly_base = ly[-14:], ly[:-14]
            stats = classify_series(views, ly_window, ly_base)
            if stats["ratio"] is None:
                continue
            out.append(TrendTopic(topic=art.replace("_", " "), source=self.name, trend_signal=stats["ratio"],
                                  timeliness=stats["timeliness"], evergreen_score=stats["evergreen_score"],
                                  evidence={"method": "mean(last 7d) / median(prior days) of Wikipedia user pageviews",
                                            "api": self.BASE, "as_of": day.isoformat(), **stats}))
        out.sort(key=lambda t: t.trend_signal or 0, reverse=True)
        return out[:limit]


class YouTubeMostPopularProvider(TrendProvider):
    """YouTube Data API v3 `videos.list(chart=mostPopular)` — recurring tags across the chart."""
    name = "youtube_most_popular"
    API = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self, http: HttpClient, api_key: str | None, region: str = "US"):
        self.http = http
        self.api_key = api_key
        self.region = region

    def discover(self, limit: int) -> list[TrendTopic]:
        if not self.api_key:
            raise ProviderError("YOUTUBE_API_KEY is not set", hint="add it to .env to use the mostPopular chart")
        data = self.http.get_json(self.API, params={"part": "snippet", "chart": "mostPopular", "maxResults": "50",
                                                    "regionCode": self.region, "key": self.api_key})
        counts: Counter[str] = Counter()
        where: dict[str, list[str]] = {}
        for item in data.get("items", []):
            for tag in {t.lower().strip() for t in item.get("snippet", {}).get("tags", []) if len(t) > 3}:
                counts[tag] += 1
                where.setdefault(tag, []).append(item.get("id"))
        out = []
        for tag, n in counts.most_common(limit):
            if n < 2:
                break
            out.append(TrendTopic(topic=tag, source=self.name, trend_signal=float(n), timeliness="rising",
                                  evidence={"method": "count of mostPopular videos sharing this tag",
                                            "region": self.region, "video_ids": where[tag][:10]}))
        return out


class RSSTrendProvider(TrendProvider):
    """Recurring multi-word names across the configured RSS/Atom feeds."""
    name = "rss"
    _PHRASE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")

    def __init__(self, http: HttpClient, feeds: list[str], *, now: dt.datetime | None = None, window_hours: int = 72):
        self.http = http
        self.feeds = feeds
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self.window = dt.timedelta(hours=window_hours)

    @staticmethod
    def parse(xml_text: str) -> list[tuple[str, dt.datetime | None]]:
        root = ET.fromstring(xml_text)
        items = []
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag not in ("item", "entry"):
                continue
            title, when = None, None
            for child in node:
                ctag = child.tag.split("}")[-1]
                if ctag == "title":
                    title = (child.text or "").strip()
                elif ctag in ("pubDate", "published", "updated") and child.text:
                    try:
                        when = parsedate_to_datetime(child.text.strip())
                    except (TypeError, ValueError):
                        try:
                            when = dt.datetime.fromisoformat(child.text.strip().replace("Z", "+00:00"))
                        except ValueError:
                            when = None
            if title:
                items.append((title, when))
        return items

    def discover(self, limit: int) -> list[TrendTopic]:
        counts: Counter[str] = Counter()
        titles: dict[str, list[str]] = {}
        for feed in self.feeds:
            resp = self.http.get(feed)
            for title, when in self.parse(resp.text):
                if when and when.tzinfo and self.now - when > self.window:
                    continue
                for phrase in {p for p in self._PHRASE.findall(title) if p.split()[0].lower() not in STOPWORDS}:
                    counts[phrase] += 1
                    titles.setdefault(phrase, []).append(title)
        out = []
        for phrase, n in counts.most_common(limit):
            if n < 2:
                break
            out.append(TrendTopic(topic=phrase, source=self.name, trend_signal=float(n), timeliness="breaking",
                                  evidence={"method": f"items mentioning phrase within {self.window}",
                                            "feeds": self.feeds, "example_titles": titles[phrase][:5]}))
        return out


def build_trend_providers(ctx) -> list[TrendProvider]:
    reg = {
        "manual": lambda: ManualTrendProvider(ctx.cfg.config_file(ctx.cfg.get("trends.manual_file"))),
        "wikipedia_pageviews": lambda: WikipediaPageviewsProvider(ctx.http, ctx.cfg.get("trends.wikipedia_project")),
        "youtube_most_popular": lambda: YouTubeMostPopularProvider(ctx.http, ctx.cfg.secret("YOUTUBE_API_KEY"),
                                                                   ctx.cfg.get("trends.youtube_region")),
        "rss": lambda: RSSTrendProvider(ctx.http, ctx.cfg.get("trends.rss_feeds") or []),
    }
    return [reg[n]() for n in ctx.cfg.get("trends.providers") if n in reg]


def discover_trends(ctx, providers: list[TrendProvider] | None = None, limit: int = 20) -> dict:
    providers = providers if providers is not None else build_trend_providers(ctx)
    topics, errors = [], {}
    for p in providers:
        if isinstance(p, RSSTrendProvider) and not p.feeds:
            continue
        try:
            found = p.discover(limit)
        except ProviderError as exc:
            log.warning("trend provider %s failed: %s", p.name, exc)
            errors[p.name] = str(exc)
            ctx.db.record_error(stage="trends", exc=exc)
            continue
        for t in found:
            row = get_or_create_topic(ctx, t.topic, category=t.category, potential_angle=t.potential_angle,
                                      trend_signal=t.trend_signal, trend_source=t.source, trend_evidence=t.evidence,
                                      evergreen_score=t.evergreen_score, timeliness=t.timeliness)
            topics.append(row)
    return {"topics": topics, "provider_errors": errors}
