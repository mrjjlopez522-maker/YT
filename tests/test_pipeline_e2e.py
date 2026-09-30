"""End-to-end: topic -> research -> sources -> rights -> script -> narration -> storyboard -> render ->
captions -> QC -> review page -> approval -> (dry-run) upload -> analytics. Uses only self-made CC0 media."""
import json
from pathlib import Path

import pytest

from studio.analytics import collector, experiments, finance
from studio.analytics.costs import cost_summary
from studio.analytics.dashboard import dashboard_data
from studio.errors import ApprovalRequiredError, DailyLimitError, StateTransitionError, ValidationError
from studio.pipeline import orchestrator, states
from studio.publish import youtube
from studio.qc import duplicates
from studio.review import review
from studio.review.html import write_dashboard


@pytest.fixture(scope="module")
def produced(tmp_path_factory, fixture_media):
    """Run the whole pipeline once for this module (it takes ~1 minute)."""
    import shutil
    from .conftest import make_ctx
    home = tmp_path_factory.mktemp("studio")
    ctx = make_ctx(home, overrides={"research": {"providers": ["local_notes"]},
                                    "source_policy": {"providers": ["local_library"]},
                                    "production": {"x264_preset": "veryfast"}})
    for f in (fixture_media / "library").iterdir():
        shutil.copy2(f, ctx.ws.home / "sources" / "library" / f.name)
    for f in (fixture_media / "notes").iterdir():
        shutil.copy2(f, ctx.ws.home / "research" / "notes" / f.name)
    result = orchestrator.run_pipeline(ctx, topic="Conway's Game of Life")
    yield ctx, result
    ctx.close()


def test_pipeline_reaches_review_with_everything_traceable(produced):
    ctx, res = produced
    assert res["status"] == "REVIEW", json.dumps(res, default=str)[:2000]
    vid = res["video_id"]
    v = ctx.db.get("videos", vid)
    # deterministic naming
    assert vid.endswith("_conways-game-of-life_video-001") and Path(v["render_path"]).name == f"{vid}.mp4"
    # traceability: video -> topic -> research -> claims -> script -> scenes -> sources -> licenses -> assets
    script = ctx.db.get("scripts", v["script_id"])
    assert script["topic_id"] == v["topic_id"]
    claims = ctx.db.select("claims", {"script_id": script["script_id"]})
    assert claims and all(c["fact_id"] and c["status"] == "VERIFIED" for c in claims)
    assert ctx.db.query("SELECT COUNT(*) AS n FROM research_facts f JOIN research r ON r.research_id = f.research_id "
                        "WHERE f.fact_id IN (SELECT fact_id FROM claims WHERE script_id = ?)",
                        (script["script_id"],))[0]["n"] >= 1
    scenes = ctx.db.select("scenes", {"video_id": vid})
    used = {s["visual_source"] for s in scenes if s["visual_source"]}
    assert used
    for sid in used:
        lic = ctx.db.select("licenses", {"source_id": sid})[0]
        assert lic["verification_status"] == "VERIFIED" and Path(lic["evidence_path"]).exists()
    kinds = {a["kind"] for a in ctx.db.select("assets", {"video_id": vid})}
    assert {"voice", "music", "sfx", "ambience", "mix", "captions_ass", "captions_srt", "render", "thumbnail",
            "review_page"} <= kinds
    assert len([a for a in ctx.db.select("assets", {"video_id": vid}) if a["kind"] == "thumbnail"]) == 3
    # QC gate passed every blocking check
    qc = v["qc_report_json"]
    assert qc["passed"] and not qc["failed"]
    names = {c["name"] for c in qc["checks"]}
    for required in ("legal_source_verification", "rights_metadata_exists", "original_script_exists",
                     "original_narration_exists", "fact_checking_complete", "captions_synchronized",
                     "audio_quality_acceptable", "video_resolution_correct", "aspect_ratio_9_16", "no_black_frames",
                     "no_corrupted_frames", "no_excessive_silence", "no_source_watermark", "no_unauthorized_music",
                     "no_misleading_claims", "no_duplicate_content", "hook_exists", "ending_payoff_exists"):
        assert required in names
    # review page shows everything a reviewer needs
    page = Path(res["review_page"]).read_text()
    for needle in ("<video", "Title options", "Description", "Script", "Fact sources", "license", "Risk flags",
                   "--approve"):
        assert needle in page
    # metadata
    md = v["metadata_json"]
    assert len(md["descriptions"]) == 3 and len(md["keywords"]) == 10 and len(md["hashtag_sets"]) == 5
    # history recorded every transition
    path = [h["to_status"] for h in ctx.db.history(vid)]
    assert path == ["IDEA", "RESEARCHING", "SOURCING", "SCRIPTING", "EDITING", "QC", "REVIEW"]


def test_upload_requires_approval_and_defaults_to_dry_run(produced):
    ctx, res = produced
    vid = res["video_id"]
    with pytest.raises(ApprovalRequiredError):
        youtube.upload(ctx, vid)
    review.approve(ctx, vid, "tester")
    with pytest.raises(ApprovalRequiredError):          # public needs explicit permission
        youtube.upload(ctx, vid, privacy="public")
    with pytest.raises(ApprovalRequiredError):          # live needs DRY_RUN off
        youtube.upload(ctx, vid, live=True)
    up = youtube.upload(ctx, vid)
    assert up["status"] == "DRY_RUN" and up["privacy_status"] == "private"
    body = up["request_json"]["body"]
    assert body["status"]["privacyStatus"] == "private" and len(body["snippet"]["title"]) <= 100
    assert "Sources:" in body["snippet"]["description"]
    assert ctx.db.get("videos", vid)["status"] == "APPROVED"  # a dry run publishes nothing


