"""Niche Research Engine.

Produces a *data report*, not a ranking. Each factor is labelled:
  FACT        measured from a public API (method + date recorded)
  ESTIMATE    derived from measured data by a stated method
  ASSUMPTION  an editable prior from config/niches.yaml (not data)
  UNKNOWN     the measurement could not be made (reason recorded)

There is deliberately no overall score: you weigh the tradeoffs and choose.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from dataclasses import asdict, dataclass
from urllib.parse import quote

import yaml

from ..errors import ProviderError
from ..sources.providers import NasaImagesProvider, WikimediaCommonsProvider
from ..sources.rights import evaluate
from ..textutil import new_id, now_iso

FACTORS = ["CONTENT_VOLUME", "SOURCE_AVAILABILITY", "LEGAL_SOURCE_AVAILABILITY", "AUDIENCE_DEMAND",
           "TOPIC_REPEATABILITY", "ORIGINALITY_POTENTIAL", "SPONSORSHIP_POTENTIAL", "PRODUCTION_DIFFICULTY",
           "COMPETITION", "FACT_CHECKING_DIFFICULTY", "EVERGREEN_POTENTIAL"]
PRIOR_FACTORS = {"ORIGINALITY_POTENTIAL": "originality_potential", "SPONSORSHIP_POTENTIAL": "sponsorship_potential",
                 "PRODUCTION_DIFFICULTY": "production_difficulty",
                 "FACT_CHECKING_DIFFICULTY": "fact_checking_difficulty"}
HIGHER_IS_HARDER = {"COMPETITION", "PRODUCTION_DIFFICULTY", "FACT_CHECKING_DIFFICULTY"}


@dataclass
class Metric:
    value: float | None
    unit: str
    label: str
    method: str
    evidence: str = ""


class PublicApiNicheData:
    """Measurements from Wikipedia, Wikimedia Commons, NASA and (optionally) YouTube search."""

    def __init__(self, http, *, lang: str = "en", youtube_api_key: str | None = None, today: dt.date | None = None):
        self.http = http
        self.lang = lang
        self.api = f"https://{lang}.wikipedia.org/w/api.php"
        self.key = youtube_api_key
        self.today = today or dt.datetime.now(dt.timezone.utc).date()

    def wiki_search(self, term: str, limit: int = 50) -> tuple[int, list[str]]:
        d = self.http.get_json(self.api, params={"action": "query", "list": "search", "srsearch": term,
                                                 "srlimit": str(limit), "srinfo": "totalhits", "format": "json",
                                                 "formatversion": "2"})
        q = d.get("query", {})
        return int(q.get("searchinfo", {}).get("totalhits", 0)), [h["title"] for h in q.get("search", [])]

    def pageviews(self, article: str, days: int = 90) -> list[int]:
        end = self.today - dt.timedelta(days=1)
        start = end - dt.timedelta(days=days - 1)
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
               f"{self.lang}.wikipedia/all-access/user/{quote(article.replace(' ', '_'), safe='')}/daily/"
               f"{start:%Y%m%d}00/{end:%Y%m%d}00")
        return [int(i["views"]) for i in self.http.get_json(url).get("items", [])]

    def commons_video_hits(self, term: str) -> int:
        d = self.http.get_json(WikimediaCommonsProvider.API, params={
            "action": "query", "list": "search", "srsearch": f"filetype:video {term}", "srnamespace": "6",
            "srlimit": "1", "srinfo": "totalhits", "format": "json", "formatversion": "2"})
        return int(d.get("query", {}).get("searchinfo", {}).get("totalhits", 0))

    def sample_candidates(self, term: str, n: int = 5):
        out = []
        for provider in (WikimediaCommonsProvider(self.http), NasaImagesProvider(self.http)):
            try:
                out.extend(provider.search(term, n))
            except ProviderError:
                continue
        return out

    def youtube_total(self, query: str) -> int | None:
        if not self.key:
            return None
        d = self.http.get_json("https://www.googleapis.com/youtube/v3/search",
                               params={"part": "id", "q": query, "type": "video", "videoDuration": "short",
                                       "maxResults": "1", "key": self.key})
        return int(d.get("pageInfo", {}).get("totalResults", 0))


def _unknown(unit: str, method: str, exc: Exception) -> Metric:
    return Metric(None, unit, "UNKNOWN", method, f"not measured: {exc}")


def measure_niche(name: str, spec: dict, data: PublicApiNicheData, policy: dict) -> dict[str, Metric]:
    seeds = spec.get("seeds", [])
    priors = spec.get("priors", {})
    date = data.today.isoformat()
    m: dict[str, Metric] = {}

    try:
        hits, titles = 0, set()
        for s in seeds:
            n, t = data.wiki_search(s)
            hits += n
            titles.update(t)
        m["CONTENT_VOLUME"] = Metric(hits, "Wikipedia search hits", "FACT",
                                     f"sum of totalhits for seed searches on {date}", ", ".join(seeds))
        m["TOPIC_REPEATABILITY"] = Metric(len(titles), "distinct articles in top-50 results per seed", "ESTIMATE",
                                          "number of distinct subtopic articles surfaced by seed searches")
    except ProviderError as exc:
        m["CONTENT_VOLUME"] = _unknown("Wikipedia search hits", "Wikipedia search totalhits", exc)
        m["TOPIC_REPEATABILITY"] = _unknown("distinct articles", "distinct seed search results", exc)

    try:
        m["SOURCE_AVAILABILITY"] = Metric(sum(data.commons_video_hits(s) for s in seeds), "Commons video files",
                                          "FACT", f"Wikimedia Commons filetype:video search totalhits on {date}")
    except ProviderError as exc:
        m["SOURCE_AVAILABILITY"] = _unknown("Commons video files", "Commons search totalhits", exc)

    try:
        cands = [c for s in seeds[:2] for c in data.sample_candidates(s)]
        if not cands:
            raise ProviderError("no candidates returned")
        passed = sum(1 for c in cands if evaluate(c.license, **policy).accepted)
        m["LEGAL_SOURCE_AVAILABILITY"] = Metric(round(passed / len(cands), 3), "share passing rights policy",
                                                "ESTIMATE", f"sample of {len(cands)} Commons/NASA results through the "
                                                            f"rights engine on {date}")
    except ProviderError as exc:
        m["LEGAL_SOURCE_AVAILABILITY"] = _unknown("share passing rights policy", "sampled rights checks", exc)

    try:
        series = [data.pageviews(s) for s in seeds]
        series = [s for s in series if len(s) >= 30]
        if not series:
            raise ProviderError("no pageview history")
        medians = [statistics.median(s) for s in series]
        cvs = [statistics.pstdev(s) / statistics.mean(s) for s in series if statistics.mean(s) > 0]
        m["AUDIENCE_DEMAND"] = Metric(round(sum(medians)), "median daily Wikipedia views (sum of seeds)", "ESTIMATE",
                                      "proxy for general interest over 90 days; not a measure of YouTube demand")
        m["EVERGREEN_POTENTIAL"] = Metric(round(1 / (1 + statistics.mean(cvs)), 3), "0-1 (steadier = higher)",
                                          "ESTIMATE", "1/(1+mean coefficient of variation) of 90-day seed pageviews")
    except ProviderError as exc:
        m["AUDIENCE_DEMAND"] = _unknown("median daily views", "Wikipedia pageviews", exc)
        m["EVERGREEN_POTENTIAL"] = _unknown("0-1", "pageview stability", exc)

    try:
        total = data.youtube_total(f"{name.replace('_', ' ')} shorts")
        m["COMPETITION"] = (Metric(total, "YouTube search totalResults (approximate)", "ESTIMATE",
                                   "YouTube Data API search.list totalResults for short videos; YouTube documents "
                                   "this number as an approximation")
                            if total is not None else
                            Metric(None, "YouTube search results", "UNKNOWN", "YouTube search",
                                   "not measured: YOUTUBE_API_KEY not set"))
    except ProviderError as exc:
        m["COMPETITION"] = _unknown("YouTube search results", "YouTube search", exc)

    for factor, key in PRIOR_FACTORS.items():
        val = priors.get(key)
        m[factor] = Metric(val, "1-5 prior", "ASSUMPTION" if val is not None else "UNKNOWN",
                           "editable prior in config/niches.yaml — not measured")
    return m


def tradeoffs(results: dict[str, dict[str, Metric]]) -> dict[str, list[str]]:
    """Describe each niche relative to the median of the niches that have a value. Descriptive only."""
    notes: dict[str, list[str]] = {n: [] for n in results}
    for factor in FACTORS:
        vals = {n: r[factor].value for n, r in results.items() if r.get(factor) and r[factor].value is not None}
        if len(vals) < 3:
            continue
        med = statistics.median(vals.values())
        for n, v in vals.items():
            label = results[n][factor].label
            if v > med:
                word = "harder" if factor in HIGHER_IS_HARDER else "more favourable"
                notes[n].append(f"{factor} above median ({v} vs {med}; {label}) — {word}")
            elif v < med:
                word = "easier" if factor in HIGHER_IS_HARDER else "less favourable"
                notes[n].append(f"{factor} below median ({v} vs {med}; {label}) — {word}")
    for n, r in results.items():
        unknown = [f for f in FACTORS if r[f].label == "UNKNOWN"]
        if unknown:
            notes[n].append(f"not measured: {', '.join(unknown)}")
    return notes


def build_report(ctx, *, data: PublicApiNicheData | None = None, niches: list[str] | None = None) -> dict:
    spec = yaml.safe_load(ctx.cfg.config_file("config/niches.yaml").read_text(encoding="utf-8"))["niches"]
    names = niches or list(spec)
    data = data or PublicApiNicheData(ctx.http, lang=ctx.cfg.get("channel.language"),
                                      youtube_api_key=ctx.cfg.secret("YOUTUBE_API_KEY"))
    policy = {"allowed_licenses": ctx.cfg.get("source_policy.allowed_licenses"),
              "min_confidence": float(ctx.cfg.get("source_policy.min_rights_confidence")),
              "allow_share_alike": bool(ctx.cfg.get("source_policy.allow_share_alike"))}
    results = {n: measure_niche(n, spec[n], data, policy) for n in names}
    notes = tradeoffs(results)
    report_id = new_id("niche")
    for n, metrics in results.items():
        for factor, mt in metrics.items():
            ctx.db.insert("niche_metrics", {"report_id": report_id, "niche": n, "factor": factor, "value": mt.value,
                                            "unit": mt.unit, "label": mt.label, "method": mt.method,
                                            "evidence": mt.evidence, "created_at": now_iso()})
    date = data.today.isoformat()
    md = render_markdown(results, notes, date)
    out = ctx.ws.dir("research")
    (out / f"niche_report_{date}.md").write_text(md, encoding="utf-8")
    (out / f"niche_report_{date}.json").write_text(
        json.dumps({n: {f: asdict(m) for f, m in r.items()} for n, r in results.items()}, indent=2), encoding="utf-8")
    return {"report_id": report_id, "results": results, "notes": notes, "markdown_path": str(out / f"niche_report_{date}.md")}


def render_markdown(results: dict[str, dict[str, Metric]], notes: dict[str, list[str]], date: str) -> str:
    lines = [f"# Niche research report — {date}", "",
             "This report shows data and tradeoffs. It does **not** rank niches or pick a winner.",
             "Labels: FACT (measured), ESTIMATE (derived, method stated), ASSUMPTION (editable prior, not data), "
             "UNKNOWN (not measured).", "",
             "| Niche | " + " | ".join(FACTORS) + " |", "|---|" + "---|" * len(FACTORS)]
    for n, r in results.items():
        cells = []
        for f in FACTORS:
            mt = r[f]
            cells.append(f"{'—' if mt.value is None else mt.value} ({mt.label})")
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    lines += ["", "## Methods", ""]
    first = next(iter(results.values()), {})
    for f in FACTORS:
        if f in first:
            lines.append(f"- **{f}** — {first[f].unit}: {first[f].method}")
    lines += ["", "## Tradeoffs per niche (descriptive)", ""]
    for n, items in notes.items():
        lines.append(f"### {n}")
        lines += [f"- {i}" for i in items] or ["- no comparable measurements"]
        lines.append("")
    return "\n".join(lines)
