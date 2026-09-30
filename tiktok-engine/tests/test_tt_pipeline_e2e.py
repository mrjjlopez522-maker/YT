"""End to end: topic -> research -> sources -> script -> voice -> edit -> QC -> REVIEW, then the
human review, publishing guards (dry run and a fake API), analytics and the audit trail.
Uses the local espeak voice so it needs no model download or network."""
import json
import subprocess
from pathlib import Path

import pytest

from studio.errors import ApprovalRequiredError, ValidationError
from conftest import load_cli, make_ctx
from ttengine import analytics, pipeline, publish, review, states


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    ctx = make_ctx(tmp_path_factory.mktemp("e2e") / "home")
    res = pipeline.run(ctx, topic="The Mandelbrot set")
    return ctx, res


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def test_pipeline_reaches_review_with_a_valid_render(produced):
    ctx, res = produced
    assert res["status"] == "REVIEW", res
    v = ctx.db.require("videos", res["video_id"])
    assert v["qc_status"] == "PASSED"
    streams = _probe(v["render_path"])
    assert streams["video"]["codec_name"] == "h264" and (streams["video"]["width"], streams["video"]["height"]) == (1080, 1920)
    assert streams["audio"]["codec_name"] == "aac"
    assert Path(res["review_page"]).is_file()


def test_calendar_states_in_order(produced):
    ctx, res = produced
    hist = [h["to_status"] for h in ctx.db.select("status_history", {"entity_id": res["video_id"]}, order_by="created_at")]
    assert hist[:8] == ["IDEA", "RESEARCH", "SOURCE", "SCRIPT", "VOICE", "EDIT", "QC", "REVIEW"]


def test_audio_tracks_scenes_and_originality(produced):
    ctx, res = produced
    vid = res["video_id"]
    assert {a["track"] for a in ctx.db.select("audio", {"video_id": vid})} == {"VOICE", "MUSIC", "SFX", "AMBIENCE", "MIX"}
    scenes = ctx.db.select("scenes", {"video_id": vid}, order_by="idx")
    assert len(scenes) >= 6
    for s in scenes:
        for field in ("scene_id", "start_time", "end_time", "visual_source", "narration", "caption", "transition",
                      "effect", "sound_effect"):
            assert field in s
    stats = ctx.db.require("videos", vid)["metadata_json"]["screen_stats"]
    assert stats["third_party_ratio"] == 0.0  # every visual is original and CC0-registered
    qc = {c["name"]: c for c in ctx.db.require("videos", vid)["qc_report_json"]["checks"]}
    for name in ("standalone_value", "promise_kept", "no_engagement_bait", "ai_disclosure", "audio_rights",
                 "caption_safe_zone", "research_packet_complete"):
        assert qc[name]["passed"], qc[name]


def test_review_page_and_audit_trail(produced):
    ctx, res = produced
    html = Path(res["review_page"]).read_text()
    for part in ("<video", "Post text", "Script", "Fact sources", "Sources &amp; licenses", "Cost", "Risk flags"):
        assert part in html
    a = review.audit(ctx, res["video_id"])
    assert [k.split("_")[0] for k in a if k[0].isdigit()] == [str(i) for i in range(1, 11)]
    assert a["2_footage_sources"] and all(f["verified"] == "VERIFIED" for f in a["2_footage_sources"])


def test_storyboard_cli(produced, capsys):
    main = load_cli()
    ctx, res = produced
    assert main.main(["--home", str(ctx.ws.home), "storyboard", "--video", res["video_id"]]) == 0
    assert "visual:" in capsys.readouterr().out


