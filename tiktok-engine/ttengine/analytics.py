"""TikTok analytics: timestamped snapshots, retention buckets, descriptive comparisons.

Sources (all permitted):
  * Display API video.query — view/like/comment/share counts for your own videos
  * TikTok Studio exports / manual entry — watch time, completion, saves, retention
    curve, new followers, traffic sources (not available from the Display API)
Correlation is not causation: comparisons are descriptive and need a minimum
sample size per group.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path

from studio.analytics.collector import latest_by_video
from studio.errors import ValidationError
from studio.textutil import new_id, now_iso

BUCKETS = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 30), (30, None)]
FIELDS = {"views", "likes", "comments", "shares", "saves", "followers_gained", "avg_watch_time", "completion_rate",
          "estimated_revenue", "period_start", "period_end"}
__all__ = ["latest_by_video", "snapshot", "retention_buckets", "compare", "import_studio_csv", "fetch_display_api"]


def retention_buckets(curve: list[tuple[float, float]]) -> dict:
    """curve: [(seconds, share of viewers still watching 0..1)] -> share lost in each bucket."""
    if not curve:
        return {}
    pts = sorted(curve)

    def at(t: float) -> float:
        prev = pts[0]
        for p in pts:
            if p[0] >= t:
                if p[0] == prev[0]:
                    return p[1]
                return prev[1] + (p[1] - prev[1]) * (t - prev[0]) / (p[0] - prev[0])
            prev = p
        return pts[-1][1]
    out = {}
    end = pts[-1][0]
    for a, b in BUCKETS:
        if a > end:
            break
        hi = min(b if b is not None else end, end)
        out[f"{a}-{b if b is not None else ''}s".replace("-s", "+s")] = round(at(a) - at(hi), 4)
    return out


def snapshot(ctx, video_id: str | None, *, source: str, retention_curve: list | None = None,
             traffic_sources: dict | None = None, platform_video_id: str | None = None, **metrics) -> str:
    unknown = set(metrics) - FIELDS
    if unknown:
        raise ValidationError(f"Unknown analytics fields: {sorted(unknown)}")
    for k, val in metrics.items():
        if k not in ("period_start", "period_end") and val is not None and float(val) < 0:
            raise ValidationError(f"{k} cannot be negative")
    if metrics.get("completion_rate") is not None and not 0 <= float(metrics["completion_rate"]) <= 1:
        raise ValidationError("completion_rate is a share between 0 and 1")
    views = metrics.get("views")
    inter = sum(metrics.get(k) or 0 for k in ("likes", "comments", "shares", "saves"))
    engagement = round(inter / views, 4) if views else None
    sid = new_id("snap")
    ctx.db.insert("analytics", {
        "snapshot_id": sid, "video_id": video_id, "youtube_video_id": platform_video_id, "captured_at": now_iso(),
        "platform": "tiktok", "source": source, "views": views, "likes": metrics.get("likes"),
        "comments": metrics.get("comments"), "shares": metrics.get("shares"), "saves": metrics.get("saves"),
        "followers_gained": metrics.get("followers_gained"), "subscribers_gained": metrics.get("followers_gained"),
        "avg_watch_time": metrics.get("avg_watch_time"), "avg_view_duration": metrics.get("avg_watch_time"),
        "completion_rate": metrics.get("completion_rate"), "engagement_rate": engagement,
        "estimated_revenue": metrics.get("estimated_revenue"), "period_start": metrics.get("period_start"),
        "period_end": metrics.get("period_end"), "retention_json": retention_curve,
        "retention_buckets_json": retention_buckets(retention_curve or []), "traffic_sources_json": traffic_sources})
    v = ctx.db.get("videos", video_id) if video_id else None
    if v and v["status"] == "PUBLISHED":
        from . import states
        states.transition(ctx, video_id, "ANALYTICS", reason="first analytics snapshot")
    return sid


def fetch_display_api(ctx, session, access_token: str) -> int:
    """Counts for our uploaded videos via the Display API (video.query)."""
    ups = ctx.db.query("SELECT video_id, youtube_video_id FROM uploads WHERE platform = 'tiktok' AND "
                       "youtube_video_id IS NOT NULL")
    if not ups:
        return 0
    ids = {u["youtube_video_id"]: u["video_id"] for u in ups}
    resp = session.post("https://open.tiktokapis.com/v2/video/query/?fields=id,view_count,like_count,comment_count,"
                        "share_count,duration", json={"filters": {"video_ids": list(ids)[:20]}},
                        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, timeout=30)
    data = resp.json().get("data", {})
    n = 0
    for item in data.get("videos", []):
        snapshot(ctx, ids.get(item["id"]), source="display_api", platform_video_id=item["id"],
                 views=item.get("view_count"), likes=item.get("like_count"), comments=item.get("comment_count"),
                 shares=item.get("share_count"))
        n += 1
    return n


def _num(x):
    if x is None or str(x).strip() in ("", "-", "—"):
        return None
    s = str(x).replace(",", "").replace("%", "").strip()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    try:
        return float(s)
    except ValueError:
        return None


def import_studio_csv(ctx, path: str | Path) -> int:
    """Tolerant import of a TikTok Studio / analytics export (one row per video)."""
    path = Path(path)
    if not path.is_file():
        raise ValidationError(f"CSV not found: {path}")
    by_caption = {(v.get("selected_title") or "").strip().lower(): v["video_id"] for v in ctx.db.select("videos")}
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            low = {k.strip().lower(): v for k, v in row.items() if k}

            def col(*names):
                return next((_num(low[n]) for n in names if n in low), None)
            cap = (low.get("video title") or low.get("caption") or low.get("title") or "").strip().lower()
            vid = low.get("studio video id") or by_caption.get(cap)
            comp = col("watched full video (%)", "completion rate (%)", "completion rate")
            snapshot(ctx, vid, source="csv", views=col("video views", "views"), likes=col("likes"),
                     comments=col("comments"), shares=col("shares"), saves=col("saves", "favorites"),
                     followers_gained=col("new followers", "followers gained"),
                     avg_watch_time=col("average watch time", "avg. watch time (s)", "average watch time (s)"),
                     completion_rate=(comp / 100 if comp is not None and comp > 1 else comp))
            n += 1
    return n


def compare(ctx, attribute: str, *, min_n: int | None = None) -> dict:
    """Retention and completion by an attribute (hook_type, format_id, length bucket, series_id, voice_id...)."""
    min_n = min_n or int(ctx.cfg.get("experiments.min_sample_size_per_variant"))
    latest = latest_by_video(ctx)
    groups: dict[str, list[dict]] = {}
    for v in ctx.db.select("videos"):
        snap = latest.get(v["video_id"])
        if not snap:
            continue
        if attribute == "hook_type":
            s = ctx.db.get("scripts", v["script_id"]) if v.get("script_id") else {}
            key = (s.get("blueprint_json") or {}).get("hook_type")
        elif attribute == "length":
            d = v.get("duration") or 0
            key = "<30s" if d < 30 else "30-60s" if d < 60 else "60-90s" if d < 90 else "90s+"
        else:
            key = v.get(attribute)
        groups.setdefault(str(key), []).append(snap)
    out = {"attribute": attribute, "min_n": min_n,
           "caveat": "Descriptive only: videos also differ in topic, timing and more.", "groups": {}}
    for key, snaps in groups.items():
        comp = [s["completion_rate"] for s in snaps if s.get("completion_rate") is not None]
        buckets: dict[str, list[float]] = {}
        for s in snaps:
            for b, val in (s.get("retention_buckets_json") or {}).items():
                buckets.setdefault(b, []).append(val)
        out["groups"][key] = {
            "n": len(snaps), "enough_data": len(snaps) >= min_n,
            "median_completion": statistics.median(comp) if comp else None,
            "median_drop_by_bucket": {b: round(statistics.median(v), 4) for b, v in buckets.items()},
        }
    return out
