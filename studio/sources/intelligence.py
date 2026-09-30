"""Source intelligence: what is in a legally usable source, and where.

Produces a structured analysis:
  HOOK_MOMENT, KEY_EVENT, CONTEXT, IMPORTANT_FACTS, VISUAL_MOMENTS,
  POTENTIAL_STORY, POTENTIAL_COMMENTARY, FACT_CHECK_REQUIREMENTS
plus technical signals (motion, scene changes, black segments, a watermark
heuristic, transcript availability).

The watermark check is a heuristic: it looks for small static, high-contrast
regions in the corners while the rest of the frame moves. It cannot prove the
absence of a watermark; a positive result blocks QC until a human reviews it.
"""
from __future__ import annotations

import numpy as np

from ..logging_setup import get_logger
from ..media import ffmpeg
from ..textutil import capitalized_terms, numbers_in, split_sentences

log = get_logger("sources.intelligence")


def transcribe(path: str) -> dict:
    """Speech-to-text behind an optional dependency. Returns availability explicitly."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return {"available": False, "reason": "no speech-to-text provider installed (pip install faster-whisper)"}
    model = WhisperModel("small", compute_type="int8")
    segments, _ = model.transcribe(path, word_timestamps=True)
    segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
    return {"available": True, "provider": "faster-whisper:small", "segments": segs,
            "text": " ".join(s["text"] for s in segs)}


def _motion(frames: np.ndarray) -> np.ndarray:
    if len(frames) < 2:
        return np.zeros(len(frames))
    diffs = np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16)).mean(axis=(1, 2))
    return np.concatenate([[diffs[0]], diffs])


def watermark_heuristic(frames: np.ndarray) -> dict:
    if len(frames) < 6:
        return {"status": "inconclusive", "reason": "too few frames"}
    f = frames.astype(np.float32)
    temporal_std = f.std(axis=0)
    global_motion = float(np.abs(np.diff(f, axis=0)).mean())
    if global_motion < 1.0:
        return {"status": "inconclusive", "reason": "footage is nearly static", "global_motion": round(global_motion, 3)}
    gy, gx = np.gradient(f.mean(axis=0))
    edges = np.hypot(gx, gy)
    h, w = temporal_std.shape
    rh, rw = max(2, int(h * 0.14)), max(2, int(w * 0.26))
    regions = {"top_left": (slice(0, rh), slice(0, rw)), "top_right": (slice(0, rh), slice(w - rw, w)),
               "bottom_left": (slice(h - rh, h), slice(0, rw)), "bottom_right": (slice(h - rh, h), slice(w - rw, w))}
    moving_elsewhere = float((temporal_std > 6).mean())
    flagged = []
    for name, (ys, xs) in regions.items():
        static_edges = (temporal_std[ys, xs] < 2.5) & (edges[ys, xs] > 12)
        frac = float(static_edges.mean())
        if frac > 0.04 and moving_elsewhere > 0.15:
            flagged.append({"region": name, "static_edge_fraction": round(frac, 3)})
    return {"status": "possible_watermark" if flagged else "none_detected", "regions": flagged,
            "global_motion": round(global_motion, 3)}


def _windows(motion: np.ndarray, times: list[float], fps: float, width_s: float = 2.0, top: int = 3) -> list[dict]:
    if len(motion) == 0:
        return []
    win = max(1, int(width_s * fps))
    scores = np.convolve(motion, np.ones(win) / win, mode="valid") if len(motion) >= win else np.array([motion.mean()])
    order = np.argsort(scores)[::-1]
    picked: list[dict] = []
    for i in order:
        start = times[int(i)]
        if all(abs(start - p["start"]) >= width_s for p in picked):
            picked.append({"start": round(start, 2), "end": round(start + width_s, 2), "motion": round(float(scores[i]), 3)})
        if len(picked) >= top:
            break
    return picked


def analyze(ctx, source_id: str, *, fps: float = 2.0) -> dict:
    src = ctx.db.require("sources", source_id)
    path = src.get("local_path")
    analysis: dict = {"source_id": source_id, "media_type": src["media_type"]}
    description = src.get("description") or ""

    if src["media_type"] == "video" and path:
        info = ffmpeg.probe(path)
        frames, times = ffmpeg.gray_frames(path, fps=fps, max_seconds=300)
        motion = _motion(frames)
        luma = frames.reshape(len(frames), -1).mean(axis=1) if len(frames) else np.array([])
        black = [round(t, 2) for t, m in zip(times, luma) if m < 12]
        thr = motion.mean() + 2 * motion.std() if len(motion) else 0
        cuts = [round(times[i], 2) for i in range(1, len(motion)) if motion[i] > max(thr, 8)]
        visual_moments = _windows(motion, times, fps)
        analysis.update({
            "duration": info.duration, "width": info.width, "height": info.height, "fps": info.fps,
            "has_audio": info.has_audio, "scene_changes": cuts, "black_frames_at": black[:50],
            "mean_motion": round(float(motion.mean()), 3) if len(motion) else 0.0,
            "watermark": watermark_heuristic(frames),
            "transcript": transcribe(path) if info.has_audio else {"available": False, "reason": "no audio track"},
        })
        hook = visual_moments[0] if visual_moments else {"start": 0.0, "end": min(2.0, info.duration)}
        key_event = cuts[0] if cuts else hook["start"]
    elif src["media_type"] == "image" and path:
        info = ffmpeg.probe(path)
        analysis.update({"width": info.width, "height": info.height,
                         "watermark": {"status": "inconclusive", "reason": "still image; review visually"},
                         "transcript": {"available": False, "reason": "still image"}})
        visual_moments, hook, key_event = [], {"start": 0.0, "end": 0.0}, 0.0
    else:
        visual_moments, hook, key_event = [], None, None
        analysis["transcript"] = {"available": False, "reason": "not a visual source"}

    text = " ".join(filter(None, [description, (analysis.get("transcript") or {}).get("text", "")]))
    claims = [s for s in split_sentences(text) if numbers_in(s) or capitalized_terms(s)]
    tags = src.get("tags_json") or []
    analysis["structured"] = {
        "HOOK_MOMENT": hook,
        "KEY_EVENT": {"time": key_event} if key_event is not None else None,
        "CONTEXT": description[:500] or "No description supplied by the source.",
        "IMPORTANT_FACTS": claims[:8],
        "VISUAL_MOMENTS": visual_moments,
        "POTENTIAL_STORY": f"Use as supporting visuals for: {', '.join(tags[:5])}" if tags else "Supporting visuals only.",
        "POTENTIAL_COMMENTARY": "Explain what the viewer is seeing and why it matters; do not narrate the source's own words.",
        "FACT_CHECK_REQUIREMENTS": [f"Independently verify: {c}" for c in claims[:8]]
                                   or ["Source makes no factual claims; narration facts come from research."],
        "ENTITIES": sorted(capitalized_terms(text))[:20],
    }
    ctx.db.update("sources", source_id, {"analysis_json": analysis,
                                         "source_timestamps_json": src.get("source_timestamps_json") or visual_moments})
    return analysis
