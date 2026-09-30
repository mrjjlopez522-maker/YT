import datetime as dt

import pytest
import yaml

from studio.errors import ProviderError
from studio.research import niche
from studio.research.providers import LocalNotesProvider, WikipediaProvider
from studio.research.topic_research import get_or_create_topic, load_facts, research_topic
from studio.research.trends import (ManualTrendProvider, RSSTrendProvider, WikipediaPageviewsProvider,
                                    classify_series, discover_trends)

from .conftest import FakeHttp


def test_local_notes_research(ctx_with_library):
    ctx = ctx_with_library
    topic = get_or_create_topic(ctx, "Conway's Game of Life")
    res = research_topic(ctx, topic["topic_id"])
    assert res["status"] == "RESEARCHED" and res["facts"] == 10
    facts = load_facts(ctx, topic["topic_id"])
    assert all(f["source_url"] or f["source_title"] for f in facts)
    assert all(f["own_words"] == 1 for f in facts)
    f9 = next(f for f in facts if f["local_key"] == "f9")
    assert f9["extra_sources_json"][0]["url"].endswith("Gosper_glider_gun")
    # re-running replaces rather than duplicates
    research_topic(ctx, topic["topic_id"])
    assert len(load_facts(ctx, topic["topic_id"])) == 10


def test_notes_without_citations_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({"topic": "Bad", "sources": [{"id": "s1", "title": "t"}],
                                                       "facts": [{"id": "f1", "text": "Uncited claim."}]}))
    with pytest.raises(ProviderError):
        LocalNotesProvider(tmp_path).research("Bad")


def test_missing_topic_research_is_insufficient(ctx):
    topic = get_or_create_topic(ctx, "A topic with no notes")
    assert research_topic(ctx, topic["topic_id"])["status"] == "INSUFFICIENT"


