"""Duplicate / repetition detection across the channel's videos.

Compares scripts, titles, topics, hooks, narration, visual sequences and the
exact source clip ranges used. A component at or above the configured
threshold is a flag. Topic overlap alone is reported, not blocking — the same
subject told from a genuinely different angle is allowed; the same subject
with a similar script is not.
"""
from __future__ import annotations

from ..textutil import content_words, jaccard, text_similarity

BLOCKING = ("script", "title", "hook", "narration", "visual_sequence", "source_clips")


def _visual_bigrams(scenes: list[dict]) -> set[tuple]:
    seq = [s.get("visual_source") or f"graphic:{s['section']}" for s in scenes]
    return {tuple(seq[i:i + 2]) for i in range(len(seq) - 1)} or {tuple(seq)}


def _clip_overlap(a: list[dict], b: list[dict]) -> float:
    """Seconds of identical source footage reused, relative to the shorter usage."""
    def ranges(scenes):
        out = {}
        for s in scenes:
            if s.get("visual_source") and s.get("source_in") is not None:
                out.setdefault(s["visual_source"], []).append((s["source_in"], s["source_out"]))
        return out
    ra, rb = ranges(a), ranges(b)
    total_a = sum(e - s for v in ra.values() for s, e in v)
    total_b = sum(e - s for v in rb.values() for s, e in v)
    if not total_a or not total_b:
        return 0.0
    shared = 0.0
    for src in ra.keys() & rb.keys():
        for s1, e1 in ra[src]:
            for s2, e2 in rb[src]:
                shared += max(0.0, min(e1, e2) - max(s1, s2))
    return round(min(1.0, shared / min(total_a, total_b)), 3)


def _profile(ctx, video: dict) -> dict:
    script = ctx.db.get("scripts", video["script_id"]) if video.get("script_id") else None
    topic = ctx.db.get("topics", video["topic_id"])
    return {"video_id": video["video_id"], "topic_id": video["topic_id"],
            "topic": topic["topic"] if topic else "", "title": video.get("selected_title") or "",
            "script": script["full_text"] if script else "", "hook": script["selected_hook"] if script else "",
            "scenes": ctx.db.select("scenes", {"video_id": video["video_id"]}, order_by="idx")}


def compare_profiles(a: dict, b: dict) -> dict:
    return {
        "script": text_similarity(a["script"], b["script"]),
        "title": text_similarity(a["title"], b["title"]) if a["title"] and b["title"] else 0.0,
        "topic": 1.0 if a["topic_id"] == b["topic_id"] else round(jaccard(set(content_words(a["topic"])),
                                                                          set(content_words(b["topic"]))), 3),
        "hook": text_similarity(a["hook"], b["hook"]) if a["hook"] and b["hook"] else 0.0,
        "narration": text_similarity(a["script"], b["script"]),
        "visual_sequence": round(jaccard(_visual_bigrams(a["scenes"]), _visual_bigrams(b["scenes"])), 3)
        if a["scenes"] and b["scenes"] else 0.0,
        "source_clips": _clip_overlap(a["scenes"], b["scenes"]),
    }


def check_video(ctx, video_id: str, *, threshold: float | None = None) -> dict:
    threshold = float(threshold if threshold is not None else ctx.cfg.get("qc.similarity_threshold"))
    video = ctx.db.require("videos", video_id)
    me = _profile(ctx, video)
    others = ctx.db.query("SELECT * FROM videos WHERE channel_id = ? AND video_id != ? AND script_id IS NOT NULL",
                          (video["channel_id"], video_id))
    flags, worst = [], {}
    for other in others:
        sims = compare_profiles(me, _profile(ctx, other))
        for k, v in sims.items():
            if v > worst.get(k, (0.0, None))[0]:
                worst[k] = (v, other["video_id"])
            if k in BLOCKING and v >= threshold:
                flags.append({"component": k, "similarity": v, "other_video": other["video_id"]})
    return {"threshold": threshold, "compared": len(others), "flags": flags,
            "max": {k: {"similarity": v, "video": vid} for k, (v, vid) in worst.items()},
            "topic_repeat": [o["video_id"] for o in others if o["topic_id"] == video["topic_id"]]}
