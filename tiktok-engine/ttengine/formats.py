"""Trend format analysis: WHY a format works, stored as reusable templates.

Three evidence streams, never scraping:
  1. templates (config/formats.yaml) — editorial hypotheses (ASSUMPTION)
  2. observations you record about trending videos (hook style, length, cuts, …)
  3. fingerprints + analytics of our own videos (measured)
"""
from __future__ import annotations

import json
import statistics
from collections import Counter

from studio.errors import ValidationError
from studio.textutil import new_id, now_iso, word_count

OBS_FIELDS = ("hook_style", "video_length", "cut_frequency", "text_density", "narration_style", "visual_style",
              "story_structure", "comment_prompt", "payoff_type", "cta_style", "notes")


def get(ctx, format_id: str) -> dict:
    f = ctx.formats.get(format_id)
    if not f:
        raise ValidationError(f"Unknown format {format_id!r}; choose from {sorted(ctx.formats)}")
    return f


def slots(fmt: dict, duration: float) -> list[dict]:
    """Absolute slot times for a given length."""
    return [{**s, "start_s": round(s["start"] * duration, 2), "end_s": round(s["end"] * duration, 2)}
            for s in fmt["story_structure"]]


def section_windows(fmt: dict, duration: float) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for s in slots(fmt, duration):
        a, b = out.get(s["section"], (s["start_s"], s["end_s"]))
        out[s["section"]] = (min(a, s["start_s"]), max(b, s["end_s"]))
    return out


def record_observation(ctx, *, trend_id: str | None = None, format_id: str | None = None, observer: str = "you",
                       **fields) -> str:
    unknown = set(fields) - set(OBS_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown observation fields: {sorted(unknown)}")
    oid = new_id("obs")
    ctx.db.insert("format_observations", {"obs_id": oid, "trend_id": trend_id, "format_id": format_id,
                                          "observed_at": now_iso(), "observer": observer,
                                          **{k: (str(v) if k == "story_structure" and v is not None else v)
                                             for k, v in fields.items()}})
    return oid


def analyze_observations(ctx) -> dict:
    """Describe the patterns in recorded observations (descriptive; small samples flagged)."""
    rows = ctx.db.select("format_observations")
    if not rows:
        return {"n": 0, "message": "No observations recorded yet (config/trend_observations.yaml)."}
    lengths = [r["video_length"] for r in rows if r["video_length"]]
    cuts = [r["cut_frequency"] for r in rows if r["cut_frequency"]]
    out = {"n": len(rows), "caveat": "Descriptive summary of what you recorded; small samples are not representative.",
           "hook_styles": Counter(r["hook_style"] for r in rows if r["hook_style"]).most_common(),
           "payoff_types": Counter(r["payoff_type"] for r in rows if r["payoff_type"]).most_common(),
           "cta_styles": Counter(r["cta_style"] for r in rows if r["cta_style"]).most_common(),
           "median_length": statistics.median(lengths) if lengths else None,
           "median_cut_frequency": statistics.median(cuts) if cuts else None,
           "opportunities": []}
    no_payoff = sum(1 for r in rows if (r["payoff_type"] or "").lower() in ("none", ""))
    if no_payoff:
        out["opportunities"].append(f"{no_payoff}/{len(rows)} observed videos had no real payoff — an explained, "
                                    "sourced version would add value rather than copy the format.")
    bait = sum(1 for r in rows if "follow for part" in (r["cta_style"] or "").lower())
    if bait:
        out["opportunities"].append(f"{bait}/{len(rows)} used 'follow for part 2' — we deliver the full payoff instead.")
    return out


def fingerprint(scenes: list[dict], words: list, duration: float, hook_type: str, fmt: dict) -> dict:
    """Measure our own video's format so analytics can compare formats with data."""
    changes = max(0, len(scenes) - 1) + sum(len([g for g in (s.get("graphics") or s.get("graphics_json") or [])
                                                  if g.get("type") not in ("attribution",)]) for s in scenes)
    on_screen_words = sum(word_count(" ".join(g.get("lines", []) + [g.get("text", "")]))
                          for s in scenes for g in (s.get("graphics") or s.get("graphics_json") or []))
    spoken = len(words)
    return {"format_id": fmt["format_id"], "content_format": fmt["content_format"], "hook_type": hook_type,
            "length_s": round(duration, 2), "cuts_per_10s": round(10 * max(0, len(scenes) - 1) / duration, 2),
            "visual_changes_per_10s": round(10 * changes / duration, 2),
            "narration_wpm": round(spoken / duration * 60, 1),
            "on_screen_text_words_per_10s": round(10 * on_screen_words / duration, 2),
            "text_density": "high" if on_screen_words / duration > 1.5 else "medium" if on_screen_words / duration > 0.5
            else "low"}


def update_stats(ctx, min_n: int | None = None) -> dict:
    """Per-template performance from our own analytics; relabel evidence once enough videos exist."""
    from .analytics import latest_by_video
    min_n = min_n or int(ctx.cfg.get("experiments.min_sample_size_per_variant"))
    latest = latest_by_video(ctx)
    out = {}
    for f in ctx.db.select("formats"):
        vids = [v["video_id"] for v in ctx.db.select("videos", {"format_id": f["format_id"]})]
        snaps = [latest[v] for v in vids if v in latest]
        comp = [s["completion_rate"] for s in snaps if s.get("completion_rate") is not None]
        views = [s["views"] for s in snaps if s.get("views") is not None]
        stats = {"n": len(snaps), "median_views": statistics.median(views) if views else None,
                 "median_completion": statistics.median(comp) if comp else None}
        label = f"DATA (n={len(snaps)})" if len(snaps) >= min_n else "ASSUMPTION"
        ctx.db.update("formats", f["format_id"], {"stats_json": stats, "evidence_label": label, "updated_at": now_iso()})
        out[f["format_id"]] = {**stats, "evidence_label": label}
    return out


def describe(ctx) -> str:
    lines = []
    for f in ctx.db.select("formats", order_by="format_id"):
        lines.append(f"{f['format_id']} [{f['evidence_label']}] {f['content_format']}, ~{f['target_length']}s, "
                     f"hook {f['hook_style']}, {f['cut_frequency']} changes/10s")
        lines.append(f"    why: {f['why_it_works']}")
        lines.append("    " + " | ".join(f"{s['slot']} {s['start']:.2f}-{s['end']:.2f}" for s in f["story_structure_json"]))
        if f.get("stats_json"):
            lines.append(f"    data: {json.dumps(f['stats_json'])}")
    return "\n".join(lines)
