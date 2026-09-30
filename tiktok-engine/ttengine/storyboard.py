"""TikTok storyboard: narration sentences → visual beats, before anything is rendered.

Scene fields: scene_id, start, end, visual (source), narration, caption,
transition, effect, sound_effect, graphics.

Visual choice per sentence, in order of preference:
  1. the visual requirement recorded in research (a generator + params)
  2. licensed/third-party footage matched by keywords (subject to screen-time limits)
  3. an original kinetic-text card
The hook uses the strongest "hook"-tagged visual. Consecutive beats never reuse
the identical clip; long beats are split into two shots for pacing.
"""
from __future__ import annotations

import math

from studio.media.storyboard import match_score, short_title
from studio.textutil import content_words, new_id, numbers_in, split_sentences
from . import brand as brand_mod
from . import visuals

FALLBACK_GENERATOR = "kinetic_text"


def _visual_spec(sentence_facts: list[str], facts_by_id: dict, packet: dict, section: str, hook_fact: dict | None):
    if section == "HOOK" and hook_fact and hook_fact.get("visual"):
        return hook_fact["visual"], hook_fact
    for fid in sentence_facts:
        f = facts_by_id.get(fid)
        if f and f.get("visual"):
            return f["visual"], f
    return None, (facts_by_id.get(sentence_facts[0]) if sentence_facts else None)


def build(ctx, *, video: dict, script: dict, narration, packet: dict, facts_by_id: dict, comment_prompt: str | None,
          series_id: str | None, total_duration: float, third_party: list[dict], licenses: dict) -> list[dict]:
    cfg = ctx.cfg
    fmt_cut = float((ctx.formats.get(video.get("format_id") or "") or {}).get("cut_frequency") or 1.5)
    max_beat = min(10.0 / fmt_cut * 1.6, 7.5)
    sentence_facts = [item.get("fact_ids", []) for sec in script["sections_json"] for item in sec["sentences"]
                      for _ in (split_sentences(item["text"]) or [item["text"]])]
    hook_fact = next((f for f in facts_by_id.values() if "hook" in (f.get("tags") or []) and f.get("visual")), None)
    timeline_events = packet.get("timeline") or {}
    speech_end = narration.sentences[-1]["end"] if narration.sentences else total_duration
    topic_terms = set(content_words(packet.get("topic", "")))

    shots = []
    for i, s in enumerate(narration.sentences):
        start = 0.0 if i == 0 else s["start"]
        end = narration.sentences[i + 1]["start"] if i + 1 < len(narration.sentences) else total_duration
        spec, fact = _visual_spec(sentence_facts[i] if i < len(sentence_facts) else [], facts_by_id, packet,
                                  s["section"], hook_fact)
        n = max(1, math.ceil((end - start) / max_beat - 1e-9))
        step = (end - start) / n
        for k in range(n):
            shots.append({"section": s["section"], "start": round(start + k * step, 3),
                          "end": round(start + (k + 1) * step, 3), "narration": s["text"], "part": k, "parts": n,
                          "spec": spec, "fact": fact, "sentence_index": i})

    scenes, prev_clip = [], None
    tp_used = 0.0
    tp_limit = float(cfg.get("source_policy.max_source_screen_ratio")) * total_duration
    for idx, shot in enumerate(shots):
        dur = shot["end"] - shot["start"]
        graphics: list[dict] = []
        spec = dict(shot["spec"] or {})
        src, visual_type, s_in, framing, effect = None, "generated", 0.0, "crop", "none"
        if not spec and third_party:
            best = max(((match_score(shot["narration"], set(), v), v) for v in third_party), key=lambda x: x[0])
            if best[0] > 0 and tp_used + dur <= tp_limit:
                src, visual_type = best[1], "footage"
                w, h = src.get("width") or 0, src.get("height") or 0
                framing = "blur_fill" if w and h and w / h > 0.7 else "crop"
                effect = "slow_zoom_in"
                tp_used += dur
                lic = licenses.get(src["source_id"]) or {}
                if lic.get("attribution_required"):
                    graphics.append({"type": "attribution", "text": lic.get("attribution_text")
                                     or f"{src.get('title')} — {src.get('creator')} ({lic.get('license_type')})"})
        if src is None:
            if not spec:
                key = short_title(shot["narration"], max_chars=34)
                spec = {"generator": FALLBACK_GENERATOR, "params": {"text": key, "sub": ""}}
            gen, params = spec["generator"], dict(spec.get("params") or {})
            if gen == "timeline":
                params = {"events": timeline_events, "active": params.get("active")}
            if gen == "mandelbrot_zoom":
                params.setdefault("colormap", ctx.brand.get("fractal_colormap", "viridis"))
            # one clip per sentence (all its shots share it, at different in-points)
            clip_len = round(sum(x["end"] - x["start"] for x in shots if x["sentence_index"] == shot["sentence_index"])
                             + 0.5, 1)
            src = visuals.generate(ctx, gen, params, clip_len, topic_id=video["topic_id"],
                                   tags=sorted(topic_terms))
            s_in = round(shot["start"] - next(x["start"] for x in shots if x["sentence_index"] == shot["sentence_index"]), 3)
            if shot["parts"] > 1 and shot["part"] > 0:
                effect = "punch_in"  # a visible change inside a long beat
        if src["source_id"] == prev_clip and shot["part"] == 0:
            effect = "punch_in"
        prev_clip = src["source_id"]
        if idx == 0:
            effect = "punch_in"
            graphics.append({"type": "title_card", "text": short_title(script["selected_hook"], max_chars=48),
                             "end": min(dur, float(cfg.get("qc.max_hook_seconds")))})
            tag = brand_mod.series_tag(ctx, series_id)
            if tag is not None:
                path = ctx.ws.visuals_dir(video["base_name"]) / "series_tag.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                tag.save(path)
                graphics.append({"type": "image", "path": str(path), "end": min(dur, 2.5)})
        scenes.append({
            "scene_id": new_id("scn"), "idx": idx, "section": shot["section"], "start_time": shot["start"],
            "end_time": shot["end"], "visual_source": src["source_id"], "source_in": s_in,
            "source_out": round(s_in + dur, 3), "visual_type": visual_type, "framing": framing, "effect": effect,
            "narration": shot["narration"] if shot["part"] == 0 else "", "caption": shot["narration"] if shot["part"] == 0
            else "(continued)", "transition": "cut", "sound_effect": None, "graphics": graphics,
            "generator": spec.get("generator") if visual_type == "generated" else None,
        })

    # end card: the comment prompt, after the narration has finished
    outro = (ctx.series.get(series_id or "") or {}).get("outro_style") or ctx.brand.get("outro_style")
    if outro == "question_card" and comment_prompt and scenes:
        card = brand_mod.question_card(ctx, comment_prompt)
        path = ctx.ws.visuals_dir(video["base_name"]) / "question_card.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        card.save(path)
        last = scenes[-1]
        start = max(0.0, speech_end + 0.15 - last["start_time"])
        last["graphics"].append({"type": "image", "path": str(path), "start": round(start, 2)})
    # whooshes mark section changes only
    if cfg.get("sfx.enabled"):
        for i, sc in enumerate(scenes):
            if i and sc["section"] != scenes[i - 1]["section"]:
                sc["sound_effect"] = "whoosh"
    return scenes


