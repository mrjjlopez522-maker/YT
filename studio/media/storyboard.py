"""Visual storyboard: timed scenes before anything is rendered.

Each scene: scene_id, start_time, end_time, visual_source, visual_type,
narration, caption, transition, sound_effect, graphics (+ source_in/out, effect).

Rules:
  * scenes follow narration sentences; long ones are split so no single source
    shot exceeds max_continuous_source_seconds
  * footage is matched to what the narration says (tags/title/entities)
  * at least (1 - max_source_screen_ratio) of the runtime is original graphics
  * the hook gets the strongest matching moment and an on-screen title card
"""
from __future__ import annotations

import math
import re

from ..textutil import content_words, new_id, numbers_in

EFFECT_CYCLE = ("slow_zoom_in", "pan", "slow_zoom_out")


def _source_terms(src: dict) -> set[str]:
    text = " ".join([src.get("title") or "", src.get("description") or "", " ".join(src.get("tags_json") or [])])
    return set(content_words(text))


def _phrases(src: dict) -> list[str]:
    return [t for t in (src.get("tags_json") or []) if len(t.split()) >= 1]


def match_score(narration: str, fact_tags: set[str], src: dict) -> float:
    words = set(content_words(narration)) | {w for t in fact_tags for w in content_words(t)}
    terms = _source_terms(src)
    score = 2.0 * len(words & terms)
    for phrase in _phrases(src):
        if len(phrase.split()) > 1 and phrase.lower() in narration.lower():
            score += 3.0
    return score


def _years(text: str) -> list[str]:
    return sorted({n for n in numbers_in(text) if len(n) == 4 and n.startswith(("1", "2"))})


