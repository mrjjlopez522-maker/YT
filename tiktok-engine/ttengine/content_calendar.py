"""Content calendar: the state board plus upcoming publishing slots from config.

Slots are suggestions for a human scheduler; a slot is only filled by a video a
person approved (quality over the slot: skip_when_quality_fails).
"""
from __future__ import annotations

import datetime as dt

from studio.analytics.costs import cost_summary
from studio.textutil import today
from . import states


def board(ctx) -> dict[str, list[dict]]:
    out = {}
    for status in states.ALL:
        rows = ctx.db.select("videos", {"status": status}, order_by="created_at")
        if rows:
            out[status] = [{"video_id": v["video_id"], "caption": v.get("selected_title"), "format": v.get("format_id"),
                            "series": v.get("series_id"), "duration": v.get("duration")} for v in rows]
    return out


def slots(ctx, days: int = 14, start: dt.date | None = None) -> list[dict]:
    cal = ctx.cfg.get("calendar")
    per_week = int(cal.get("days_per_week", 5))
    windows = cal.get("publishing_windows") or []
    per_day = int(cal.get("videos_per_day", 1))
    start = start or today()
    taken = {r["scheduled_for"][:10] for r in ctx.db.query(
        "SELECT a.scheduled_for FROM approvals a JOIN videos v ON v.video_id = a.video_id "
        "WHERE v.status = 'SCHEDULED' AND a.decision = 'SCHEDULE' AND a.scheduled_for IS NOT NULL")}
    out = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        if d.weekday() >= per_week:  # Monday-first: 5 days/week -> Mon..Fri
            continue
        for n in range(per_day):
            out.append({"date": d.isoformat(), "window": windows[n % len(windows)] if windows else None,
                        "timezone": cal.get("timezone", "UTC"), "has_scheduled_video": d.isoformat() in taken})
    return out


def overview(ctx) -> dict:
    cal = ctx.cfg.get("calendar")
    made_today = int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE substr(created_at,1,10) = ?",
                                   (today().isoformat(),)) or 0)
    return {"board": board(ctx), "videos_per_day": cal.get("videos_per_day"), "created_today": made_today,
            "days_per_week": cal.get("days_per_week"), "publishing_windows": cal.get("publishing_windows"),
            "max_cost_per_video": ctx.cfg.get("costs.max_api_cost_per_video"),
            "cost_per_video_so_far": cost_summary(ctx)["COST_PER_VIDEO"], "next_slots": slots(ctx, 7)}
