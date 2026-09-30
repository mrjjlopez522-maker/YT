"""Analytics snapshots (timestamped; never overwritten).

Sources:
  * YouTube Analytics API v2 (reports.query) for uploaded videos
  * a YouTube Studio "Table data.csv" export (no API access needed)
  * manual entry
Only metrics YouTube actually reports are stored; nothing is estimated here.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from ..errors import ValidationError
from ..logging_setup import get_logger
from ..textutil import new_id, now_iso

log = get_logger("studio.api")
METRICS = ["views", "likes", "comments", "shares", "subscribersGained", "subscribersLost", "averageViewDuration",
           "averageViewPercentage", "estimatedMinutesWatched"]
_COLUMN_MAP = {"views": "views", "likes": "likes", "comments": "comments", "shares": "shares",
               "subscribersGained": "subscribers_gained", "subscribersLost": "subscribers_lost",
               "averageViewDuration": "avg_view_duration", "averageViewPercentage": "avg_view_percentage"}


def _rows_to_dicts(resp: dict) -> list[dict]:
    names = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(names, r)) for r in resp.get("rows", []) or []]


def analytics_service(ctx):
    from googleapiclient.discovery import build

    from ..publish.youtube import credentials
    return build("youtubeAnalytics", "v2", credentials=credentials(ctx), cache_discovery=False)


def collect_api(ctx, *, service=None, start: dt.date | None = None, end: dt.date | None = None) -> int:
    uploads = ctx.db.query("SELECT * FROM uploads WHERE status = 'UPLOADED' AND youtube_video_id IS NOT NULL")
    if not uploads:
        return 0
    service = service or analytics_service(ctx)
    end = end or dt.datetime.now(dt.timezone.utc).date()
    n = 0
    for up in uploads:
        s = start or dt.date.fromisoformat(up["created_at"][:10])
        common = {"ids": "channel==MINE", "startDate": s.isoformat(), "endDate": end.isoformat(),
                  "filters": f"video=={up['youtube_video_id']}"}
        try:
            totals = _rows_to_dicts(service.reports().query(metrics=",".join(METRICS), dimensions="video",
                                                            **common).execute())
            retention = _rows_to_dicts(service.reports().query(
                metrics="audienceWatchRatio,relativeRetentionPerformance", dimensions="elapsedVideoTimeRatio",
                **common).execute())
            traffic = _rows_to_dicts(service.reports().query(metrics="views", dimensions="insightTrafficSourceType",
                                                             **common).execute())
        except Exception as exc:  # noqa: BLE001 - recorded and surfaced per video
            log.warning("analytics for %s failed: %s", up["youtube_video_id"], exc)
            ctx.db.record_error(stage="analytics", exc=exc, video_id=up["video_id"])
            continue
        t = totals[0] if totals else {}
        snapshot(ctx, up["video_id"], youtube_video_id=up["youtube_video_id"], source="api",
                 period_start=s.isoformat(), period_end=end.isoformat(),
                 **{dst: t.get(src) for src, dst in _COLUMN_MAP.items()},
                 retention=retention, traffic_sources=traffic)
        n += 1
        video = ctx.db.get("videos", up["video_id"])
        if video and video["status"] == "PUBLISHED":
            from ..pipeline import states
            states.transition(ctx, up["video_id"], "ANALYZING", reason="first analytics snapshot")
    return n


def snapshot(ctx, video_id: str | None, *, source: str, youtube_video_id: str | None = None, retention=None,
             traffic_sources=None, **metrics) -> str:
    allowed = {"views", "engaged_views", "likes", "comments", "shares", "subscribers_gained", "subscribers_lost",
               "avg_view_duration", "avg_view_percentage", "estimated_revenue", "period_start", "period_end"}
    unknown = set(metrics) - allowed
    if unknown:
        raise ValidationError(f"Unknown analytics fields: {sorted(unknown)}")
    for k, v in metrics.items():
        if k not in ("period_start", "period_end") and v is not None and float(v) < 0:
            raise ValidationError(f"{k} cannot be negative")
    sid = new_id("snap")
    ctx.db.insert("analytics", {"snapshot_id": sid, "video_id": video_id, "youtube_video_id": youtube_video_id,
                                "captured_at": now_iso(), "retention_json": retention,
                                "traffic_sources_json": traffic_sources, "source": source, **metrics})
    return sid


def _num(value: str | None) -> float | None:
    if value is None or str(value).strip() in ("", "—", "-"):
        return None
    v = str(value).replace(",", "").replace("%", "").strip()
    if ":" in v:  # h:mm:ss or m:ss
        parts = [float(p) for p in v.split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    try:
        return float(v)
    except ValueError:
        return None


def import_studio_csv(ctx, path: str | Path) -> int:
    """Import YouTube Studio > Analytics > Advanced mode > Export > 'Table data.csv'."""
    path = Path(path)
    if not path.is_file():
        raise ValidationError(f"CSV not found: {path}")
    uploads = {u["youtube_video_id"]: u["video_id"] for u in ctx.db.query(
        "SELECT youtube_video_id, video_id FROM uploads WHERE youtube_video_id IS NOT NULL")}
    titles = {(v["selected_title"] or "").strip().lower(): v["video_id"] for v in ctx.db.select("videos")}
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            low = {k.strip().lower(): v for k, v in row.items() if k}
            yt_id = low.get("content") or low.get("video")
            if not yt_id or yt_id.lower() == "total":
                continue
            vid = uploads.get(yt_id) or titles.get((low.get("video title") or "").strip().lower())

            def col(*names):
                return next((_num(low[n]) for n in names if n in low), None)
            snapshot(ctx, vid, youtube_video_id=yt_id, source="csv",
                     views=col("views"), engaged_views=col("engaged views"), likes=col("likes"),
                     comments=col("comments added", "comments"), shares=col("shares"),
                     subscribers_gained=col("subscribers gained", "subscribers"),
                     subscribers_lost=col("subscribers lost"),
                     avg_view_duration=col("average view duration"),
                     avg_view_percentage=col("average percentage viewed (%)", "average percentage viewed"),
                     estimated_revenue=col("estimated revenue (usd)", "your estimated revenue (usd)"))
            n += 1
    return n


def latest_by_video(ctx) -> dict[str, dict]:
    """Most recent snapshot per video (insertion order breaks same-second ties)."""
    out: dict[str, dict] = {}
    for r in ctx.db.query("SELECT * FROM analytics WHERE video_id IS NOT NULL ORDER BY captured_at, rowid"):
        out[r["video_id"]] = r
    return out
