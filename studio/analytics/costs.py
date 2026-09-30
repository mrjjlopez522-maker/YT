"""Cost ledger and budget enforcement.

Prices come from config/pricing.yaml (your inputs, not looked up). Every
recorded cost is an ESTIMATE computed from units x unit price. Before any paid
call the pipeline projects the worst-case cost and refuses to exceed
costs.max_api_cost_per_video.
"""
from __future__ import annotations

import yaml

from ..errors import BudgetExceededError
from ..textutil import new_id, now_iso

CATEGORIES = ("research", "llm", "tts", "storage", "rendering", "sources", "other")


class CostTracker:
    def __init__(self, ctx):
        self.ctx = ctx
        path = ctx.cfg.config_file(ctx.cfg.get("costs.pricing_file"))
        self.pricing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.allow_unpriced = bool(self.pricing.get("allow_unpriced", False))
        self.max_per_video = float(ctx.cfg.get("costs.max_api_cost_per_video"))

    def rate(self, category: str, provider: str, key: str) -> float | None:
        entry = (self.pricing.get(category) or {}).get(provider)
        if entry is None:
            return None
        value = entry.get(key) if isinstance(entry, dict) else None
        return None if value is None else float(value)

    def require_rate(self, category: str, provider: str, key: str) -> float:
        value = self.rate(category, provider, key)
        if value is None:
            if self.allow_unpriced:
                return 0.0
            raise BudgetExceededError(
                f"No price configured for {category}.{provider}.{key}, so the budget cannot be enforced",
                hint="set it in config/pricing.yaml (or allow_unpriced: true)")
        return value

    def spent(self, *, video_id: str | None = None, topic_id: str | None = None) -> float:
        if video_id:
            return float(self.ctx.db.scalar("SELECT COALESCE(SUM(estimated_usd),0) FROM costs WHERE video_id = ?",
                                            (video_id,)))
        if topic_id:
            return float(self.ctx.db.scalar(
                "SELECT COALESCE(SUM(estimated_usd),0) FROM costs WHERE topic_id = ? AND video_id IS NULL", (topic_id,)))
        return 0.0

    def check_budget(self, projected_usd: float, *, video_id: str | None = None, topic_id: str | None = None,
                     what: str = "call") -> None:
        total = self.spent(video_id=video_id, topic_id=topic_id) + projected_usd
        if total > self.max_per_video + 1e-9:
            raise BudgetExceededError(
                f"{what} would bring this video's estimated cost to ${total:.4f}, over the "
                f"${self.max_per_video:.2f} limit", hint="raise costs.max_api_cost_per_video or use cheaper providers")

    def record(self, category: str, provider: str, *, units: float, unit_type: str, usd: float,
               video_id: str | None = None, topic_id: str | None = None) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"unknown cost category {category}")
        self.ctx.db.insert("costs", {"cost_id": new_id("cost"), "video_id": video_id, "topic_id": topic_id,
                                     "category": category, "provider": provider, "units": float(units),
                                     "unit_type": unit_type, "estimated_usd": round(float(usd), 6),
                                     "created_at": now_iso()})

    # convenience estimators --------------------------------------------------
    def llm_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.require_rate("llm", provider, "input_per_mtok")
                + output_tokens * self.require_rate("llm", provider, "output_per_mtok")) / 1_000_000

    def tts_cost(self, provider: str, chars: int) -> float:
        return chars / 1000 * self.require_rate("tts", provider, "per_1k_chars")

    def render_cost(self, minutes: float) -> float:
        return minutes * float((self.pricing.get("rendering") or {}).get("per_render_minute") or 0.0)

    def storage_cost(self, gb: float) -> float:
        return gb * float((self.pricing.get("storage") or {}).get("per_gb_month") or 0.0)


def attach_topic_costs(ctx, topic_id: str, video_id: str) -> None:
    ctx.db.conn.execute("UPDATE costs SET video_id = ? WHERE topic_id = ? AND video_id IS NULL", (video_id, topic_id))


def cost_summary(ctx) -> dict:
    rows = ctx.db.query("SELECT video_id, category, SUM(estimated_usd) AS usd FROM costs "
                        "WHERE video_id IS NOT NULL GROUP BY video_id, category")
    per_video: dict[str, float] = {}
    per_category: dict[str, float] = {c: 0.0 for c in CATEGORIES}
    for r in rows:
        per_video[r["video_id"]] = per_video.get(r["video_id"], 0.0) + r["usd"]
        per_category[r["category"]] = per_category.get(r["category"], 0.0) + r["usd"]
    n = len(per_video)
    avg = sum(per_video.values()) / n if n else None
    return {
        "label": "ESTIMATE (units x prices from config/pricing.yaml)",
        "videos_costed": n,
        "COST_PER_VIDEO": None if avg is None else round(avg, 4),
        "COST_PER_100_VIDEOS": None if avg is None else round(avg * 100, 2),
        "COST_PER_1000_VIDEOS": None if avg is None else round(avg * 1000, 2),
        "by_category_total": {k: round(v, 4) for k, v in per_category.items()},
        "by_category_per_video": {k: round(v / n, 4) for k, v in per_category.items()} if n else {},
        "per_video": {k: round(v, 4) for k, v in per_video.items()},
    }
