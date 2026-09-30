"""Profitability model built on actual data.

* Revenue comes from the `revenue` table (sponsorships, affiliate, products,
  YouTube payouts you record) and YouTube's own estimated_revenue in analytics.
* Costs come from the cost ledger.
* No RPM is ever assumed. A hypothetical scenario runs only when you supply an
  RPM yourself, and everything it outputs is labelled HYPOTHETICAL.
* Shorts ad revenue is treated as $0 in scenarios unless you assert the
  channel is eligible (YPP + the Shorts view threshold; see docs/BUSINESS_RESEARCH.md).
"""
from __future__ import annotations

import datetime as dt

from ..errors import ValidationError
from ..textutil import new_id, now_iso
from .collector import latest_by_video
from .costs import cost_summary

CATEGORIES = ("shorts_ads", "longform_ads", "sponsorship", "affiliate", "product", "fan_funding", "other")


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


def model(ctx, *, hypothetical_rpm: float | None = None, assume_shorts_eligible: bool = False,
          fixed_monthly_costs: float = 0.0, videos_per_month: int | None = None, days: int = 30) -> dict:
    since = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days)).isoformat()
    costs = cost_summary(ctx)
    actual_rev = ctx.db.query("SELECT category, SUM(amount_usd) AS usd FROM revenue GROUP BY category")
    actual_total = sum(r["usd"] for r in actual_rev)
    latest = latest_by_video(ctx)
    yt_est = sum(s.get("estimated_revenue") or 0.0 for s in latest.values())
    monthly_rev = ctx.db.scalar("SELECT COALESCE(SUM(amount_usd),0) FROM revenue WHERE period_end >= ?", (since,)) or 0.0
    monthly_cost = ctx.db.scalar("SELECT COALESCE(SUM(estimated_usd),0) FROM costs WHERE created_at >= ?", (since,)) or 0.0
    videos = int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE render_path IS NOT NULL") or 0)
    cost_per_video = costs["COST_PER_VIDEO"]
    views = [s.get("views") or 0 for s in latest.values()]

    out = {
        "actual": {
            "label": "ACTUAL (recorded revenue and YouTube-reported estimates)",
            "revenue_by_category": {r["category"]: round(r["usd"], 2) for r in actual_rev},
            "revenue_total": round(actual_total, 2),
            "youtube_estimated_revenue": round(float(yt_est), 2),
            "revenue_per_video": round(actual_total / videos, 4) if videos and actual_total else None,
            "cost_per_video_estimate": cost_per_video,
            "gross_margin": round((actual_total - (cost_per_video or 0) * videos) / actual_total, 3)
            if actual_total else None,
            f"revenue_last_{days}_days": round(float(monthly_rev), 2),
            f"costs_last_{days}_days": round(float(monthly_cost) + fixed_monthly_costs, 2),
            "videos_with_analytics": len(views), "median_views": sorted(views)[len(views) // 2] if views else None,
        },
        "costs": costs,
    }
    if hypothetical_rpm is not None:
        if hypothetical_rpm < 0:
            raise ValidationError("RPM must be >= 0")
        effective_rpm = hypothetical_rpm if assume_shorts_eligible else 0.0
        vpm = videos_per_month or max(1, int(ctx.cfg.get("production.max_daily_videos")) * 30)
        med = out["actual"]["median_views"] or 0
        rev_per_video = med / 1000 * effective_rpm
        var_cost = cost_per_video or 0.0
        month_rev = rev_per_video * vpm
        month_cost = var_cost * vpm + fixed_monthly_costs
        out["hypothetical"] = {
            "label": "HYPOTHETICAL — based on an RPM you supplied, not on data",
            "rpm_input": hypothetical_rpm, "shorts_ads_eligible_assumed": assume_shorts_eligible,
            "note": None if assume_shorts_eligible else
            "Shorts ad revenue set to $0: eligibility (YPP and, from 2027-02-01, 10M qualified Shorts views per "
            "90 days) was not asserted. Use --assume-eligible only if the channel qualifies.",
            "views_per_video_used": med, "videos_per_month": vpm,
            "revenue_per_video": round(rev_per_video, 4), "monthly_revenue": round(month_rev, 2),
            "monthly_costs": round(month_cost, 2), "monthly_profit": round(month_rev - month_cost, 2),
            "break_even_views_per_video": round(var_cost / (effective_rpm / 1000), 0) if effective_rpm and var_cost
            else None,
        }
    return out
