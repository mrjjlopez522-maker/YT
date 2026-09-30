"""A/B learning across *different* videos. Never duplicate uploads, never fake traffic.

One production variable varies across naturally different videos (balanced
assignment). Analysis refuses to compare until every variant has the minimum
sample size, and always says that topic, timing and other factors differ.
Record per content: experiment_id, variable, variant, content_id, result,
sample_size, date.
"""
from __future__ import annotations

from studio.analytics import experiments as core
from studio.analytics.collector import latest_by_video
from studio.errors import ValidationError
from studio.textutil import new_id, now_iso, today

VARIABLES = ("HOOK", "HOOK_TYPE", "VIDEO_LENGTH", "CAPTION", "TOPIC", "FORMAT", "VOICE", "CAPTION_STYLE",
             "EDITING_STYLE", "MUSIC", "POSTING_TIME")
METRICS = ("completion_rate", "avg_watch_time", "views", "saves", "shares", "comments", "likes", "followers_gained",
           "engagement_rate")
next_variant = core.next_variant
describe = core.describe


def create(ctx, *, name: str, variable: str, variants: list[str], hypothesis: str | None = None,
           metric: str = "completion_rate", min_sample_size: int | None = None) -> str:
    variable = variable.upper()
    if variable not in VARIABLES:
        raise ValidationError(f"variable must be one of {VARIABLES}")
    if len(set(variants)) < 2:
        raise ValidationError("an experiment needs at least two distinct variants")
    if metric not in METRICS:
        raise ValidationError(f"metric must be one of {METRICS}")
    eid = new_id("exp")
    ctx.db.insert("experiments", {"experiment_id": eid, "name": name, "variable": variable,
                                  "variants_json": list(dict.fromkeys(variants)), "hypothesis": hypothesis,
                                  "metric": metric, "status": "RUNNING", "created_at": now_iso(),
                                  "min_sample_size": int(min_sample_size or ctx.cfg.get(
                                      "experiments.min_sample_size_per_variant"))})
    return eid


def assign(ctx, experiment_id: str, video_id: str, variant: str) -> None:
    core.assign(ctx, experiment_id, video_id, variant)
    ctx.db.conn.execute("UPDATE experiment_assignments SET date = ? WHERE experiment_id = ? AND video_id = ?",
                        (today().isoformat(), experiment_id, video_id))


def analyze(ctx, experiment_id: str) -> dict:
    result = core.analyze(ctx, experiment_id)
    exp = ctx.db.require("experiments", experiment_id)
    latest = latest_by_video(ctx)
    rows = []
    for a in ctx.db.select("experiment_assignments", {"experiment_id": experiment_id}):
        snap = latest.get(a["video_id"]) or {}
        value = snap.get(exp["metric"])
        ctx.db.conn.execute("UPDATE experiment_assignments SET result = ? WHERE experiment_id = ? AND video_id = ?",
                            (value, experiment_id, a["video_id"]))
        rows.append({"experiment_id": experiment_id, "variable": exp["variable"], "variant": a["variant"],
                     "content_id": a["video_id"], "result": value, "sample_size": result["sample_sizes"][a["variant"]],
                     "date": a.get("date")})
    return {**result, "rows": rows}
