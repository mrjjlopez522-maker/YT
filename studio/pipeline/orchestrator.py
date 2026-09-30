"""Pipeline orchestrator: IDEA -> RESEARCHING -> SOURCING -> SCRIPTING -> EDITING -> QC -> REVIEW.

Each stage validates its inputs, records what it produced, and on failure
records the error, marks the video FAILED (with the stage) and stops. A QC
failure marks NEEDS_REVISION and stops. Nothing continues past REVIEW without
a human decision.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from ..analytics.costs import CostTracker, attach_topic_costs
from ..content import metadata as metadata_mod
from ..content.script import generate_script
from ..errors import DailyLimitError, StudioError, ValidationError
from ..logging_setup import get_logger
from ..media import audio as audio_mod
from ..media import captions as captions_mod
from ..media import ffmpeg, graphics, render, storyboard, tts
from ..paths import video_base_name
from ..research.topic_research import get_or_create_topic, load_facts, research_topic
from ..sources import discovery
from ..textutil import new_id, now_iso, sha256_file, split_sentences, stable_id, today
from . import states

log = get_logger("pipeline")
STAGE_ORDER = ["research", "sourcing", "scripting", "editing", "qc"]
STAGE_STATUS = {"research": "RESEARCHING", "sourcing": "SOURCING", "scripting": "SCRIPTING", "editing": "EDITING",
                "qc": "QC"}


# -- video records -------------------------------------------------------------------
def videos_created_today(ctx) -> int:
    return int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE channel_id = ? AND substr(created_at,1,10) = ?",
                             (ctx.cfg.channel_id, today().isoformat())))


def create_video(ctx, topic_id: str, *, experiment_vars: dict | None = None) -> dict:
    limit = int(ctx.cfg.get("production.max_daily_videos"))
    if videos_created_today(ctx) >= limit:
        raise DailyLimitError(f"Daily production limit reached ({limit} videos)",
                              hint="production.max_daily_videos — quality over quantity")
    topic = ctx.db.require("topics", topic_id)
    seq = int(ctx.db.scalar("SELECT COUNT(*) FROM videos WHERE topic_id = ?", (topic_id,))) + 1
    base = video_base_name(today(), topic["slug"], seq)
    now = now_iso()
    row = {"video_id": base, "channel_id": ctx.cfg.channel_id, "topic_id": topic_id, "base_name": base, "seq": seq,
           "status": "IDEA", "experiment_vars_json": experiment_vars or {}, "created_at": now, "updated_at": now}
    ctx.db.insert("videos", row)
    ctx.db.insert("status_history", {"entity_type": "videos", "entity_id": base, "from_status": None,
                                     "to_status": "IDEA", "reason": "created", "created_at": now})
    return row


def _asset(ctx, video_id: str, kind: str, path: Path, *, source_id=None, voice_id=None, duration=None, meta=None):
    ctx.db.insert("assets", {"asset_id": new_id("ast"), "video_id": video_id, "kind": kind, "path": str(path),
                             "source_id": source_id, "voice_id": voice_id,
                             "sha256": sha256_file(path) if Path(path).is_file() else None, "duration": duration,
                             "meta_json": meta, "created_at": now_iso()})


# -- stages -----------------------------------------------------------------------------
def stage_research(ctx, video: dict) -> dict:
    res = research_topic(ctx, video["topic_id"])
    if res["status"] != "RESEARCHED":
        topic = ctx.db.require("topics", video["topic_id"])
        raise ValidationError(
            f"Research found {res['facts']} facts for '{topic['topic']}' (need {ctx.cfg.get('research.min_facts')})",
            hint=f"add research/notes/{topic['slug']}.yaml or enable a network research provider"
                 + (f"; provider errors: {res['provider_errors']}" if res["provider_errors"] else ""))
    return res


def source_queries(ctx, topic_id: str) -> list[str]:
    topic = ctx.db.require("topics", topic_id)
    tags = [t for f in load_facts(ctx, topic_id) for t in f.get("tags", [])
            if t not in {"setup", "development", "payoff", "hook", "origin", "person", "history", "definition",
                         "mechanism", "rule", "stakes", "contrast", "significance", "visual"}]
    return list(dict.fromkeys([topic["topic"], *tags]))[:6]


def stage_sourcing(ctx, video: dict) -> dict:
    report = discovery.discover(ctx, queries=source_queries(ctx, video["topic_id"]), topic_id=video["topic_id"])
    usable = ctx.db.select("sources", {"topic_id": video["topic_id"], "status": "INGESTED", "role": "visual"})
    if not usable and not ctx.cfg.get("production.allow_graphics_only"):
        raise ValidationError("No rights-verified visual sources were found",
                              hint="add licensed footage to sources/library with rights sidecars, or allow graphics-only")
    return {"approved": len(report.approved), "rejected": len(report.rejected), "usable_visuals": len(usable),
            "provider_errors": report.provider_errors}


def stage_scripting(ctx, video: dict) -> dict:
    script = generate_script(ctx, video["topic_id"], video_id=video["video_id"])
    if script["factcheck_status"] != "PASSED":
        raise ValidationError("Fact check did not pass", hint="review claims in the scripts/ output")
    topic = ctx.db.require("topics", video["topic_id"])
    facts = load_facts(ctx, video["topic_id"])
    sources = ctx.db.select("sources", {"topic_id": video["topic_id"], "status": "INGESTED"})
    lic = {r["source_id"]: r for r in ctx.db.query(
        "SELECT * FROM licenses WHERE source_id IN (SELECT source_id FROM sources WHERE topic_id = ?)",
        (video["topic_id"],))}
    past = [r["selected_title"] for r in ctx.db.query(
        "SELECT selected_title FROM videos WHERE channel_id = ? AND selected_title IS NOT NULL AND video_id != ?",
        (ctx.cfg.channel_id, video["video_id"]))]
    md = metadata_mod.build_metadata(topic=topic, script=script, facts=facts, sources=sources, licenses=lic,
                                     past_titles=past, style_cfg=metadata_mod.load_style(ctx),
                                     duration=script["est_duration"],
                                     synthetic_voice=ctx.cfg.get("voice.provider") in ("espeak", "elevenlabs"))
    ctx.db.update("videos", video["video_id"], {
        "metadata_json": md, "selected_title": md["selected_title"], "selected_description": md["selected_description"],
        "tags_json": md["keywords"], "updated_at": now_iso()})
    return {"script_id": script["script_id"], "hook": script["selected_hook"], "words": script["word_count"],
            "est_duration": script["est_duration"], "title": md["selected_title"]}


def _voice_row(ctx, provider) -> str:
    settings = {k: ctx.cfg.get(f"voice.{k}") for k in ("words_per_minute", "pitch", "sentence_pause_ms",
                                                         "section_pause_ms", "hook_pitch_delta")}
    vid = stable_id("voice", provider.name, getattr(provider, "voice", ""), json.dumps(settings, sort_keys=True))
    if ctx.db.get("voices", vid) is None:
        ctx.db.insert("voices", {"voice_id": vid, "provider": provider.name, "voice_name": getattr(provider, "voice", ""),
                                 "settings_json": settings, "created_at": now_iso()})
    return vid


def stage_editing(ctx, video: dict, *, caption_style: str | None = None) -> dict:
    cfg = ctx.cfg
    vid = video["video_id"]
    base = video["base_name"]
    video = ctx.db.require("videos", vid)
    script = ctx.db.require("scripts", video["script_id"])
    topic = ctx.db.require("topics", video["topic_id"])
    ctx.db.delete("assets", {"video_id": vid})
    costs = CostTracker(ctx)

    # narration
    provider = tts.build_tts(ctx)
    if provider.paid:
        chars = len(script["full_text"])
        costs.check_budget(costs.tts_cost(provider.name, chars), video_id=vid, what="TTS narration")
    voice_id = _voice_row(ctx, provider)
    adir = ctx.ws.audio_dir(base)
    narration = tts.narrate(
        provider, script["sections_json"], out_wav=adir / "voice_raw.wav", wpm=int(cfg.get("voice.words_per_minute")),
        pitch=int(cfg.get("voice.pitch")), sentence_pause=cfg.get("voice.sentence_pause_ms") / 1000,
        section_pause=cfg.get("voice.section_pause_ms") / 1000, hook_pitch_delta=int(cfg.get("voice.hook_pitch_delta")),
        lexicon=tts.load_lexicon(cfg.config_file(cfg.get("voice.pronunciation_file"))))
    costs.record("tts", provider.name, units=narration.chars, unit_type="characters",
                 usd=costs.tts_cost(provider.name, narration.chars) if provider.paid else 0.0, video_id=vid)
    duration = narration.duration

    # audio tracks (licensed music only, per policy)
    music_file = None
    if cfg.get("music.policy") == "licensed_library_only":
        music = ctx.db.query("SELECT s.* FROM sources s JOIN licenses l ON l.source_id = s.source_id "
                             "WHERE s.role = 'music' AND s.status = 'INGESTED' AND l.verification_status = 'VERIFIED' "
                             "ORDER BY s.date_found LIMIT 1")
        music_file = Path(music[0]["local_path"]) if music else None
    tracks = audio_mod.build_tracks(ctx, voice_raw=Path(narration.audio_path), out_dir=adir, duration=duration,
                                    music_file=music_file)
    for kind in ("voice", "music", "sfx", "ambience", "mix"):
        _asset(ctx, vid, kind, tracks[kind], voice_id=voice_id if kind == "voice" else None, duration=duration,
               meta={"music_source": str(music_file)} if kind == "music" and music_file else None)

    # captions
    style = captions_mod.load_style(ctx, caption_style)
    chunks = captions_mod.chunk_words(narration.words, style)
    problems = captions_mod.validate(chunks, narration.words, duration)
    if problems:
        raise ValidationError("Caption timing is invalid: " + "; ".join(problems[:5]))
    ass_path = ctx.ws.captions_path(base, "ass")
    srt_path = ctx.ws.captions_path(base, "srt")
    ass_path.write_text(captions_mod.to_ass(chunks, style, cfg.resolution), encoding="utf-8")
    srt_path.write_text(captions_mod.to_srt(chunks), encoding="utf-8")
    _asset(ctx, vid, "captions_ass", ass_path, meta={"style": style["name"], "chunks": len(chunks)})
    _asset(ctx, vid, "captions_srt", srt_path)
    words_path = ctx.ws.captions_path(base, "words.json")
    words_path.write_text(json.dumps([w.__dict__ for w in narration.words], indent=1), encoding="utf-8")

    # storyboard
    sources = ctx.db.select("sources", {"topic_id": video["topic_id"], "status": "INGESTED", "role": "visual"})
    licenses = {r["source_id"]: r for r in ctx.db.query(
        "SELECT * FROM licenses WHERE verification_status = 'VERIFIED' AND source_id IN "
        "(SELECT source_id FROM sources WHERE topic_id = ?)", (video["topic_id"],))}
    sources = [s for s in sources if s["source_id"] in licenses]
    facts_by_id = {f["fact_id"]: f for f in load_facts(ctx, video["topic_id"])}
    sentence_facts = []
    for sec in script["sections_json"]:
        for item in sec["sentences"]:
            for _ in split_sentences(item["text"]) or [item["text"]]:
                sentence_facts.append(item.get("fact_ids", []))
    hook_title = storyboard.short_title(video.get("selected_title") or script["selected_hook"])
    scenes = storyboard.build_storyboard(sentences=narration.sentences, total_duration=duration, sources=sources,
                                         licenses=licenses, facts_by_id=facts_by_id, sentence_facts=sentence_facts,
                                         hook_title=hook_title, topic=topic["topic"], cfg=cfg)
    storyboard.store_scenes(ctx, vid, scenes)
    pdir = ctx.ws.project_dir(base)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "storyboard.json").write_text(json.dumps({"scenes": scenes, "screen_time": storyboard.screen_time(scenes),
                                                      "narration": narration.sentences}, indent=2, default=list),
                                          encoding="utf-8")

    # render
    out = ctx.ws.render_path(base)
    info = render.render_video(scenes=scenes, sources_by_id={s["source_id"]: s for s in sources},
                               audio_mix=tracks["mix"], ass_path=ass_path, duration=duration, out_path=out,
                               work=ctx.ws.visuals_dir(base), cfg=cfg)
    costs.record("rendering", "local", units=duration / 60, unit_type="render_minutes",
                 usd=costs.render_cost(duration / 60), video_id=vid)
    size_gb = out.stat().st_size / 1e9
    costs.record("storage", "local", units=size_gb, unit_type="GB-month", usd=costs.storage_cost(size_gb), video_id=vid)
    _asset(ctx, vid, "render", out, duration=info.duration)

    # thumbnails for the 3 concepts
    md = video.get("metadata_json") or {}
    for n, concept in enumerate(md.get("thumbnail_concepts") or [], start=1):
        frame = None
        if concept["concept"] == "strongest_frame":
            # the payoff's footage (the reveal), away from the hook's title card
            footage = [s for s in scenes if s["visual_type"] == "footage" and s["section"] != "HOOK"]
            pick = next((s for s in footage if s["section"] == "PAYOFF"), footage[0] if footage else None)
            t = (pick["start_time"] + pick["end_time"]) / 2 if pick else duration / 2
            frame = ffmpeg.extract_frame(out, t, ctx.ws.visuals_dir(base) / f"thumb_frame_{n}.png")
        thumb = graphics.thumbnail(concept["text"], frame, ctx.ws.thumbnail_path(base, n).with_suffix(".jpg"))
        _asset(ctx, vid, "thumbnail", thumb, meta=concept)

    ctx.db.update("videos", vid, {"voice_id": voice_id, "render_path": str(out), "duration": info.duration,
                                  "width": info.width, "height": info.height, "fps": info.fps, "updated_at": now_iso()})
    return {"render": str(out), "duration": info.duration, "scenes": len(scenes),
            "screen_time": storyboard.screen_time(scenes), "caption_chunks": len(chunks),
            "mix_loudness": tracks["mix_loudness"]}


def stage_qc(ctx, video: dict) -> dict:
    from ..qc.checks import run_qc
    return run_qc(ctx, video["video_id"])


STAGE_FUNCS = {"research": stage_research, "sourcing": stage_sourcing, "scripting": stage_scripting,
               "editing": stage_editing, "qc": stage_qc}


# -- runner --------------------------------------------------------------------------------
def run_stages(ctx, video_id: str, stages: list[str]) -> dict:
    results: dict = {"video_id": video_id, "stages": {}}
    for stage in stages:
        video = ctx.db.require("videos", video_id)
        states.transition(ctx, video_id, STAGE_STATUS[stage], reason=f"stage {stage} started")
        try:
            results["stages"][stage] = STAGE_FUNCS[stage](ctx, video)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, then re-raised as a result
            tb = traceback.format_exc()
            ctx.db.record_error(stage=stage, exc=exc, video_id=video_id, topic_id=video["topic_id"], tb=tb)
            log.error("stage %s failed for %s: %s", stage, video_id, exc)
            states.transition(ctx, video_id, "FAILED", reason=f"{stage}: {exc}"[:500], extra={"failed_stage": stage})
            results.update({"status": "FAILED", "failed_stage": stage, "error": str(exc),
                            "hint": getattr(exc, "hint", None) if isinstance(exc, StudioError) else None})
            return results
        if stage == "qc":
            qc = results["stages"]["qc"]
            if qc["passed"]:
                states.transition(ctx, video_id, "REVIEW", reason="QC passed; ready for human review")
                from ..review.html import write_review_page
                results["review_page"] = str(write_review_page(ctx, video_id))
                results["status"] = "REVIEW"
            else:
                states.transition(ctx, video_id, "NEEDS_REVISION",
                                  reason="QC failed: " + ", ".join(c["name"] for c in qc["failed"]))
                results["status"] = "NEEDS_REVISION"
            return results
    results["status"] = ctx.db.require("videos", video_id)["status"]
    return results


def run_pipeline(ctx, *, topic: str | None = None, topic_id: str | None = None,
                 experiment_vars: dict | None = None) -> dict:
    if topic_id is None:
        if not topic:
            raise ValidationError("Give a topic or a topic_id")
        topic_id = get_or_create_topic(ctx, topic)["topic_id"]
    video = create_video(ctx, topic_id, experiment_vars=experiment_vars)
    attach_topic_costs(ctx, topic_id, video["video_id"])
    return run_stages(ctx, video["video_id"], STAGE_ORDER)


def resume(ctx, video_id: str, *, from_stage: str | None = None) -> dict:
    video = ctx.db.require("videos", video_id)
    start = from_stage or video.get("failed_stage")
    if start is None:
        mapping = {"NEEDS_REVISION": "scripting", "REVIEW": "editing", "APPROVED": "editing"}
        start = mapping.get(video["status"])
    if start not in STAGE_ORDER:
        raise ValidationError(f"Cannot resume {video_id} from status {video['status']}")
    return run_stages(ctx, video_id, STAGE_ORDER[STAGE_ORDER.index(start):])


def auto_research_topic(ctx) -> dict | None:
    """Pick the next topic for --auto-research: researched-ready topics first, never inventing trends."""
    from ..research.trends import discover_trends
    discover_trends(ctx)
    rows = ctx.db.query(
        "SELECT t.* FROM topics t WHERE t.channel_id = ? AND NOT EXISTS "
        "(SELECT 1 FROM videos v WHERE v.topic_id = t.topic_id) "
        "ORDER BY CASE t.research_status WHEN 'RESEARCHED' THEN 0 ELSE 1 END, "
        "COALESCE(t.trend_signal, 0) DESC, t.created_at", (ctx.cfg.channel_id,))
    return rows[0] if rows else None