def test_publish_requires_approval_then_dry_runs(produced):
    ctx, res = produced
    vid = res["video_id"]
    with pytest.raises(ApprovalRequiredError):
        publish.publish(ctx, vid)
    review.approve(ctx, vid, "tester")
    out = publish.publish(ctx, vid)
    assert out["status"] == "DRY_RUN" and out["dry_run"] == 1
    plan = json.loads((ctx.ws.export_dir(ctx.db.require("videos", vid)["base_name"]) / "tiktok_publish_plan.json")
                      .read_text())
    assert plan["init"].endswith("/inbox/video/init/")  # default mode: draft to the creator's inbox
    assert ctx.db.require("videos", vid)["status"] == "APPROVED"  # a dry run publishes nothing
    with pytest.raises(ApprovalRequiredError):
        publish.publish(ctx, vid, live=True)  # DRY_RUN is still on


def test_direct_post_guards(produced):
    ctx, res = produced
    vid = res["video_id"]
    pub = ctx.cfg.data["publishing"]
    pub["tiktok_mode"] = "direct"
    try:
        with pytest.raises(ValidationError):
            publish.plan(ctx, vid, privacy_level=None)  # no default privacy
        with pytest.raises(ApprovalRequiredError):
            publish.plan(ctx, vid, privacy_level="PUBLIC_TO_EVERYONE")  # unaudited app
        pub["tiktok_app_audited"] = True
        with pytest.raises(ApprovalRequiredError):
            publish.plan(ctx, vid, privacy_level="PUBLIC_TO_EVERYONE")  # approval did not allow public
        with pytest.raises(ValidationError):
            publish.plan(ctx, vid, privacy_level="FOLLOWER_OF_CREATOR", creator={"privacy_level_options": ["SELF_ONLY"]})
        p = publish.plan(ctx, vid, privacy_level="SELF_ONLY",
                         creator={"privacy_level_options": ["SELF_ONLY"], "duet_disabled": True})
        assert p["post_info"]["disable_duet"] is True and p["post_info"]["privacy_level"] == "SELF_ONLY"
    finally:
        pub["tiktok_mode"] = "draft"
        pub.pop("tiktok_app_audited", None)


class FakeTikTok:
    def __init__(self):
        self.calls = []

    def creator_info(self):
        self.calls.append("creator_info")
        return {"privacy_level_options": ["SELF_ONLY"]}

    def init_draft(self, source_info):
        self.calls.append("init_draft")
        return {"publish_id": "v_inbox_file~v2.123", "upload_url": "https://upload.example/abc"}

    def upload(self, url, path, chunks):
        self.calls.append(("upload", len(chunks)))

    def status(self, publish_id):
        self.calls.append("status")
        return {"status": "SEND_TO_USER_INBOX"}


def test_live_publish_with_fake_api_records_upload(produced, monkeypatch):
    ctx, res = produced
    vid = res["video_id"]
    monkeypatch.setenv("DRY_RUN", "false")
    api = FakeTikTok()
    out = publish.publish(ctx, vid, live=True, api=api)
    assert api.calls[0] == "creator_info" and "init_draft" in api.calls and "status" in api.calls
    row = ctx.db.require("uploads", out["upload_id"])
    assert row["publish_id"] == "v_inbox_file~v2.123" and row["status"] == "UPLOADED" and row["dry_run"] == 0
    assert ctx.db.require("videos", vid)["status"] == "APPROVED"  # a draft is not a public post


def test_analytics_snapshot_and_compare(produced):
    ctx, res = produced
    vid = res["video_id"]
    states.transition(ctx, vid, "PUBLISHED", reason="test: marked published by the creator")
    sid = analytics.snapshot(ctx, vid, source="manual", views=1000, likes=50, saves=20, completion_rate=0.31,
                             avg_watch_time=21.5, retention_curve=[(0, 1.0), (3, 0.7), (30, 0.35), (60, 0.2)])
    snap = ctx.db.get("analytics", sid)
    assert snap["retention_buckets_json"]["0-2s"] > 0
    assert ctx.db.require("videos", vid)["status"] == "ANALYTICS"
    cmp = analytics.compare(ctx, "hook_type")
    group = next(iter(cmp["groups"].values()))
    assert group["n"] == 1 and group["enough_data"] is False
    assert review.audit(ctx, vid)["10_performance"][0]["views"] == 1000