def emphasis_words(script: dict, packet: dict) -> set[str]:
    """Words worth colouring in captions: years/numbers, people's surnames and a few key terms."""
    words = set()
    for s in script["sections_json"]:
        for x in s["sentences"]:
            words |= numbers_in(x["text"])
    for person in packet.get("people", []):
        words.add(person.split()[-1].lower())
    words |= {"fractal", "infinity", "dimension", "connected"} & set(content_words(script["full_text"]))
    return words


def screen_stats(scenes: list[dict], duration: float) -> dict:
    third = sum(s["end_time"] - s["start_time"] for s in scenes if s["visual_type"] in ("footage", "still"))
    by_source: dict[str, float] = {}
    for s in scenes:
        by_source[s["visual_source"] or "graphic"] = by_source.get(s["visual_source"] or "graphic", 0.0) + \
            s["end_time"] - s["start_time"]
    changes = max(0, len(scenes) - 1) + sum(1 for s in scenes for g in s["graphics"] if g["type"] != "attribution")
    return {"third_party_ratio": round(third / duration, 3), "visual_changes_per_10s": round(10 * changes / duration, 2),
            "max_single_visual_share": round(max(by_source.values()) / duration, 3) if by_source else 0.0,
            "original_visual_ratio": round(1 - third / duration, 3), "scenes": len(scenes),
            "distinct_visuals": len(by_source)}
