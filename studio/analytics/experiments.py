"""Experiment engine: learn from naturally different videos, never from duplicate uploads.

An experiment varies one production variable across *different* videos
(balanced assignment). Analysis is descriptive: it refuses to compare until
every variant has at least `min_sample_size` videos with analytics, reports
bootstrap intervals, and always states that topic, timing and other factors
differ between videos.
"""
from __future__ import annotations

import json

import numpy as np

from ..errors import ValidationError
from ..textutil import new_id, now_iso
from .collector import latest_by_video

VARIABLES = ("HOOK", "VIDEO_LENGTH", "TITLE", "TOPIC", "NARRATION_STYLE", "CAPTION_STYLE", "EDITING_STYLE",
             "POSTING_TIME")
METRICS = ("views", "avg_view_percentage", "avg_view_duration", "likes", "shares", "subscribers_gained")


def create(ctx, *, name: str, variable: str, variants: list[str], hypothesis: str | None = None,
           metric: str = "views", min_sample_size: int | None = None) -> str:
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


def next_variant(ctx, experiment_id: str) -> str:
    exp = ctx.db.require("experiments", experiment_id)
    counts = {v: 0 for v in exp["variants_json"]}
    for a in ctx.db.select("experiment_assignments", {"experiment_id": experiment_id}):
        counts[a["variant"]] = counts.get(a["variant"], 0) + 1
    return min(counts.items(), key=lambda kv: (kv[1], exp["variants_json"].index(kv[0])))[0]


def assign(ctx, experiment_id: str, video_id: str, variant: str) -> None:
    exp = ctx.db.require("experiments", experiment_id)
    if exp["status"] != "RUNNING":
        raise ValidationError("experiment is not running")
    if variant not in exp["variants_json"]:
        raise ValidationError(f"unknown variant {variant!r}")
    ctx.db.insert("experiment_assignments", {"experiment_id": experiment_id, "video_id": video_id, "variant": variant},
                  or_replace=True)
    v = ctx.db.require("videos", video_id)
    ev = dict(v.get("experiment_vars_json") or {})
    ev[exp["variable"]] = variant
    ctx.db.update("videos", video_id, {"experiment_vars_json": ev})


def _bootstrap_diff(a: np.ndarray, b: np.ndarray, n: int = 4000, seed: int = 7) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    diffs = rng.choice(a, (n, len(a))).mean(axis=1) - rng.choice(b, (n, len(b))).mean(axis=1)
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def analyze(ctx, experiment_id: str) -> dict:
    exp = ctx.db.require("experiments", experiment_id)
    metric = exp["metric"]
    latest = latest_by_video(ctx)
    groups: dict[str, list[float]] = {v: [] for v in exp["variants_json"]}
    dates = []
    for a in ctx.db.select("experiment_assignments", {"experiment_id": experiment_id}):
        snap = latest.get(a["video_id"])
        if snap and snap.get(metric) is not None:
            groups[a["variant"]].append(float(snap[metric]))
            dates.append(snap["captured_at"][:10])
    sizes = {k: len(v) for k, v in groups.items()}
    result = {"metric": metric, "sample_sizes": sizes, "min_sample_size": exp["min_sample_size"],
              "caveat": "Descriptive comparison of different videos; topic, posting time and other factors vary, "
                        "so differences are not proof of cause."}
    if min(sizes.values()) < exp["min_sample_size"]:
        result["status"] = "INSUFFICIENT_DATA"
        result["message"] = (f"Need at least {exp['min_sample_size']} videos with analytics per variant; have {sizes}. "
                             "No conclusion is drawn.")
    else:
        stats = {k: {"n": len(v), "mean": round(float(np.mean(v)), 3), "median": round(float(np.median(v)), 3)}
                 for k, v in groups.items()}
        best = max(stats, key=lambda k: stats[k]["mean"])
        comps = {}
        for k, v in groups.items():
            if k != best:
                lo, hi = _bootstrap_diff(np.array(groups[best]), np.array(v))
                comps[f"{best} - {k}"] = {"ci95": [round(lo, 3), round(hi, 3)],
                                          "clear_difference": bool(lo > 0)}
        result.update({"status": "ANALYZED", "stats": stats, "leader": best, "comparisons": comps})
    date_range = f"{min(dates)}..{max(dates)}" if dates else None
    ctx.db.update("experiments", experiment_id, {"result_json": result, "sample_size": sum(sizes.values()),
                                                 "date_range": date_range})
    return result


def conclude(ctx, experiment_id: str) -> dict:
    result = analyze(ctx, experiment_id)
    if result["status"] != "ANALYZED":
        raise ValidationError(result["message"])
    ctx.db.update("experiments", experiment_id, {"status": "CONCLUDED", "concluded_at": now_iso()})
    return result


def describe(ctx) -> list[dict]:
    return [{**e, "result": json.dumps(e.get("result_json"))[:200] if e.get("result_json") else None}
            for e in ctx.db.select("experiments", order_by="created_at")]
