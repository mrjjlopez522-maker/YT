"""Publishing helpers (OAuth PKCE, chunking), analytics, experiments."""
import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from studio.errors import ValidationError
from ttengine import analytics, experiments, publish

MB = 1024 * 1024


def test_pkce_and_authorize_url():
    verifier, challenge = publish.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expect
    url = publish.authorize_url("key123", "http://localhost:8765/callback", "st", challenge)
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == [challenge]
    assert "password" not in url.lower()


def test_chunk_plan_follows_media_transfer_rules():
    info, chunks = publish.chunk_plan(3 * MB)
    assert info["total_chunk_count"] == 1 and chunks == [(0, 3 * MB - 1)]
    info, chunks = publish.chunk_plan(23 * MB, 10 * MB)
    assert info["total_chunk_count"] == 2 and info["chunk_size"] == 10 * MB
    assert chunks == [(0, 10 * MB - 1), (10 * MB, 23 * MB - 1)]  # remainder merged into the last chunk
    info, _ = publish.chunk_plan(500 * MB, 200 * MB)
    assert info["chunk_size"] == 64 * MB  # clamped to the 64 MB maximum


def test_retention_buckets():
    curve = [(0, 1.0), (2, 0.8), (5, 0.6), (10, 0.5), (20, 0.4), (30, 0.3), (60, 0.1)]
    b = analytics.retention_buckets(curve)
    assert list(b) == ["0-2s", "2-5s", "5-10s", "10-20s", "20-30s", "30+s"]
    assert b["0-2s"] == pytest.approx(0.2) and b["30+s"] == pytest.approx(0.2)
    assert analytics.retention_buckets([]) == {}


def test_snapshot_validation(ctx):
    with pytest.raises(ValidationError):
        analytics.snapshot(ctx, None, source="manual", views=-1)
    with pytest.raises(ValidationError):
        analytics.snapshot(ctx, None, source="manual", completion_rate=45)
    with pytest.raises(ValidationError):
        analytics.snapshot(ctx, None, source="manual", fake_followers=10)
    sid = analytics.snapshot(ctx, None, source="manual", views=200, likes=10, comments=2, shares=3, saves=5)
    assert ctx.db.get("analytics", sid)["engagement_rate"] == 0.1


def test_compare_flags_small_samples(ctx):
    out = analytics.compare(ctx, "format_id")
    assert out["groups"] == {} and "Descriptive" in out["caveat"]


def test_experiment_validation(ctx):
    with pytest.raises(ValidationError):
        experiments.create(ctx, name="x", variable="FAKE_VIEWS", variants=["a", "b"])
    with pytest.raises(ValidationError):
        experiments.create(ctx, name="x", variable="HOOK_TYPE", variants=["a", "a"])
    eid = experiments.create(ctx, name="hooks", variable="hook_type", variants=["QUESTION", "VISUAL_HOOK"])
    res = experiments.analyze(ctx, eid)
    assert res["status"] == "INSUFFICIENT_DATA" and res["rows"] == []