def test_wikipedia_provider_marks_text_as_not_own_words():
    http = FakeHttp({
        "list": None,
    })
    extract = ("The Tacoma Narrows Bridge was a suspension bridge in Washington. It opened on July 1, 1940. "
               "The bridge collapsed on November 7, 1940 in winds of about 64 kilometres per hour.\n== References ==\nx")

    def route(url, params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": "Tacoma Narrows Bridge (1940)"}]}}
        return {"query": {"pages": [{"title": "Tacoma Narrows Bridge (1940)", "extract": extract,
                                     "fullurl": "https://en.wikipedia.org/wiki/Tacoma_Narrows_Bridge_(1940)"}]}}
    http.routes = {"wikipedia.org": route}
    bundle = WikipediaProvider(http).research("Tacoma Narrows Bridge")
    doc = bundle.docs[0]
    assert doc.text_license == "CC-BY-SA-4.0" and doc.reliability == "tertiary"
    assert doc.facts and all(not f.own_words for f in doc.facts)
    assert "References" not in doc.content


# -- trends -----------------------------------------------------------------------
def test_classify_series():
    steady = [100 + (i % 3) for i in range(60)]
    assert classify_series(steady)["timeliness"] == "evergreen"
    rising = [100] * 53 + [200] * 7
    r = classify_series(rising)
    assert r["timeliness"] == "rising" and r["ratio"] == 2.0
    breaking = [100] * 53 + [100, 100, 100, 150, 900, 1500, 2500]
    assert classify_series(breaking)["timeliness"] == "breaking"
    assert classify_series([1, 2, 3])["timeliness"] == "insufficient_data"
    seasonal = classify_series(rising, last_year_window=[300] * 14, last_year_baseline=[100] * 40)
    assert seasonal["timeliness"] == "seasonal"


def test_pageviews_provider_uses_measured_data_only():
    def route(url, params):
        if "/top/" in url:
            return {"items": [{"articles": [{"article": "Main_Page", "views": 9}, {"article": "Special:Search", "views": 8},
                                            {"article": "Comet_X", "views": 7}]}]}
        return {"items": [{"views": 100}] * 53 + [{"views": 400}] * 7}
    p = WikipediaPageviewsProvider(FakeHttp({"wikimedia.org": route}), today=dt.date(2026, 9, 30), check_last_year=False)
    topics = p.discover(10)
    assert [t.topic for t in topics] == ["Comet X"]
    assert topics[0].trend_signal == 4.0 and topics[0].evidence["as_of"] == "2026-09-29"


def test_rss_parse_and_recurrence():
    now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
    xml = """<rss><channel>
      <item><title>Artemis Program reaches milestone</title><pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>
      <item><title>Engineers review Artemis Program schedule</title><pubDate>Tue, 29 Sep 2026 12:00:00 GMT</pubDate></item>
      <item><title>Old story about Artemis Program</title><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
    </channel></rss>"""
    p = RSSTrendProvider(FakeHttp({"feed": xml}), ["https://example.org/feed"], now=now)
    topics = p.discover(5)
    assert topics[0].topic == "Artemis Program" and topics[0].trend_signal == 2.0


def test_discover_trends_manual_and_outage(ctx, tmp_path):
    ideas = tmp_path / "ideas.yaml"
    ideas.write_text(yaml.safe_dump({"ideas": [{"topic": "Tidal locking", "category": "space", "evergreen": True}]}))
    out = discover_trends(ctx, providers=[ManualTrendProvider(ideas), WikipediaPageviewsProvider(FakeHttp({}))])
    assert [t["topic"] for t in out["topics"]] == ["Tidal locking"]
    assert out["topics"][0]["trend_signal"] is None  # never invented
    assert "wikipedia_pageviews" in out["provider_errors"]


# -- niche ------------------------------------------------------------------------
class FakeNicheData:
    today = dt.date(2026, 9, 30)

    def __init__(self, scale):
        self.scale = scale

    def wiki_search(self, term, limit=50):
        return 1000 * self.scale, [f"{term} {i}" for i in range(5 * self.scale)]

    def pageviews(self, article, days=90):
        return [100 * self.scale + (i % 5) for i in range(90)]

    def commons_video_hits(self, term):
        return 10 * self.scale

    def sample_candidates(self, term, n=5):
        from studio.sources.providers import SourceCandidate
        from studio.sources.rights import LicenseInfo
        return [SourceCandidate("u1", "x", "t", "video", LicenseInfo("CC0-1.0", evidence_kind="structured_api")),
                SourceCandidate("u2", "x", "t", "video", LicenseInfo("CC-BY-NC-4.0", evidence_kind="structured_api",
                                                                      creator="c"))]

    def youtube_total(self, q):
        return None


class RoutingNicheData(FakeNicheData):
    scales = {"history": 1, "science": 2, "space": 3}

    def __init__(self):
        super().__init__(1)

    def wiki_search(self, term, limit=50):
        self.scale = next((v for k, v in self.scales.items() if k in term.lower()), 1)
        return super().wiki_search(term, limit)


def test_niche_report_labels_and_no_ranking(ctx):
    from studio.research.niche import PublicApiNicheData
    rep = niche.build_report(ctx, data=FakeNicheData(2), niches=["history", "science", "space"])
    r = rep["results"]["science"]
    assert r["CONTENT_VOLUME"].label == "FACT"
    assert r["LEGAL_SOURCE_AVAILABILITY"].value == 0.5 and r["LEGAL_SOURCE_AVAILABILITY"].label == "ESTIMATE"
    assert r["SPONSORSHIP_POTENTIAL"].label == "ASSUMPTION"
    assert r["COMPETITION"].label == "UNKNOWN"
    md = open(rep["markdown_path"]).read()
    assert "does **not** rank" in md and "best" not in md.lower()
    # network failure -> UNKNOWN, never guessed
    offline = niche.build_report(ctx, data=PublicApiNicheData(FakeHttp({}), today=dt.date(2026, 9, 30)),
                                 niches=["history"])
    h = offline["results"]["history"]
    assert h["CONTENT_VOLUME"].label == "UNKNOWN" and h["CONTENT_VOLUME"].value is None
    assert h["ORIGINALITY_POTENTIAL"].label == "ASSUMPTION"
