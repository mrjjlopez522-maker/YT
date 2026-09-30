"""Config, database, safety switches, CLI entry point, calendar and finance."""
import datetime as dt

import pytest

from studio.errors import ConfigError, ValidationError
from conftest import load_cli, make_ctx


def test_tables_and_extra_columns(ctx):
    tables = {r["name"] for r in ctx.db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    required = {"topics", "trends", "ideas", "sources", "licenses", "research", "claims", "scripts", "scenes", "assets",
                "audio", "videos", "experiments", "uploads", "analytics", "errors", "formats", "series",
                "research_packets", "comment_prompts"}
    assert required <= tables
    cols = {r["name"] for r in ctx.db.query("PRAGMA table_info(analytics)")}
    assert {"saves", "completion_rate", "retention_buckets_json", "followers_gained"} <= cols
    assert ctx.db.path.name == "tiktok.sqlite3"


def test_safety_defaults(ctx):
    assert ctx.cfg.dry_run is True
    assert ctx.cfg.auto_publish is False
    assert ctx.cfg.manual_approval is True


def test_reference_tables_synced(ctx):
    assert ctx.db.get("formats", "unexpected_fact_reveal")["evidence_label"] == "ASSUMPTION"
    assert ctx.db.get("series", "visible-math") is not None
    accent = ctx.series["visible-math"]["visual_identity"]["accent"].lstrip("#")
    assert ctx.palette("visible-math")["accent"] == tuple(int(accent[i:i + 2], 16) for i in (0, 2, 4))


def test_invalid_config_rejected(tmp_path):
    with pytest.raises(ConfigError):
        make_ctx(tmp_path / "h", {"production": {"video_resolution": [1920, 1080]}})
    with pytest.raises(ConfigError):
        make_ctx(tmp_path / "h2", {"publishing": {"tiktok_mode": "scrape"}})


def test_cli_init_and_status(tmp_path, capsys):
    main = load_cli()
    home = tmp_path / "cli"
    make_ctx(home)
    assert main.main(["--home", str(home), "init"]) == 0
    out = capsys.readouterr().out
    assert '"DRY_RUN": true' in out and '"AUTO_PUBLISH": false' in out
    assert main.main(["--home", str(home), "status"]) == 0
    assert main.main(["--home", str(home), "formats"]) == 0


def test_calendar_slots_respect_days_per_week(ctx):
    from ttengine import content_calendar
    monday = dt.date(2026, 10, 5)
    slots = content_calendar.slots(ctx, days=7, start=monday)
    assert {dt.date.fromisoformat(s["date"]).weekday() for s in slots} == {0, 1, 2, 3, 4}
    assert all(s["window"] for s in slots)
    ov = content_calendar.overview(ctx)
    assert ov["videos_per_day"] == 1 and "board" in ov


def test_finance_uses_recorded_revenue_only(ctx):
    from ttengine import finance
    s = finance.summary(ctx)
    assert s["REVENUE_PER_VIDEO"] is None and s["PROFIT_PER_VIDEO"] is None
    assert s["BREAK_EVEN"]["views_per_video"] is None
    with pytest.raises(ValidationError):
        finance.add_revenue(ctx, amount_usd=5, category="projected", period_start="2026-09-01",
                            period_end="2026-09-30")
    finance.add_revenue(ctx, amount_usd=12.5, category="brand_deal", period_start="2026-09-01",
                        period_end="2026-09-30")
    assert finance.summary(ctx)["VERIFIED"]["revenue_total"] == 12.5
