"""Costs, revenue, profit and break-even from recorded numbers only.

Revenue is whatever you record (Creator Rewards payouts, Shop affiliate
commissions, brand deals...). Nothing is projected or promised: a figure that
cannot be computed from recorded data is None, with the reason.
"""
from __future__ import annotations

import datetime as dt
import math

from studio.analytics.collector import latest_by_video
from studio.analytics.costs import cost_summary
from studio.errors import ValidationError
from studio.textutil import new_id, now_iso

CATEGORIES = ("creator_rewards", "shop_affiliate", "brand_deal", "live_gifts", "subscriptions", "other")


def add_revenue(ctx, *, amount_usd: float, category: str, period_start: str, period_end: str,
                video_id: str | None = None, notes: str | None = None) -> str:
    if category not in CATEGORIES:
        raise ValidationError(f"category must be one of {CATEGORIES}")
    if amount_usd < 0:
        raise ValidationError("amount must be >= 0")
    for d in (period_start, period_end):
        dt.date.fromisoformat(d)
    rid = new_id("rev")
    ctx.db.insert("revenue", {"revenue_id": rid, "video_id": video_id, "period_start": period_start,
                              "period_end": period_end, "category": category, "amount_usd": float(amount_usd),
                              "notes": notes, "created_at": now_iso()})
    return rid


def summary(ctx) -> dict:
    costs = cost_summary(ctx)
    rev = ctx.db.query("SELECT category, SUM(amount_usd) AS usd FROM revenue GROUP BY category")
    revenue_total = round(sum(r["usd"] for r in rev), 2)
    published = int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE status IN ('PUBLISHED', 'ANALYTICS')") or 0)
    views = sum((s.get("views") or 0) for s in latest_by_video(ctx).values())
    cpv = costs["COST_PER_VIDEO"]
    rpv = round(revenue_total / published, 4) if published and revenue_total else None
    per_1k = round(revenue_total / views * 1000, 4) if revenue_total and views else None
    if cpv is None:
        break_even = {"views_per_video": None, "basis": "no costed videos yet"}
    elif cpv == 0:
        break_even = {"views_per_video": 0, "basis": "recorded variable cost per video is $0 (local voice and "
                                                      "rendering); your time and fixed costs are not in the ledger"}
    elif per_1k:
        break_even = {"views_per_video": math.ceil(cpv / (per_1k / 1000)),
                      "basis": f"your recorded revenue per 1,000 views (${per_1k})"}
    else:
        break_even = {"views_per_video": None, "basis": "not computable until revenue and views are recorded"}
    return {
        "VERIFIED": {"label": "recorded by you or reported by TikTok",
                     "revenue_by_category": {r["category"]: round(r["usd"], 2) for r in rev},
                     "revenue_total": revenue_total, "videos_published": published, "total_views": views},
        "ESTIMATES": {"label": costs["label"], "COST_PER_VIDEO": cpv, "COST_PER_100_VIDEOS": costs["COST_PER_100_VIDEOS"],
                      "COST_PER_1000_VIDEOS": costs["COST_PER_1000_VIDEOS"],
                      "by_category_per_video": costs["by_category_per_video"]},
        "REVENUE_PER_VIDEO": rpv,
        "PROFIT_PER_VIDEO": round(rpv - cpv, 4) if rpv is not None and cpv is not None else None,
        "REVENUE_PER_1000_VIEWS": per_1k,
        "BREAK_EVEN": break_even,
        "notes": ["Creator Rewards pays only on eligible accounts and qualified views of videos of 1 minute or more "
                  "(docs/BUSINESS_RESEARCH.md); until you are eligible, treat it as $0.",
                  "No revenue is projected: every revenue figure above comes from amounts you recorded."],
    }
