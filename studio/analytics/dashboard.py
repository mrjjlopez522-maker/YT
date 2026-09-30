"""Dashboard data: totals, groupings and descriptive "what is working?" notes.

"What is working" compares the top quarter of videos (by views) with the rest
on production attributes. It is shown only when there are enough videos, it
reports group sizes, and it never claims a cause.
"""
from __future__ import annotations

import datetime as dt
import statistics

from .collector import latest_by_video
from .costs import cost_summary
from .finance import model


def _group(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key) or "unknown"), []).append(r)
    out = []
    for k, items in groups.items():
        views = [i["views"] for i in items if i["views"] is not None]
        pct = [i["avg_pct_viewed"] for i in items if i["avg_pct_viewed"] is not None]
        out.append({key: k, "videos": len(items), "views": sum(views) if views else None,
                    "avg_views": round(statistics.mean(views), 1) if views else None,
                    "avg_pct_viewed": round(statistics.mean(pct), 1) if pct else None})
    return sorted(out, key=lambda r: -(r["avg_views"] or 0))


def what_is_working(rows: list[dict], min_n: int) -> list[str]:
    measured = [r for r in rows if r["views"] is not None]
    if len(measured) < max(8, 2 * min_n):
        return [f"Not enough published videos with analytics to compare (have {len(measured)}, "
                f"need {max(8, 2 * min_n)}). Keep publishing and collecting."]
    measured.sort(key=lambda r: r["views"], reverse=True)
    top = measured[: max(2, len(measured) // 4)]
    rest = measured[len(top):]
    notes = [f"Top {len(top)} videos by views vs the other {len(rest)} (descriptive, not causal):"]
    for attr in ("format", "hook_strategy", "duration_bucket", "caption_style", "topic"):
        def share(group, value):
            return sum(1 for r in group if r.get(attr) == value) / len(group)
        values = {r.get(attr) for r in measured if r.get(attr)}
        for val in values:
            t, o = share(top, val), share(rest, val)
            if t - o >= 0.25:
                notes.append(f"{attr} = {val}: {t:.0%} of top videos vs {o:.0%} of the rest")
    pct_top = [r["avg_pct_viewed"] for r in top if r["avg_pct_viewed"] is not None]
    pct_rest = [r["avg_pct_viewed"] for r in rest if r["avg_pct_viewed"] is not None]
    if pct_top and pct_rest:
        notes.append(f"Average % viewed: top {statistics.mean(pct_top):.1f}% vs rest {statistics.mean(pct_rest):.1f}%")
    if len(notes) == 1:
        notes.append("No attribute stands out between top videos and the rest.")
    return notes


def dashboard_data(ctx) -> dict:
    latest = latest_by_video(ctx)
    rows = []
    for v in ctx.db.query("SELECT v.*, t.topic, s.format, s.hooks_json FROM videos v JOIN topics t ON t.topic_id = "
                          "v.topic_id LEFT JOIN scripts s ON s.script_id = v.script_id ORDER BY v.created_at"):
        snap = latest.get(v["video_id"]) or {}
        hooks = v.get("hooks_json") or []
        dur = v.get("duration") or 0
        caption = next((a.get("meta_json", {}).get("style") for a in ctx.db.select(
            "assets", {"video_id": v["video_id"], "kind": "captions_ass"})), None)
        rows.append({"video_id": v["video_id"], "status": v["status"], "title": v.get("selected_title"),
                     "topic": v["topic"], "format": v.get("format"),
                     "hook_strategy": hooks[0]["strategy"] if hooks else None,
                     "duration_bucket": "<30s" if dur < 30 else "30-45s" if dur < 45 else "45s+",
                     "caption_style": caption, "views": snap.get("views"),
                     "avg_pct_viewed": snap.get("avg_view_percentage"),
                     "subscribers_gained": snap.get("subscribers_gained"), "created_at": v["created_at"]})
    views = [r["views"] for r in rows if r["views"] is not None]
    pct = [r["avg_pct_viewed"] for r in rows if r["avg_pct_viewed"] is not None]
    four_weeks = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=28)).isoformat()
    uploads_4w = ctx.db.scalar("SELECT COUNT(*) FROM uploads WHERE status = 'UPLOADED' AND created_at >= ?",
                               (four_weeks,)) or 0
    fin = model(ctx)
    return {
        "kpis": {"total_videos": len(rows),
                 "published": sum(1 for r in rows if r["status"] in ("PUBLISHED", "ANALYZING")),
                 "total_views": sum(views) if views else 0,
                 "average_views": round(statistics.mean(views), 1) if views else "no data",
                 "average_retention": f"{statistics.mean(pct):.1f}%" if pct else "no data",
                 "subscribers_gained": sum(r["subscribers_gained"] or 0 for r in rows),
                 "publishing_per_week": round(uploads_4w / 4, 2),
                 "revenue_actual": f"${fin['actual']['revenue_total']:.2f}" if fin["actual"]["revenue_total"]
                 else "none recorded"},
        "by_topic": _group(rows, "topic"), "by_format": _group(rows, "format"), "videos": rows,
        "what_is_working": what_is_working(rows, int(ctx.cfg.get("experiments.min_sample_size_per_variant"))),
        "costs": cost_summary(ctx), "revenue": fin["actual"],
    }
