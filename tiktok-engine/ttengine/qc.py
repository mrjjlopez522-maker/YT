"""TikTok QC: the studio QC gate plus TikTok-specific checks.

Added checks: research_packet_complete, original_editing, format_pacing, promise_kept,
caption_safe_zone, no_engagement_bait, ai_disclosure, caption_length, audio_rights,
cost_within_budget, standalone_value ("would this still be worth watching if the
viewer had never seen the source material?"), plus an informational monetization
length note.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from studio.analytics.costs import CostTracker
from studio.media.captions import load_style
from studio.qc.checks import Check, run_qc
from studio.textutil import now_iso
from . import formats as formats_mod
from . import packet as packet_mod
from .script import bait_issues
from .script import load_style as load_text_style


def run(ctx, video_id: str) -> dict:
    cfg = ctx.cfg
    base = run_qc(ctx, video_id)
    v = ctx.db.require("videos", video_id)
    script = ctx.db.require("scripts", v["script_id"])
    md = v.get("metadata_json") or {}
    stats = md.get("screen_stats") or {}
    fmt = ctx.formats.get(v.get("format_id") or "")
    checks: list[Check] = []

    def add(name, ok, details, severity="blocking", **data):
        checks.append(Check(name, bool(ok), details, severity, data))

    pk = packet_mod.load(ctx, v["topic_id"]) or {}
    add("research_packet_complete", pk.get("complete"),
        f"{len(pk.get('important_facts', []))} facts, {len(pk.get('sources', []))} sources, "
        f"{len(pk.get('primary_sources', []))} primary" if pk else "no research packet")

    min_changes = float(cfg.get("qc.min_visual_changes_per_10s"))
    max_share = float(cfg.get("qc.max_single_visual_share"))
    max_tp = float(cfg.get("source_policy.max_source_screen_ratio"))
    edit_ok = (stats.get("visual_changes_per_10s", 0) >= min_changes and stats.get("max_single_visual_share", 1) <= max_share
               and stats.get("third_party_ratio", 1) <= max_tp and stats.get("original_visual_ratio", 0) > 0)
    add("original_editing", edit_ok,
        f"{stats.get('visual_changes_per_10s')} visual changes/10s (min {min_changes}), largest single visual "
        f"{stats.get('max_single_visual_share', 0):.0%} (max {max_share:.0%}), third-party footage "
        f"{stats.get('third_party_ratio', 0):.0%}, {stats.get('distinct_visuals')} distinct visuals", **stats)

    words = json.loads(ctx.ws.captions_path(v["base_name"], "words.json").read_text())
    duration = float(v.get("duration") or 0)
    if fmt and words and duration:
        win = formats_mod.section_windows(fmt, duration)
        hook_end = max(w["end"] for w in words if w["section"] == "HOOK")
        payoff_start = min((w["start"] for w in words if w["section"] == "PAYOFF"), default=duration)
        hook_limit = max(win["HOOK"][1] + 1.0, float(cfg.get("qc.max_hook_seconds")))
        payoff_floor = win.get("PAYOFF", (0.6 * duration, duration))[0] * 0.75
        add("format_pacing", hook_end <= hook_limit and payoff_start >= payoff_floor,
            f"hook ends {hook_end:.1f}s (limit {hook_limit:.1f}s); payoff starts {payoff_start:.1f}s "
            f"(template slot {win.get('PAYOFF', (0, 0))[0]:.1f}s, floor {payoff_floor:.1f}s)")
    else:
        add("format_pacing", False, "missing format, narration timings or render")

    promise = (script.get("blueprint_json") or {}).get("promise") or {}
    if not promise.get("kept"):
        detail = "the payoff does not answer the hook's premise"
    elif promise.get("shared_with_payoff"):
        detail = f"payoff picks up the hook's terms {promise['shared_with_payoff']}"
    else:
        detail = f"the question hook is answered in the body (shared terms {promise.get('shared_with_body')})"
    add("promise_kept", promise.get("kept"), detail)

    style = load_style(ctx, (ctx.series.get(v.get("series_id") or "") or {}).get("caption_style"))
    zone = cfg.get("qc.caption_safe_zone")
    safe = (style.get("margin_v", 0) >= zone["min_margin_v"] and style.get("margin_lr", 0) >= zone["min_margin_lr"]
            and style.get("font_size", 0) >= zone["min_font_size"])
    add("caption_safe_zone", safe, f"style {style['name']}: margin_v {style.get('margin_v')}, margin_lr "
                                   f"{style.get('margin_lr')}, font {style.get('font_size')}")

    text_style = load_text_style(ctx)
    prompts = [p["text"] for p in ctx.db.select("comment_prompts", {"video_id": video_id})]
    texts = [v.get("caption") or "", v.get("selected_description") or "", *prompts, script["full_text"]]
    bait = sorted(set(bait_issues(texts, text_style)))
    add("no_engagement_bait", not bait, "no bait, fake urgency or fake engagement prompts" if not bait
        else f"found: {bait}")

    synthetic = cfg.get("voice.provider") in ("kokoro", "espeak", "elevenlabs")
    disclosed = (md.get("disclosure") or "") and md["disclosure"] in (v.get("caption") or "")
    add("ai_disclosure", (not synthetic) or disclosed or not cfg.get("publishing.disclose_synthetic_voice"),
        "synthetic narration disclosed in the post text" if disclosed else "no synthetic media to disclose"
        if not synthetic else "synthetic narration not disclosed (publishing.disclose_synthetic_voice)")

    cap_len = len(v.get("caption") or "")
    add("caption_length", 0 < cap_len <= int(cfg.get("publishing.max_caption_chars")),
        f"{cap_len} characters (limit {cfg.get('publishing.max_caption_chars')})")

    bad_audio = []
    for a in ctx.db.select("audio", {"video_id": video_id}):
        if a["track"] in ("MUSIC", "SFX", "AMBIENCE") and a.get("source_id"):
            lic = ctx.db.select("licenses", {"source_id": a["source_id"]})
            if not lic or lic[0]["verification_status"] != "VERIFIED":
                bad_audio.append(a["track"])
    add("audio_rights", not bad_audio, "all music/SFX tracks have verified rights records (original or licensed)"
        if not bad_audio else f"unverified: {bad_audio}")

    costs = CostTracker(ctx)
    spent = costs.spent(video_id=video_id)
    add("cost_within_budget", spent <= costs.max_per_video + 1e-9, f"${spent:.4f} of ${costs.max_per_video:.2f}")

    coverage = next((c["data"].get("narration_coverage") for c in base["checks"] if c["name"] == "transformation_limits"),
                    0) or 0
    standalone = (stats.get("third_party_ratio", 1) <= 0.5 and coverage >= float(cfg.get("qc.min_narration_coverage"))
                  and (script.get("blueprint_json") or {}).get("standalone_test", {}).get("passes", False))
    add("standalone_value", standalone,
        f"narration covers {coverage:.0%}; third-party footage {stats.get('third_party_ratio', 0):.0%}; "
        "the story is carried by original narration, research and graphics")

    add("monetization_length", duration >= 60, f"{duration:.0f}s — Creator Rewards counts only videos of 1 minute or "
        "longer" if duration < 60 else f"{duration:.0f}s (eligible length for Creator Rewards)", severity="warning")

    extra = [asdict(c) for c in checks]
    all_checks = base["checks"] + extra
    failed = [c for c in all_checks if c["severity"] == "blocking" and not c["passed"]]
    risk = list(base["risk_flags"])
    risk = [r for r in risk if "espeak" not in r] + (
        ["narration uses the espeak-ng development voice (robotic)"] if cfg.get("voice.provider") == "espeak" else [])
    if not pk.get("primary_sources"):
        risk.append("no primary source in the research packet")
    report = {"passed": not failed, "checked_at": now_iso(), "checks": all_checks, "failed": failed,
              "risk_flags": risk}
    ctx.db.update("videos", video_id, {"qc_status": "PASSED" if report["passed"] else "FAILED",
                                       "qc_report_json": report, "risk_flags_json": risk, "updated_at": now_iso()})
    out = ctx.ws.export_dir(v["base_name"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "qc_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