def build_storyboard(*, sentences: list[dict], total_duration: float, sources: list[dict], licenses: dict,
                     facts_by_id: dict, sentence_facts: list[list[str]], hook_title: str, topic: str,
                     cfg) -> list[dict]:
    max_shot = float(cfg.get("source_policy.max_continuous_source_seconds"))
    max_ratio = float(cfg.get("source_policy.max_source_screen_ratio"))
    max_hook = float(cfg.get("qc.max_hook_seconds"))
    visuals = [s for s in sources if s.get("media_type") in ("video", "image") and s.get("local_path")]

    # 1) shots from sentence boundaries, split to respect the continuous-shot limit
    shots = []
    for i, s in enumerate(sentences):
        start = 0.0 if i == 0 else s["start"]
        end = sentences[i + 1]["start"] if i + 1 < len(sentences) else total_duration
        n = max(1, math.ceil((end - start) / max_shot - 1e-9))
        step = (end - start) / n
        for k in range(n):
            shots.append({"section": s["section"], "start": round(start + k * step, 3),
                          "end": round(start + (k + 1) * step, 3), "narration": s["text"], "sentence_index": i,
                          "part": k})
    all_years = sorted({y for s in sentences for y in _years(s["text"])})

    # 2) visual matching
    for shot in shots:
        tags = {t for fid in sentence_facts[shot["sentence_index"]] for t in (facts_by_id.get(fid, {}).get("tags") or [])}
        shot["fact_tags"] = tags
        shot["candidates"] = sorted(((match_score(shot["narration"], tags, v), v["source_id"]) for v in visuals),
                                    reverse=True)

    # 3) original-graphics quota
    need = (1.0 - max_ratio) * total_duration if visuals else total_duration
    graphic_time = 0.0
    order = sorted((s for s in shots if s["section"] not in ("HOOK",)),
                   key=lambda s: ((s["candidates"][0][0] if s["candidates"] else 0)
                                  - (2 if s["fact_tags"] & {"rule", "mechanism", "definition"} else 0),
                                  s["section"] == "PAYOFF"))
    for shot in shots:
        shot["graphic"] = not visuals
    for shot in order:
        if graphic_time >= need:
            break
        if not shot["graphic"]:
            shot["graphic"] = True
            graphic_time += shot["end"] - shot["start"]

    # 4) choose source + in/out for footage shots
    uses: dict[str, int] = {}
    cursor: dict[str, float] = {}
    prev_src = None
    by_id = {v["source_id"]: v for v in visuals}
    scenes = []
    effect_i = 0
    for idx, shot in enumerate(shots):
        dur = shot["end"] - shot["start"]
        graphics: list[dict] = []
        scene = {"scene_id": new_id("scn"), "idx": idx, "section": shot["section"], "start_time": shot["start"],
                 "end_time": shot["end"], "narration": shot["narration"] if shot["part"] == 0 else "",
                 "caption": shot["narration"] if shot["part"] == 0 else "(continued)", "transition": "cut",
                 "sound_effect": None, "visual_source": None, "source_in": None, "source_out": None}
        if shot["graphic"]:
            scene["visual_type"] = "graphic"
            scene["effect"] = "slow_zoom_in"
            key = [w for w in shot["narration"].split()][:9]
            graphics.append({"type": "background_card", "heading": topic,
                             "lines": [" ".join(key) + ("…" if len(shot["narration"].split()) > 9 else "")]})
        else:
            best = max(shot["candidates"], key=lambda c: c[0] - 0.8 * uses.get(c[1], 0) - (1.5 if c[1] == prev_src else 0))
            src = by_id[best[1]]
            uses[src["source_id"]] = uses.get(src["source_id"], 0) + 1
            prev_src = src["source_id"]
            scene["visual_source"] = src["source_id"]
            scene["visual_type"] = "footage" if src["media_type"] == "video" else "still"
            src_dur = float(src.get("duration") or 0)
            moments = ((src.get("analysis_json") or {}).get("structured") or {}).get("VISUAL_MOMENTS") or []
            if scene["visual_type"] == "footage" and src_dur:
                if shot["section"] == "HOOK" and moments:
                    s_in = moments[0]["start"]
                else:
                    s_in = cursor.get(src["source_id"], 0.0)
                s_in = max(0.0, min(s_in, max(0.0, src_dur - dur)))
                cursor[src["source_id"]] = (s_in + dur) % max(src_dur, 0.001)
                scene["source_in"], scene["source_out"] = round(s_in, 3), round(s_in + dur, 3)
            if shot["section"] == "HOOK":
                scene["effect"] = "punch_in"
            elif shot["section"] == "PAYOFF" and shot["part"] == 0:
                scene["effect"] = "punch_in"
            else:
                scene["effect"] = EFFECT_CYCLE[effect_i % len(EFFECT_CYCLE)]
                effect_i += 1
            w, h = src.get("width") or 0, src.get("height") or 0
            scene["framing"] = "blur_fill" if w and h and w / h > 0.7 else "crop"
            lic = licenses.get(src["source_id"]) or {}
            if lic.get("attribution_required"):
                graphics.append({"type": "attribution", "text": lic.get("attribution_text")
                                 or f"{src.get('title')} — {src.get('creator')} ({lic.get('license_type')})"})
            if shot["section"] == "PAYOFF" and shot["part"] == 0:
                label = next((p for p in _phrases(src) if len(p.split()) > 1 and p.lower() in shot["narration"].lower()),
                             None)
                if label:
                    graphics.append({"type": "highlight_box", "box": [180, 620, 900, 1180], "label": label.title(),
                                     "start": 0.4})
        if idx == 0:
            graphics.append({"type": "title_card", "text": hook_title, "end": min(dur, max_hook)})
        yrs = _years(shot["narration"])
        if len(all_years) >= 2 and yrs and shot["part"] == 0 and not shot["graphic"]:
            graphics.append({"type": "timeline", "years": all_years, "active": all_years.index(yrs[0]),
                             "label": "Timeline"})
        scene["graphics"] = graphics
        scenes.append(scene)

    # sound effects mark section changes only (when enabled)
    if cfg.get("sfx.enabled"):
        for i, sc in enumerate(scenes):
            if i and sc["section"] != scenes[i - 1]["section"]:
                sc["sound_effect"] = "transition"
    return scenes


def screen_time(scenes: list[dict]) -> dict:
    total = sum(s["end_time"] - s["start_time"] for s in scenes) or 1.0
    footage = sum(s["end_time"] - s["start_time"] for s in scenes if s["visual_type"] in ("footage", "still"))
    longest = max((s["end_time"] - s["start_time"] for s in scenes if s["visual_type"] == "footage"), default=0.0)
    return {"source_ratio": round(footage / total, 3), "graphic_ratio": round(1 - footage / total, 3),
            "longest_source_shot": round(longest, 3), "scenes": len(scenes)}


def short_title(text: str, max_words: int = 7) -> str:
    words = text.split()
    out = " ".join(words[:max_words])
    return re.sub(r"[,;:]$", "", out) + ("…" if len(words) > max_words else "")


def store_scenes(ctx, video_id: str, scenes: list[dict]) -> None:
    ctx.db.delete("scenes", {"video_id": video_id})
    for s in scenes:
        ctx.db.insert("scenes", {
            "scene_id": s["scene_id"], "video_id": video_id, "idx": s["idx"], "section": s["section"],
            "start_time": s["start_time"], "end_time": s["end_time"], "visual_source": s["visual_source"],
            "source_in": s["source_in"], "source_out": s["source_out"], "visual_type": s["visual_type"],
            "effect": s.get("effect"), "narration": s["narration"], "caption": s["caption"],
            "transition": s["transition"], "sound_effect": s["sound_effect"], "graphics_json": s["graphics"],
        })