def test_live_upload_path_with_fake_youtube_client(produced, monkeypatch):
    ctx, res = produced
    vid = res["video_id"]
    if ctx.db.get("videos", vid)["status"] == "REVIEW":
        review.approve(ctx, vid, "tester")
    review._record(ctx, vid, "APPROVE", "tester", allow_public=True, notes="public ok")
    monkeypatch.setenv("DRY_RUN", "false")
    calls = {}

    class Req:
        def __init__(self, kw):
            calls["insert"] = kw

        def next_chunk(self):
            return None, {"id": "yt123"}

    class Videos:
        def insert(self, **kw):
            return Req(kw)

    class Service:
        def videos(self):
            return Videos()

    up = youtube.upload(ctx, vid, privacy="unlisted", live=True, service=Service())
    assert up["status"] == "UPLOADED" and up["youtube_video_id"] == "yt123"
    assert calls["insert"]["part"] == "snippet,status"
    assert calls["insert"]["body"]["status"]["privacyStatus"] == "unlisted"
    assert ctx.db.get("videos", vid)["status"] == "PUBLISHED"


def test_request_body_is_valid_for_official_client(produced):
    """Build (not send) the request with google-api-python-client's bundled discovery document."""
    googleapiclient = pytest.importorskip("googleapiclient.discovery")
    from googleapiclient.http import MediaFileUpload
    ctx, res = produced
    v = ctx.db.get("videos", res["video_id"])
    body = youtube.build_request_body(ctx, v, privacy="private", publish_at="2030-01-01T10:00:00Z")
    svc = googleapiclient.build("youtube", "v3", developerKey="offline-test", static_discovery=True)
    req = svc.videos().insert(part="snippet,status", body=body,
                              media_body=MediaFileUpload(v["render_path"], mimetype="video/mp4", resumable=True))
    assert "upload/youtube/v3/videos" in req.uri and "part=snippet%2Cstatus" in req.uri


def test_analytics_experiments_dashboard_finance(produced, tmp_path):
    ctx, res = produced
    vid = res["video_id"]
    collector.snapshot(ctx, vid, source="manual", views=1200, likes=80, avg_view_percentage=71.5,
                       subscribers_gained=6)
    csv = tmp_path / "Table data.csv"
    title = ctx.db.get("videos", vid)["selected_title"].replace('"', '""')
    csv.write_text("Content,Video title,Views,Average view duration,Average percentage viewed (%),Likes\n"
                   f'Total,,1500,,,\nyt123,"{title}",1500,0:00:31,68.2,95\n')
    assert collector.import_studio_csv(ctx, csv) == 1
    latest = collector.latest_by_video(ctx)[vid]
    assert latest["views"] == 1500 and latest["avg_view_duration"] == 31
    with pytest.raises(ValidationError):
        collector.snapshot(ctx, vid, source="manual", views=-5)
    exp = experiments.create(ctx, name="hook style", variable="HOOK", variants=["question", "statement"])
    experiments.assign(ctx, exp, vid, experiments.next_variant(ctx, exp))
    result = experiments.analyze(ctx, exp)
    assert result["status"] == "INSUFFICIENT_DATA" and "No conclusion" in result["message"]
    data = dashboard_data(ctx)
    assert data["kpis"]["total_videos"] == 1 and data["kpis"]["total_views"] == 1500
    assert "Not enough" in data["what_is_working"][0]
    assert write_dashboard(ctx, data).exists()
    costs = cost_summary(ctx)
    assert costs["videos_costed"] == 1 and costs["COST_PER_1000_VIDEOS"] == pytest.approx(costs["COST_PER_VIDEO"] * 1000)
    fin = finance.model(ctx)
    assert "hypothetical" not in fin                         # no RPM is ever assumed
    fin = finance.model(ctx, hypothetical_rpm=0.05)
    assert fin["hypothetical"]["label"].startswith("HYPOTHETICAL") and fin["hypothetical"]["monthly_revenue"] == 0
    finance.add_revenue(ctx, amount_usd=150, category="sponsorship", period_start="2026-09-01",
                        period_end="2026-09-30", video_id=vid)
    assert finance.model(ctx)["actual"]["revenue_total"] == 150


def test_duplicate_detection_flags_a_near_copy(produced):
    ctx, res = produced
    a = duplicates._profile(ctx, ctx.db.get("videos", res["video_id"]))
    sims = duplicates.compare_profiles(a, dict(a, video_id="other"))
    assert sims["script"] == 1.0 and sims["visual_sequence"] == 1.0 and sims["source_clips"] == 1.0
    different = dict(a, script="Tidal forces lock the Moon's rotation to its orbit.", hook="Why one face?",
                     title="Tidal locking", scenes=[], topic="Tidal locking", topic_id="t2")
    far = duplicates.compare_profiles(a, different)
    assert max(far[k] for k in duplicates.BLOCKING) < 0.3


def test_state_machine_and_daily_limit(produced):
    ctx, res = produced
    with pytest.raises(StateTransitionError):
        states.check("IDEA", "PUBLISHED")
    with pytest.raises(StateTransitionError):
        states.check("REJECTED", "APPROVED")
    ctx.cfg.data["production"]["max_daily_videos"] = 1
    with pytest.raises(DailyLimitError):
        orchestrator.create_video(ctx, ctx.db.get("videos", res["video_id"])["topic_id"])


def test_failed_stage_is_recorded_and_resumable(ctx):
    res = orchestrator.run_pipeline(ctx, topic="A topic nobody researched")
    assert res["status"] == "FAILED" and res["failed_stage"] == "research" and res["hint"]
    v = ctx.db.get("videos", res["video_id"])
    assert v["status"] == "FAILED" and v["failed_stage"] == "research"
    assert ctx.db.select("errors", {"video_id": v["video_id"]})
