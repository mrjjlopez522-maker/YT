"""Automated QC gate. A video becomes READY_FOR_REVIEW (status REVIEW) only if
every blocking check passes; otherwise NEEDS_REVISION and the pipeline stops.

Checks (spec order, then extras):
  legal_source_verification, rights_metadata_exists, original_script_exists,
  original_narration_exists, fact_checking_complete, captions_synchronized,
  audio_quality_acceptable, video_resolution_correct, aspect_ratio_9_16,
  no_black_frames, no_corrupted_frames, no_excessive_silence,
  no_source_watermark, no_unauthorized_music, no_misleading_claims,
  no_duplicate_content, hook_exists, ending_payoff_exists,
  + style_quality, duration_within_target, transformation_limits, attribution_present
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..content import metadata as metadata_mod
from ..content import style as style_mod
from ..media import captions as captions_mod
from ..media import ffmpeg
from ..media.storyboard import screen_time
from ..media.tts import WordTiming
from ..research.topic_research import load_facts
from ..sources.rights import REGISTRY
from ..textutil import longest_common_run, now_iso
from . import duplicates


@dataclass
class Check:
    name: str
    passed: bool
    details: str
    severity: str = "blocking"   # blocking | warning
    data: dict = field(default_factory=dict)


def _used_sources(ctx, video_id: str) -> list[dict]:
    return ctx.db.query(
        "SELECT DISTINCT s.* FROM sources s WHERE s.source_id IN "
        "(SELECT visual_source FROM scenes WHERE video_id = ? AND visual_source IS NOT NULL "
        " UNION SELECT source_id FROM assets WHERE video_id = ? AND source_id IS NOT NULL)", (video_id, video_id))


def _license(ctx, source_id: str) -> dict | None:
    rows = ctx.db.select("licenses", {"source_id": source_id})
    return rows[0] if rows else None


def run_qc(ctx, video_id: str) -> dict:
    cfg = ctx.cfg
    video = ctx.db.require("videos", video_id)
    script = ctx.db.get("scripts", video["script_id"]) if video.get("script_id") else None
    render_path = Path(video.get("render_path") or "")
    scenes = ctx.db.select("scenes", {"video_id": video_id}, order_by="idx")
    assets = ctx.db.select("assets", {"video_id": video_id})
    used = _used_sources(ctx, video_id)
    checks: list[Check] = []
    risk: list[str] = []

    def add(name, ok, details, severity="blocking", **data):
        checks.append(Check(name, bool(ok), details, severity, data))

    # 1-2 rights ---------------------------------------------------------------
    bad = []
    for s in used:
        lic = _license(ctx, s["source_id"])
        if s["status"] != "INGESTED" or not lic or lic["verification_status"] != "VERIFIED":
            bad.append(s["source_id"])
    add("legal_source_verification", not bad,
        f"{len(used)} source(s) used; all rights-verified" if not bad else f"unverified sources used: {bad}")
    missing = []
    for s in used:
        lic = _license(ctx, s["source_id"]) or {}
        terms = REGISTRY.get(lic.get("license_type", ""))
        problems = [k for k in ("license_type", "rights_confidence", "evidence_path") if not lic.get(k)]
        if lic.get("evidence_path") and not Path(lic["evidence_path"]).exists():
            problems.append("evidence file missing")
        if terms and terms.requires_reference and not lic.get("permission_reference"):
            problems.append("permission_reference")
        if lic.get("attribution_required") and not (s.get("creator") or lic.get("attribution_text")):
            problems.append("creator/attribution")
        if problems:
            missing.append({s["source_id"]: problems})
        if lic.get("verified_by", "").startswith("human"):
            risk.append(f"{s['source_id']}: rights verified by {lic['verified_by']}")
        for reason in lic.get("reasons_json") or []:
            if isinstance(reason, str) and reason.startswith("risk: "):
                risk.append(f"{s['source_id']}: {reason[6:]}")
    add("rights_metadata_exists", not missing, "complete rights records" if not missing else f"incomplete: {missing}")

    # 3 original script ----------------------------------------------------------
    if script:
        facts = load_facts(ctx, video["topic_id"])
        max_run = int(cfg.get("content.max_ngram_overlap"))
        third_party = [f["text"] for f in facts if not f.get("own_words")]
        third_party += [s.get("description") or "" for s in used]
        third_party += [((s.get("analysis_json") or {}).get("transcript") or {}).get("text", "") for s in used]
        runs = [longest_common_run(script["full_text"], t) for t in third_party if t]
        worst = max(runs, default=0)
        verbatim = [i for i in (script.get("style_report_json") or {}).get("issues", []) if i["rule"] == "verbatim_copy"]
        add("original_script_exists", worst <= max_run and not verbatim,
            f"longest run shared with third-party text: {worst} words (limit {max_run})", longest_run=worst)
    else:
        facts = []
        add("original_script_exists", False, "no script")

    # 4 narration ---------------------------------------------------------------
    voice = next((a for a in assets if a["kind"] == "voice"), None)
    words_file = ctx.ws.captions_path(video["base_name"], "words.json")
    words = [WordTiming(**w) for w in json.loads(words_file.read_text())] if words_file.exists() else []
    script_words = script["full_text"].split() if script else []
    add("original_narration_exists", bool(voice and voice.get("duration") and words and len(words) == len(script_words)),
        f"narration of {len(words)} words generated from the script ({len(script_words)} words)")

    # 5 fact check ---------------------------------------------------------------
    claims = ctx.db.select("claims", {"script_id": script["script_id"]}) if script else []
    allowed = {"VERIFIED"} | ({"NEEDS_REVIEW"} if cfg.get("factcheck.allow_needs_review_claims") else set())
    bad_claims = [c for c in claims if c["status"] not in allowed]
    add("fact_checking_complete", bool(script and claims and not bad_claims and script["factcheck_status"] == "PASSED"),
        f"{len(claims)} claims, {len(bad_claims)} not verified", unverified=[c["claim"] for c in bad_claims])
    if any(c["status"] == "NEEDS_REVIEW" for c in claims):
        risk.append("some claims need human review")
    if any((c.get("notes") or "").find("tertiary") >= 0 for c in claims):
        risk.append("some claims rest only on tertiary sources (e.g. Wikipedia) — consider a primary source")

    # media probes -------------------------------------------------------------------
    info = ffmpeg.probe(render_path) if render_path.is_file() else None
    duration = info.duration if info else 0.0

    # 6 captions -------------------------------------------------------------------
    if words and info:
        style = captions_mod.load_style(ctx, (next((a for a in assets if a["kind"] == "captions_ass"), {}) or {})
                                        .get("meta_json", {}).get("style"))
        chunks = captions_mod.chunk_words(words, style)
        problems = captions_mod.validate(chunks, words, duration)
        if chunks and chunks[0].start > 1.0:
            problems.append(f"first caption starts at {chunks[0].start:.2f}s")
        add("captions_synchronized", not problems, "captions aligned to narration word timings" if not problems
            else "; ".join(problems[:4]))
    else:
        add("captions_synchronized", False, "missing narration timings or render")

    # 7 audio ---------------------------------------------------------------------------
    if info and info.has_audio:
        loud = ffmpeg.loudness(render_path)
        target, tol = float(cfg.get("audio.target_lufs")), float(cfg.get("audio.loudness_tolerance_lu"))
        tp_max = float(cfg.get("audio.true_peak_db")) + 0.5
        ok = abs(loud["integrated_lufs"] - target) <= tol and loud["true_peak_db"] <= tp_max
        add("audio_quality_acceptable", ok, f"{loud['integrated_lufs']:.1f} LUFS (target {target}±{tol}), "
                                            f"true peak {loud['true_peak_db']:.1f} dBTP (max {tp_max})", **loud)
    else:
        add("audio_quality_acceptable", False, "render has no audio")

    # 8-9 format ----------------------------------------------------------------------------
    w, h = cfg.resolution
    add("video_resolution_correct", bool(info and (info.width, info.height) == (w, h)),
        f"{info.width}x{info.height}" if info else "no render")
    add("aspect_ratio_9_16", bool(info and info.width and info.width * 16 == info.height * 9),
        "9:16" if info and info.width and info.width * 16 == info.height * 9 else "not 9:16")
    if info:
        add("h264_aac_container", info.video_codec == "h264" and info.audio_codec == "aac" and info.pix_fmt == "yuv420p",
            f"{info.video_codec}/{info.audio_codec}/{info.pix_fmt} @ {info.fps}fps")

    # 10-12 frames and silence --------------------------------------------------------------
    if info:
        black = [b for b in ffmpeg.detect_black(render_path, min_duration=0.1)
                 if b[1] - b[0] > float(cfg.get("qc.max_black_seconds"))]
        add("no_black_frames", not black, "no black segments" if not black else f"black segments: {black}")
        errors = ffmpeg.decode_errors(render_path)
        expected = round(duration * float(cfg.get("production.fps")))
        frames_ok = info.nb_frames is None or abs(info.nb_frames - expected) <= 2
        add("no_corrupted_frames", not errors and frames_ok,
            f"decoded cleanly; {info.nb_frames} frames (expected ~{expected})" if not errors
            else f"decoder errors: {errors[:3]}")
        max_sil = float(cfg.get("qc.max_silence_seconds"))
        speech_end = words[-1].end if words else duration
        long_sil = [s for s in ffmpeg.detect_silence(render_path, min_duration=max_sil) if s[0] < speech_end - 0.05]
        add("no_excessive_silence", not long_sil,
            f"no silence over {max_sil}s during narration" if not long_sil else f"silences: {long_sil}")
    else:
        for n in ("no_black_frames", "no_corrupted_frames", "no_excessive_silence"):
            add(n, False, "no render")

    # 13 watermark ---------------------------------------------------------------------------
    flagged, inconclusive = [], []
    for s in used:
        wm = ((s.get("analysis_json") or {}).get("watermark") or {})
        lic = _license(ctx, s["source_id"]) or {}
        reviewed = "watermark reviewed" in (lic.get("permission_notes") or "").lower()
        if wm.get("status") == "possible_watermark" and not reviewed:
            flagged.append(s["source_id"])
        elif wm.get("status") == "inconclusive":
            inconclusive.append(s["source_id"])
    add("no_source_watermark", not flagged,
        "no watermark-like static overlays detected" if not flagged else f"possible watermark in {flagged}")
    if inconclusive:
        risk.append(f"watermark check inconclusive for {inconclusive} — look at the footage")

    # 14 music -----------------------------------------------------------------------------
    unauthorized = []
    for a in assets:
        if a["kind"] in ("music", "sfx", "ambience") and a.get("meta_json") and a["meta_json"].get("music_source"):
            if not a.get("source_id"):
                src = ctx.db.query("SELECT s.source_id FROM sources s JOIN licenses l ON l.source_id = s.source_id "
                                   "WHERE s.local_path = ? AND l.verification_status = 'VERIFIED'",
                                   (a["meta_json"]["music_source"],))
                if not src:
                    unauthorized.append(a["path"])
    if cfg.get("source_policy.use_source_audio"):
        unauthorized += [s["source_id"] for s in used if s.get("has_audio") and
                         not (_license(ctx, s["source_id"]) or {}).get("audio_reuse_allowed")]
    music_policy = cfg.get("music.policy")
    add("no_unauthorized_music", not unauthorized,
        f"music policy '{music_policy}'; soundtrack is the studio's own mix" if not unauthorized
        else f"unlicensed audio: {unauthorized}")

    # 15 misleading claims -------------------------------------------------------------------
    style_cfg = metadata_mod.load_style(ctx)
    title = video.get("selected_title") or ""
    issues = []
    if script:
        score, crit = metadata_mod.title_score(title, script["full_text"], ctx.db.require("topics", video["topic_id"])["topic"],
                                               [], style_cfg)
        if score <= 0:
            issues.append(f"title not supported by the script or clickbait ({crit})")
        facts_text = " ".join(f["text"] for f in facts).lower()
        for term in style_mod.absolute_terms(title + " " + (video.get("selected_description") or ""), style_cfg):
            if term not in facts_text:
                issues.append(f"absolute term '{term}' not backed by research")
        if any(c["status"] == "REJECTED" for c in claims):
            issues.append("rejected claims present")
    add("no_misleading_claims", not issues, "title/description consistent with verified research" if not issues
        else "; ".join(issues))

    # 16 duplicates -----------------------------------------------------------------------------
    dup = duplicates.check_video(ctx, video_id)
    add("no_duplicate_content", not dup["flags"],
        f"compared with {dup['compared']} video(s); max similarity "
        f"{max((v['similarity'] for k, v in dup['max'].items() if k in duplicates.BLOCKING), default=0):.2f}"
        if not dup["flags"] else f"too similar: {dup['flags']}", report=dup)
    if dup["topic_repeat"]:
        risk.append(f"same topic as {dup['topic_repeat']} — make sure the angle is new")

    # 17-18 structure -------------------------------------------------------------------------
    sections = {s["name"]: s for s in (script["sections_json"] if script else [])}
    hook_words = [x for x in words if x.section == "HOOK"]
    hook_ok = bool(sections.get("HOOK") and hook_words and hook_words[0].start <= 1.0
                   and hook_words[-1].end - hook_words[0].start <= float(cfg.get("qc.max_hook_seconds")))
    add("hook_exists", hook_ok, f"hook '{script['selected_hook'] if script else ''}' spoken "
                                f"{hook_words[0].start:.2f}-{hook_words[-1].end:.2f}s" if hook_words else "no hook")
    payoff_words = [x for x in words if x.section == "PAYOFF"]
    payoff_ok = bool(sections.get("PAYOFF") and payoff_words and duration and payoff_words[0].start >= 0.4 * duration)
    add("ending_payoff_exists", payoff_ok, f"payoff from {payoff_words[0].start:.1f}s of {duration:.1f}s"
        if payoff_words else "no payoff")

    # extras --------------------------------------------------------------------------------------
    if script:
        rep = script.get("style_report_json") or {}
        add("style_quality", rep.get("passed", False), "no slop patterns" if rep.get("passed")
            else "; ".join(f"{i['rule']}: {i.get('detail')}" for i in rep.get("issues", [])[:5]))
    target = float(cfg.get("production.target_duration"))
    tol = float(cfg.get("production.duration_tolerance"))
    add("duration_within_target", bool(info and abs(duration - target) <= tol * target
                                       and duration <= float(cfg.get("production.max_duration"))),
        f"{duration:.1f}s (target {target:.0f}s ±{int(tol * 100)}%)")
    st = screen_time([dict(s, visual_type=s["visual_type"]) for s in scenes]) if scenes else {}
    coverage = ((words[-1].end - words[0].start) / duration) if words and duration else 0.0
    lim_ok = bool(st) and st["source_ratio"] <= float(cfg.get("source_policy.max_source_screen_ratio")) + 1e-6 \
        and st["longest_source_shot"] <= float(cfg.get("source_policy.max_continuous_source_seconds")) + 1e-6 \
        and coverage >= float(cfg.get("qc.min_narration_coverage"))
    add("transformation_limits", lim_ok, f"source on screen {st.get('source_ratio', 0):.0%}, longest shot "
                                         f"{st.get('longest_source_shot', 0):.1f}s, narration covers {coverage:.0%}",
        screen_time=st, narration_coverage=round(coverage, 3))
    missing_attr = []
    for s in used:
        lic = _license(ctx, s["source_id"]) or {}
        if lic.get("attribution_required"):
            in_desc = (s.get("creator") or "") in (video.get("selected_description") or "")
            on_screen = all(any(g["type"] == "attribution" for g in (sc.get("graphics_json") or []))
                            for sc in scenes if sc.get("visual_source") == s["source_id"])
            if not (in_desc and on_screen):
                missing_attr.append(s["source_id"])
    add("attribution_present", not missing_attr, "all required credits on screen and in the description"
        if not missing_attr else f"missing credits for {missing_attr}")
    if ctx.cfg.get("voice.provider") == "espeak":
        risk.append("narration uses the espeak-ng development voice (robotic) — use a natural TTS provider to publish")

    blocking_failed = [c for c in checks if c.severity == "blocking" and not c.passed]
    report = {"passed": not blocking_failed, "checked_at": now_iso(),
              "checks": [asdict(c) for c in checks], "failed": [asdict(c) for c in blocking_failed],
              "risk_flags": risk}
    ctx.db.update("videos", video_id, {"qc_status": "PASSED" if report["passed"] else "FAILED",
                                       "qc_report_json": report, "risk_flags_json": risk, "updated_at": now_iso()})
    out = ctx.ws.export_dir(video["base_name"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "qc_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
