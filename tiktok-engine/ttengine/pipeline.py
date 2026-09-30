"""TikTok pipeline: IDEA → RESEARCH → SOURCE → SCRIPT → VOICE → EDIT → QC → REVIEW.

Every stage records what it produced; a failure records the error, marks the
video FAILED with the stage (resumable), and stops. QC failure → NEEDS_REVISION.
Nothing is published without a human decision.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from studio.analytics.costs import CostTracker, attach_topic_costs
from studio.errors import DailyLimitError, StudioError, ValidationError
from studio.logging_setup import get_logger
from studio.media import audio as audio_mod
from studio.media import captions as captions_mod
from studio.media import ffmpeg, graphics, render
from studio.media import storyboard as core_storyboard
from studio.media.tts import WordTiming, narrate
from studio.paths import video_base_name
from studio.research.topic_research import get_or_create_topic, load_facts, research_topic
from studio.sources import discovery
from studio.textutil import new_id, now_iso, sha256_file, today
from . import brand as brand_mod
from . import formats as formats_mod
from . import metadata as metadata_mod
from . import packet as packet_mod
from . import script as script_mod
from . import sound, states
from . import storyboard as sb
from . import voice as voice_mod

log = get_logger("tiktok.pipeline")
STAGES = ["research", "source", "script", "voice", "edit", "qc"]
STAGE_STATUS = {"research": "RESEARCH", "source": "SOURCE", "script": "SCRIPT", "voice": "VOICE", "edit": "EDIT",
                "qc": "QC"}


def videos_today(ctx) -> int:
    return int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE channel_id = ? AND substr(created_at,1,10) = ?",
                             (ctx.cfg.channel_id, today().isoformat())))


def create_video(ctx, topic_id: str, *, format_id: str, series_id: str | None = None, mode: str = "EVERGREEN",
                 idea_id: str | None = None, experiment_vars: dict | None = None) -> dict:
    limit = int(ctx.cfg.get("calendar.videos_per_day"))
    if videos_today(ctx) >= limit:
        raise DailyLimitError(f"Daily production limit reached ({limit}); quality over quantity",
                              hint="calendar.videos_per_day")
    formats_mod.get(ctx, format_id)
    if series_id and series_id not in ctx.series:
        raise ValidationError(f"Unknown series {series_id!r}")
    topic = ctx.db.require("topics", topic_id)
    seq = int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE topic_id = ?", (topic_id,))) + 1
    base = video_base_name(today(), topic["slug"], seq)
    now = now_iso()
    row = {"video_id": base, "channel_id": ctx.cfg.channel_id, "topic_id": topic_id, "base_name": base, "seq": seq,
           "status": "IDEA", "format_id": format_id, "series_id": series_id, "mode": mode, "idea_id": idea_id,
           "platform": "tiktok", "experiment_vars_json": experiment_vars or {}, "created_at": now, "updated_at": now}
    ctx.db.insert("videos", row)
    ctx.db.insert("status_history", {"entity_type": "videos", "entity_id": base, "from_status": None,
                                     "to_status": "IDEA", "reason": f"created ({mode})", "created_at": now})
    return row


def _asset(ctx, video_id, kind, path, **kw):
    ctx.db.insert("assets", {"asset_id": new_id("ast"), "video_id": video_id, "kind": kind, "path": str(path),
                             "sha256": sha256_file(path) if Path(path).is_file() else None, "created_at": now_iso(),
                             **{k: v for k, v in kw.items() if k in ("source_id", "voice_id", "duration", "meta_json")}})


# -- stages ---------------------------------------------------------------------------------
def stage_research(ctx, v: dict) -> dict:
    res = research_topic(ctx, v["topic_id"])
    pk = packet_mod.build(ctx, v["topic_id"])
    if not pk["complete"]:
        topic = ctx.db.require("topics", v["topic_id"])
        raise ValidationError(f"Research packet incomplete: {[k for k, ok in pk['checks'].items() if not ok]}",
                              hint=f"add research/notes/{topic['slug']}.yaml (facts in your own words, cited)"
                                   + (f"; provider errors: {res['provider_errors']}" if res["provider_errors"] else ""))
    return {"facts": res["facts"], "sources": len(pk["sources"]), "primary_sources": len(pk["primary_sources"]),
            "contradictions": len(pk["contradictions"]), "warnings": pk["warnings"],
            "provider_errors": res["provider_errors"]}


def stage_source(ctx, v: dict) -> dict:
    """Licensed third-party sources (rights-gated) + a feasibility check of every visual requirement."""
    topic = ctx.db.require("topics", v["topic_id"])
    rep = discovery.discover(ctx, queries=[topic["topic"]], topic_id=v["topic_id"])
    from .visuals import GENERATORS
    facts = load_facts(ctx, v["topic_id"])
    missing = sorted({f["visual"]["generator"] for f in facts if f.get("visual")
                      and f["visual"].get("generator") not in GENERATORS})
    if missing:
        raise ValidationError(f"Research asks for visuals no generator can make: {missing}")
    return {"licensed_approved": len(rep.approved), "rejected": len(rep.rejected),
            "provider_errors": rep.provider_errors,
            "visual_requirements": sorted({f["visual"]["generator"] for f in facts if f.get("visual")})}


def stage_script(ctx, v: dict) -> dict:
    # budget words for the voice that will actually read this (measured, not assumed)
    series = ctx.series.get(v.get("series_id") or "") or {}
    wpm = voice_mod.effective_wpm(ctx, series.get("voice"))
    ctx.cfg.data["voice"]["words_per_minute"] = wpm
    s = script_mod.generate(ctx, v["topic_id"], format_id=v["format_id"], video_id=v["video_id"])
    if s["factcheck_status"] != "PASSED":
        raise ValidationError("Fact check did not pass")
    pk = packet_mod.load(ctx, v["topic_id"])
    topic = ctx.db.require("topics", v["topic_id"])
    prompts = script_mod.comment_prompts(ctx, pk, ctx.formats[v["format_id"]])
    ctx.db.delete("comment_prompts", {"video_id": v["video_id"]})
    for i, p in enumerate(prompts):
        ctx.db.insert("comment_prompts", {"prompt_id": new_id("cp"), "video_id": v["video_id"], "text": p["text"],
                                          "kind": p["kind"], "selected": int(i == 0), "created_at": now_iso()})
    md = metadata_mod.build(ctx, topic=topic, script=ctx.db.require("scripts", s["script_id"]), packet=pk,
                            comment_prompts=prompts)
    ctx.db.update("videos", v["video_id"], {"metadata_json": md, "selected_title": md["selected_caption"],
                                            "caption": md["post_text"], "selected_description": md["selected_description"],
                                            "tags_json": md["keywords"], "updated_at": now_iso()})
    return {"script_id": s["script_id"], "hook": s["selected_hook"], "hook_type": s["hook_type"],
            "words": s["word_count"], "est_duration": s["est_duration"], "wpm_budgeted": wpm,
            "promise_kept": s["blueprint_json"]["promise"]["kept"]}


def stage_voice(ctx, v: dict) -> dict:
    cfg = ctx.cfg
    v = ctx.db.require("videos", v["video_id"])
    script = ctx.db.require("scripts", v["script_id"])
    series = ctx.series.get(v.get("series_id") or "") or {}
    provider, lexicon = voice_mod.build(ctx, series.get("voice"))
    costs = CostTracker(ctx)
    if provider.paid:
        costs.check_budget(costs.tts_cost(provider.name, len(script["full_text"])), video_id=v["video_id"],
                           what="narration")
    outro = series.get("outro_style") or ctx.brand.get("outro_style")
    tail = 0.6 + (2.6 if outro == "question_card" else 0.0)
    adir = ctx.ws.audio_dir(v["base_name"])
    nar = narrate(provider, script["sections_json"], out_wav=adir / "voice_raw.wav",
                  wpm=int(cfg.get("voice.words_per_minute")), pitch=int(cfg.get("voice.pitch")),
                  sentence_pause=cfg.get("voice.sentence_pause_ms") / 1000,
                  section_pause=cfg.get("voice.section_pause_ms") / 1000,
                  hook_pitch_delta=int(cfg.get("voice.hook_pitch_delta")), lexicon=lexicon, tail=tail)
    costs.record("tts", provider.name, units=nar.chars, unit_type="characters",
                 usd=costs.tts_cost(provider.name, nar.chars) if provider.paid else 0.0, video_id=v["video_id"])
    words_path = ctx.ws.captions_path(v["base_name"], "words.json")
    words_path.write_text(json.dumps([w.__dict__ for w in nar.words], indent=1), encoding="utf-8")
    (adir / "narration.json").write_text(json.dumps({"duration": nar.duration, "sentences": nar.sentences,
                                                     "sections": nar.sections, "provider": nar.provider,
                                                     "voice": nar.voice}, indent=1), encoding="utf-8")
    vid = f"voice_{provider.name}_{getattr(provider, 'voice', '')}"
    if ctx.db.get("voices", vid) is None:
        ctx.db.insert("voices", {"voice_id": vid, "provider": provider.name, "voice_name": getattr(provider, "voice", ""),
                                 "settings_json": {"speed": cfg.get("voice.speed", 1.0),
                                                   "license": voice_mod.MODEL_LICENSE if provider.name == "kokoro" else None},
                                 "created_at": now_iso()})
    ctx.db.update("videos", v["video_id"], {"voice_id": vid, "updated_at": now_iso()})
    target = float(script["target_duration"])
    speech = nar.sentences[-1]["end"] if nar.sentences else 0
    return {"provider": provider.name, "voice": getattr(provider, "voice", ""), "duration": nar.duration,
            "speech_seconds": round(speech, 2), "target": target, "words": len(nar.words)}


def _narration(ctx, v: dict):
    from studio.media.tts import TTSResult
    adir = ctx.ws.audio_dir(v["base_name"])
    meta = json.loads((adir / "narration.json").read_text())
    words = [WordTiming(**w) for w in json.loads(ctx.ws.captions_path(v["base_name"], "words.json").read_text())]
    return TTSResult(audio_path=str(adir / "voice_raw.wav"), duration=meta["duration"], sample_rate=0, words=words,
                     sections=meta["sections"], sentences=meta["sentences"], provider=meta["provider"],
                     voice=meta["voice"])


def stage_edit(ctx, v: dict) -> dict:
    cfg = ctx.cfg
    v = ctx.db.require("videos", v["video_id"])
    vid, base = v["video_id"], v["base_name"]
    script = ctx.db.require("scripts", v["script_id"])
    pk = packet_mod.load(ctx, v["topic_id"])
    nar = _narration(ctx, v)
    duration = nar.duration
    brand_mod.apply(ctx, v.get("series_id"))
    for table in ("assets", "audio"):
        ctx.db.delete(table, {"video_id": vid})
    _asset(ctx, vid, "voice_raw", nar.audio_path, duration=duration)

    # visuals + storyboard (original visuals are generated and rights-registered here)
    third_party = [s for s in ctx.db.select("sources", {"topic_id": v["topic_id"], "status": "INGESTED", "role": "visual"})
                   if s["platform"] != "generated"]
    licenses = {r["source_id"]: r for r in ctx.db.query("SELECT * FROM licenses WHERE verification_status = 'VERIFIED'")}
    third_party = [s for s in third_party if s["source_id"] in licenses]
    facts_by_id = {f["fact_id"]: f for f in load_facts(ctx, v["topic_id"])}
    prompt = next((p["text"] for p in ctx.db.select("comment_prompts", {"video_id": vid, "selected": 1})), None)
    scenes = sb.build(ctx, video=v, script=script, narration=nar, packet=pk, facts_by_id=facts_by_id,
                      comment_prompt=prompt, series_id=v.get("series_id"), total_duration=duration,
                      third_party=third_party, licenses=licenses)
    core_storyboard.store_scenes(ctx, vid, scenes)
    sdir = ctx.ws.dir("storyboards")
    stats = sb.screen_stats(scenes, duration)
    (sdir / f"{base}.json").write_text(json.dumps({"scenes": scenes, "stats": stats, "narration": nar.sentences},
                                                  indent=2, default=str), encoding="utf-8")

    # sound design: VOICE / MUSIC / SFX / AMBIENCE
    bed = sound.music_bed(ctx, duration)
    whoosh = sound.transition_sfx(ctx)
    sfx_events = [(max(0.0, s["start_time"] - 0.2), Path(whoosh["local_path"])) for s in scenes
                  if s.get("sound_effect") and whoosh]
    adir = ctx.ws.audio_dir(base)
    tracks = audio_mod.build_tracks(ctx, voice_raw=Path(nar.audio_path), out_dir=adir, duration=duration,
                                    music_file=Path(bed["local_path"]) if bed else None, sfx_events=sfx_events)
    for kind, track, src in (("voice", "VOICE", None), ("music", "MUSIC", bed), ("sfx", "SFX", whoosh),
                             ("ambience", "AMBIENCE", None), ("mix", "MIX", None)):
        loud = ffmpeg.loudness(tracks[kind]) if kind in ("voice", "mix") else {}
        ctx.db.insert("audio", {"audio_id": new_id("aud"), "video_id": vid, "track": track, "path": str(tracks[kind]),
                                "source_id": (src or {}).get("source_id"),
                                "provider": nar.provider if kind == "voice" else ("generated" if src else None),
                                "duration": duration, "integrated_lufs": loud.get("integrated_lufs"),
                                "true_peak_db": loud.get("true_peak_db"), "created_at": now_iso()})
        _asset(ctx, vid, kind, tracks[kind], source_id=(src or {}).get("source_id"), duration=duration,
               meta_json={"music_source": (src or {}).get("local_path")} if kind in ("music", "sfx") and src else None)

    # captions
    style = captions_mod.load_style(ctx, (ctx.series.get(v.get("series_id") or "") or {}).get("caption_style"))
    chunks = captions_mod.chunk_words(nar.words, style)
    problems = captions_mod.validate(chunks, nar.words, duration)
    if problems:
        raise ValidationError("Caption timing invalid: " + "; ".join(problems[:4]))
    ass = ctx.ws.captions_path(base, "ass")
    ass.write_text(captions_mod.to_ass(chunks, style, cfg.resolution, emphasis_words=sb.emphasis_words(script, pk)),
                   encoding="utf-8")
    srt = ctx.ws.captions_path(base, "srt")
    srt.write_text(captions_mod.to_srt(chunks), encoding="utf-8")
    _asset(ctx, vid, "captions_ass", ass, meta_json={"style": style["name"], "chunks": len(chunks)})
    _asset(ctx, vid, "captions_srt", srt)

    # render
    sources_by_id = {s["source_id"]: s for s in ctx.db.select("sources", {"status": "INGESTED"})}
    out = ctx.ws.render_path(base)
    info = render.render_video(scenes=scenes, sources_by_id=sources_by_id, audio_mix=tracks["mix"], ass_path=ass,
                               duration=duration, out_path=out, work=ctx.ws.visuals_dir(base), cfg=cfg)
    costs = CostTracker(ctx)
    costs.record("rendering", "local", units=duration / 60, unit_type="render_minutes",
                 usd=costs.render_cost(duration / 60), video_id=vid)
    gb = out.stat().st_size / 1e9
    costs.record("storage", "local", units=gb, unit_type="GB-month", usd=costs.storage_cost(gb), video_id=vid)
    _asset(ctx, vid, "render", out, duration=info.duration)

    # cover: a frame from the hook visual, plus the cover timestamp for the TikTok API
    cover_t = min(1.2, duration / 2)
    frame = ffmpeg.extract_frame(out, cover_t, ctx.ws.visuals_dir(base) / "cover_frame.png")
    cover = graphics.thumbnail(script["selected_hook"] if len(script["selected_hook"]) < 60 else
                               core_storyboard.short_title(script["selected_hook"], 40), frame,
                               ctx.ws.thumbnail_path(base, 1).with_suffix(".jpg"))
    _asset(ctx, vid, "thumbnail", cover, meta_json={"cover_timestamp_ms": int(cover_t * 1000)})
    fp = formats_mod.fingerprint(scenes, nar.words, duration, (script["blueprint_json"] or {}).get("hook_type"),
                                 ctx.formats[v["format_id"]])
    md = dict(v.get("metadata_json") or {})
    md.update({"cover_timestamp_ms": int(cover_t * 1000), "format_fingerprint": fp, "screen_stats": stats})
    ctx.db.update("videos", vid, {"render_path": str(out), "duration": info.duration, "width": info.width,
                                  "height": info.height, "fps": info.fps, "metadata_json": md, "updated_at": now_iso()})
    return {"render": str(out), "duration": info.duration, "scenes": len(scenes), "stats": stats,
            "mix_loudness": tracks["mix_loudness"], "fingerprint": fp}


def stage_qc(ctx, v: dict) -> dict:
    from .qc import run
    return run(ctx, v["video_id"])


STAGE_FUNCS = {"research": stage_research, "source": stage_source, "script": stage_script, "voice": stage_voice,
               "edit": stage_edit, "qc": stage_qc}


def run_stages(ctx, video_id: str, stages: list[str]) -> dict:
    out: dict = {"video_id": video_id, "stages": {}}
    for stage in stages:
        v = ctx.db.require("videos", video_id)
        states.transition(ctx, video_id, STAGE_STATUS[stage], reason=f"{stage} started")
        try:
            out["stages"][stage] = STAGE_FUNCS[stage](ctx, v)
        except Exception as exc:  # noqa: BLE001 - recorded, then reported
            ctx.db.record_error(stage=stage, exc=exc, video_id=video_id, topic_id=v["topic_id"],
                                tb=traceback.format_exc())
            log.error("stage %s failed for %s: %s", stage, video_id, exc)
            states.transition(ctx, video_id, "FAILED", reason=f"{stage}: {exc}"[:500], extra={"failed_stage": stage})
            out.update({"status": "FAILED", "failed_stage": stage, "error": str(exc),
                        "hint": getattr(exc, "hint", None) if isinstance(exc, StudioError) else None})
            return out
        if stage == "qc":
            qc = out["stages"]["qc"]
            if qc["passed"]:
                states.transition(ctx, video_id, "REVIEW", reason="QC passed; ready for human review")
                from .review import write_page
                out["review_page"] = str(write_page(ctx, video_id))
                out["status"] = "REVIEW"
            else:
                states.transition(ctx, video_id, "NEEDS_REVISION",
                                  reason="QC failed: " + ", ".join(c["name"] for c in qc["failed"]))
                out["status"] = "NEEDS_REVISION"
            return out
    out["status"] = ctx.db.require("videos", video_id)["status"]
    return out


def run(ctx, *, topic: str | None = None, topic_id: str | None = None, format_id: str | None = None,
        series_id: str | None = None, mode: str = "EVERGREEN", idea_id: str | None = None) -> dict:
    if topic_id is None:
        if not topic:
            raise ValidationError("Give a topic")
        topic_id = get_or_create_topic(ctx, topic)["topic_id"]
    if format_id is None or series_id is None:  # the researcher's suggestions, if any
        t = ctx.db.require("topics", topic_id)
        notes = packet_mod.notes_for(ctx, t["topic"])
        format_id = format_id or notes.get("suggested_format") or "unexpected_fact_reveal"
        series_id = series_id if series_id is not None else notes.get("series")
    v = create_video(ctx, topic_id, format_id=format_id, series_id=series_id, mode=mode, idea_id=idea_id)
    attach_topic_costs(ctx, topic_id, v["video_id"])
    return run_stages(ctx, v["video_id"], STAGES)


def resume(ctx, video_id: str, from_stage: str | None = None) -> dict:
    v = ctx.db.require("videos", video_id)
    start = from_stage or v.get("failed_stage") or {"NEEDS_REVISION": "script", "REVIEW": "edit"}.get(v["status"])
    if start not in STAGES:
        raise ValidationError(f"Cannot resume {video_id} from {v['status']}")
    return run_stages(ctx, video_id, STAGES[STAGES.index(start):])
