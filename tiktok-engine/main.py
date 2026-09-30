#!/usr/bin/env python3
"""TikTok Engine command line.

  python main.py init                          workspace folders + database, safety switches
  python main.py niches                        niche tradeoffs (no single "best" score)
  python main.py trends [--discover]           trends you observed + measured providers
  python main.py formats [--analyze | --update-stats]
  python main.py ideas --topic "..." [--topic ...] | --from-trends | --list | --develop ID | --produce ID
  python main.py research --topic "..."        research + research packet
  python main.py sources --topic "..."         licensed-source discovery (rights-gated)
  python main.py verify [--approve ID | --reject ID ...]   human rights verification
  python main.py script --topic "..." [--format ID]        script preview (hook types, sections, fact check)
  python main.py voice [--list | --download | --calibrate | --video ID]
  python main.py storyboard --video ID
  python main.py render --video ID            storyboard + visuals + sound + captions + render, then QC
  python main.py qc --video ID
  python main.py review [--video ID] [--approve | --reject | --edit-caption T | --render-again | --schedule WHEN]
  python main.py auth [--code CODE --state STATE]           TikTok OAuth (PKCE); never asks for a password
  python main.py publish --video ID [--privacy SELF_ONLY] [--live]
  python main.py analytics [--record ID ... | --import-csv F | --fetch | --compare ATTR]
  python main.py experiments {create,list,assign,analyze}
  python main.py calendar | costs | audit --video ID | status
  python main.py pipeline --topic "..." [--format ID] [--series ID] [--mode M]
  python main.py pipeline --trend-mode
  python main.py pipeline --resume VIDEO_ID [--from-stage STAGE]
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttengine  # noqa: E402,F401  (puts the core `studio` library on sys.path)


def _ctx(args):
    from ttengine.context import TikTokContext
    return TikTokContext.create(args.home)


def _reviewer(args) -> str:
    return getattr(args, "reviewer", None) or os.environ.get("STUDIO_REVIEWER") or getpass.getuser()


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _topic_id(ctx, topic: str) -> str:
    from studio.research.topic_research import get_or_create_topic
    return get_or_create_topic(ctx, topic)["topic_id"]


def _stages(ctx, video_id: str, stages: list[str]) -> dict:
    from ttengine.pipeline import run_stages
    res = run_stages(ctx, video_id, stages)
    _print({k: v for k, v in res.items() if k != "stages"})
    return res


# -- commands -----------------------------------------------------------------------------
def cmd_init(args):
    ctx = _ctx(args)
    _print({"workspace": str(ctx.ws.home), "database": str(ctx.db.path), "DRY_RUN": ctx.cfg.dry_run,
            "AUTO_PUBLISH": ctx.cfg.auto_publish, "MANUAL_APPROVAL_REQUIRED": ctx.cfg.manual_approval,
            "voice": ctx.cfg.get("voice.provider"), "formats": sorted(ctx.formats), "series": sorted(ctx.series)})


def cmd_niches(args):
    from studio.research.niche import build_report
    ctx = _ctx(args)
    rep = build_report(ctx, niches=args.niches.split(",") if args.niches else None)
    print(Path(rep["markdown_path"]).read_text())


def cmd_trends(args):
    from ttengine import trends
    ctx = _ctx(args)
    if args.discover:
        out = trends.discover(ctx)
        if out["provider_errors"]:
            _print({"provider_errors": out["provider_errors"]})
    trends.expire(ctx)
    rows = trends.active(ctx)
    if not rows:
        print("No active trends. Record what you observe in config/trend_observations.yaml, then --discover.")
    for t in rows:
        sig = "not measured" if t["trend_signal"] is None else f"{t['trend_signal']:.2f}"
        print(f"{t['trend_id']}  {t['topic']}  [{t['trend_type']}, {t['trend_source']}]  signal {sig}  "
              f"detected {t['date_detected']}  expires {t['expiration_estimate']}")
        if t.get("potential_angle"):
            print(f"      angle: {t['potential_angle']}")


def cmd_formats(args):
    from ttengine import formats
    ctx = _ctx(args)
    if args.analyze:
        _print(formats.analyze_observations(ctx))
    elif args.update_stats:
        _print(formats.update_stats(ctx))
    else:
        print(formats.describe(ctx))


def cmd_ideas(args):
    from ttengine import ideas
    ctx = _ctx(args)
    if args.develop:
        pk = ideas.develop(ctx, args.develop)
        _print({"complete": pk["complete"], "checks": pk["checks"], "warnings": pk.get("warnings")})
        return
    if args.produce:
        _print(ideas.produce(ctx, args.produce))
        return
    if args.list:
        for i in ctx.db.select("ideas", order_by="created_at"):
            print(f"{i['status']:<11} {i['idea_id']}  [{i['format_id']}/{i['hook_type']}] {i['topic']}: {i['hook']}"
                  + (f"  -- {i['elimination_reason']}" if i.get("elimination_reason") else ""))
        return
    if args.from_trends:
        from ttengine import trends
        by_topic = {}
        for t in trends.active(ctx):
            by_topic.setdefault(t["topic_id"], t)
        topics = [ctx.db.require("topics", tid) for tid in by_topic]
        batch = ideas.generate_batch(ctx, topics, n=args.n, mode=None, trends_by_topic=by_topic)
    elif args.topic:
        from studio.research.topic_research import research_topic
        topics = []
        for name in args.topic:
            tid = _topic_id(ctx, name)
            research_topic(ctx, tid)
            topics.append(ctx.db.require("topics", tid))
        batch = ideas.generate_batch(ctx, topics, n=args.n, mode=args.mode, series_id=args.series)
    else:
        raise SystemExit("ideas needs --topic, --from-trends, --list, --develop or --produce")
    print(f"batch {batch['batch_id']}: {batch['generated']} ideas, {batch['eliminated']} eliminated "
          f"({batch['disclaimer']})")
    for i in batch["shortlisted"]:
        print(f"  {i['order']:.3f}  {i['idea_id']}  [{i['format_id']}/{i['hook_type']}] {i['hook']}")
    print("see all, with elimination reasons: python main.py ideas --list")


def cmd_research(args):
    from studio.research.topic_research import research_topic
    from ttengine import packet
    ctx = _ctx(args)
    tid = _topic_id(ctx, args.topic)
    res = research_topic(ctx, tid)
    pk = packet.build(ctx, tid)
    _print({"facts": res["facts"], "provider_errors": res["provider_errors"], "packet_complete": pk["complete"],
            "checks": pk["checks"], "warnings": pk.get("warnings"), "packet": pk.get("path")})


def cmd_sources(args):
    from studio.sources.discovery import discover
    ctx = _ctx(args)
    tid = _topic_id(ctx, args.topic)
    rep = discover(ctx, queries=[args.query or args.topic], topic_id=tid)
    _print({"approved": rep.approved, "rejected": [{"source_id": s, "reasons": r} for s, r in rep.rejected],
            "provider_errors": rep.provider_errors,
            "note": "Rights unclear -> rejected. Original generated visuals are registered at render time (CC0, ours)."})


def cmd_verify(args):
    from studio.sources.discovery import human_verify
    ctx = _ctx(args)
    if args.approve or args.reject:
        human_verify(ctx, args.approve or args.reject, reviewer=_reviewer(args), approve=bool(args.approve),
                     license_type=args.license, permission_reference=args.reference, permission_date=args.date,
                     notes=args.notes)
    for r in ctx.db.query("SELECT source_id, status, license_type, rights_confidence, title, creator "
                          "FROM source_rights ORDER BY date_found"):
        print(f"{r['source_id']}  {r['status']:<9} {str(r['license_type']):<12} conf={r['rights_confidence']}  "
              f"{r['title']} — {r['creator']}")
    for s in ctx.db.select("sources", {"status": "REJECTED"}):
        print(f"  rejected {s['source_id']}: {s['rejection_reason']}")


def cmd_script(args):
    from ttengine import script, voice
    ctx = _ctx(args)
    tid = _topic_id(ctx, args.topic)
    ctx.cfg.data["voice"]["words_per_minute"] = voice.effective_wpm(ctx)
    s = script.generate(ctx, tid, format_id=args.format, target_duration=args.duration)
    bp = s["blueprint_json"]
    print(f"script {s['script_id']}  format {bp['format_id']}  hook type {bp['hook_type']}  ~{s['est_duration']}s  "
          f"fact check {s['factcheck_status']}  promise kept: {bp['promise']['kept']}")
    for sec in s["sections_json"]:
        print(f"[{sec['name']}]")
        for x in sec["sentences"]:
            print(f"  {x['text']}")
    print(f"saved: {s['path']}")


def cmd_voice(args):
    from ttengine import voice
    ctx = _ctx(args)
    models = ctx.cfg.path(ctx.cfg.get("voice.models_dir"))
    if args.download:
        _print({"downloaded": [str(p) for p in voice.download_models(models)], "license": voice.MODEL_LICENSE})
    elif args.list:
        print("\n".join(voice.KokoroProvider(models).voices()))
    elif args.calibrate:
        ctx.db.conn.execute("DELETE FROM voices WHERE voice_id LIKE 'calibration_%'")
        print(f"measured {voice.effective_wpm(ctx)} words per minute "
              f"({ctx.cfg.get('voice.provider')} {ctx.cfg.get('voice.voice_name')} speed {ctx.cfg.get('voice.speed')})")
    elif args.video:
        _stages(ctx, args.video, ["voice"])
    else:
        raise SystemExit("voice needs --list, --download, --calibrate or --video")


def cmd_storyboard(args):
    ctx = _ctx(args)
    v = ctx.db.require("videos", args.video)
    path = ctx.ws.dir("storyboards") / f"{v['base_name']}.json"
    if not path.is_file():
        raise SystemExit(f"No storyboard yet; build it with: python main.py render --video {args.video}")
    data = json.loads(path.read_text())
    for s in data["scenes"]:
        visual = f"{s['generator']} (original, generated)" if s.get("generator") else s["visual_source"]
        print(f"{s['scene_id']}  {s['start_time']:6.2f}-{s['end_time']:6.2f}  [{s['section']}]  visual: {visual}")
        if s.get("narration"):
            print(f"        narration: {s['narration']}")
        print(f"        caption: {s.get('caption') or ''} | transition {s.get('transition')} | effect "
              f"{s.get('effect')} | sfx {s.get('sound_effect') or '-'}")
    _print(data["stats"])


def cmd_render(args):
    ctx = _ctx(args)
    _stages(ctx, args.video, ["edit", "qc"])


def cmd_qc(args):
    from ttengine import qc, states
    ctx = _ctx(args)
    v = ctx.db.require("videos", args.video)
    if v["status"] == "EDIT":
        rep = _stages(ctx, args.video, ["qc"])["stages"].get("qc") or {}
    else:
        rep = qc.run(ctx, args.video)
        if not rep["passed"] and v["status"] == "REVIEW":
            states.transition(ctx, args.video, "NEEDS_REVISION", reason="QC re-check failed")
    for c in rep.get("checks", []):
        print(f"{'PASS' if c['passed'] else 'FAIL' if c['severity'] == 'blocking' else 'NOTE'}  "
              f"{c['name']}: {c['details']}")
    print(f"QC {'PASSED' if rep.get('passed') else 'FAILED'}; status {ctx.db.require('videos', args.video)['status']}")


def cmd_review(args):
    from studio.review.review import pending, summary
    from ttengine import review
    ctx = _ctx(args)
    if not args.video:
        rows = pending(ctx)
        print("Nothing waiting for review." if not rows else "\n".join(
            f"{v['video_id']}  {v.get('selected_title')}" for v in rows))
        return
    who = _reviewer(args)
    if args.approve:
        review.approve(ctx, args.video, who, allow_public=args.allow_public, notes=args.notes)
        print(f"APPROVED by {who}" + (" (public posting allowed)" if args.allow_public else " (SELF_ONLY/draft only)"))
        print(f"Publishing is a separate, explicit step: python main.py publish --video {args.video} --privacy ...")
    elif args.reject:
        review.reject(ctx, args.video, who, notes=args.notes)
        print("REJECTED")
    elif args.edit_caption:
        review.edit_caption(ctx, args.video, who, args.edit_caption)
        print(f"caption edited; status {ctx.db.require('videos', args.video)['status']}")
    elif args.render_again:
        res = review.render_again(ctx, args.video, who, notes=args.notes)
        _print({k: v for k, v in res.items() if k != "stages"})
    elif args.schedule:
        review.schedule(ctx, args.video, who, args.schedule, allow_public=args.allow_public)
        print(f"SCHEDULED for {args.schedule}. Nothing posts by itself: run publish at that time "
              "(TikTok's API has no scheduled-post parameter).")
    else:
        print(summary(ctx, args.video))
        print(f"\nreview page: {review.write_page(ctx, args.video)}")


def cmd_auth(args):
    import requests
    import secrets as pysecrets
    from ttengine import publish
    ctx = _ctx(args)
    key, secret = ctx.cfg.secret("TIKTOK_CLIENT_KEY"), ctx.cfg.secret("TIKTOK_CLIENT_SECRET")
    redirect = os.environ.get("TIKTOK_REDIRECT_URI")
    if not (key and secret and redirect):
        raise SystemExit("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in .env "
                         "(from your TikTok for Developers app)")
    pending_path = publish.token_path(ctx).with_name("tiktok_oauth_pending.json")
    if not args.code:
        verifier, challenge = publish.pkce_pair()
        state = pysecrets.token_urlsafe(16)
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(json.dumps({"verifier": verifier, "state": state}))
        os.chmod(pending_path, 0o600)
        print("Open this URL, sign in on TikTok's own page and approve the app:\n")
        print(publish.authorize_url(key, redirect, state, challenge))
        print("\nThen run: python main.py auth --code <code from the redirect> --state <state from the redirect>")
        return
    pend = json.loads(pending_path.read_text()) if pending_path.is_file() else {}
    if not pend or args.state != pend.get("state"):
        raise SystemExit("State mismatch or no pending authorisation; start again with: python main.py auth")
    token = publish.exchange_code(requests.Session(), client_key=key, client_secret=secret, code=args.code,
                                  redirect_uri=redirect, verifier=pend["verifier"])
    publish.save_token(ctx, token)
    pending_path.unlink()
    print(f"Authorised (scopes: {token.get('scope')}). Token saved with owner-only permissions; never commit it.")


def cmd_publish(args):
    from ttengine import publish
    ctx = _ctx(args)
    api = None
    if args.live:
        import requests
        path = publish.token_path(ctx)
        if not path.is_file():
            raise SystemExit("Not authorised yet: python main.py auth")
        api = publish.TikTokAPI(requests.Session(), json.loads(path.read_text())["access_token"])
    res = publish.publish(ctx, args.video, privacy_level=args.privacy, live=args.live, api=api,
                          disable_comment=args.disable_comment, disable_duet=args.disable_duet,
                          disable_stitch=args.disable_stitch)
    _print({k: res.get(k) for k in ("upload_id", "status", "privacy_status", "publish_id", "dry_run")})
    if res["status"] == "DRY_RUN":
        print("DRY RUN: nothing was sent. The exact API plan is in exports/<video>/tiktok_publish_plan.json")


def _curve(path: str) -> list:
    p = Path(path)
    if p.suffix == ".json":
        return [tuple(x) for x in json.loads(p.read_text())]
    import csv
    with open(p, newline="") as fh:
        return [(float(r[0]), float(r[1])) for r in csv.reader(fh) if r and r[0].replace(".", "", 1).isdigit()]


def cmd_analytics(args):
    from ttengine import analytics
    ctx = _ctx(args)
    if args.record:
        metrics = {k: getattr(args, k) for k in ("views", "likes", "comments", "shares", "saves", "followers_gained",
                                                  "avg_watch_time", "completion_rate") if getattr(args, k) is not None}
        sid = analytics.snapshot(ctx, args.record, source="manual",
                                 retention_curve=_curve(args.retention) if args.retention else None, **metrics)
        _print({"snapshot_id": sid, "retention_buckets": ctx.db.get("analytics", sid)["retention_buckets_json"]})
    elif args.import_csv:
        _print({"snapshots": analytics.import_studio_csv(ctx, args.import_csv)})
    elif args.fetch:
        import requests
        from ttengine.publish import token_path
        if not token_path(ctx).is_file():
            raise SystemExit("Not authorised yet: python main.py auth")
        token = json.loads(token_path(ctx).read_text())["access_token"]
        _print({"snapshots": analytics.fetch_display_api(ctx, requests.Session(), token)})
    elif args.compare:
        _print(analytics.compare(ctx, args.compare))
    else:
        _print(analytics.latest_by_video(ctx))


def cmd_experiments(args):
    from ttengine import experiments as ex
    ctx = _ctx(args)
    if args.action == "create":
        _print({"experiment_id": ex.create(ctx, name=args.name, variable=args.variable,
                                           variants=args.variants.split(","), hypothesis=args.hypothesis,
                                           metric=args.metric)})
    elif args.action == "assign":
        variant = args.variant or ex.next_variant(ctx, args.experiment)
        ex.assign(ctx, args.experiment, args.video, variant)
        print(f"{args.video} -> {variant}")
    elif args.action == "analyze":
        _print(ex.analyze(ctx, args.experiment))
    else:
        _print(ex.describe(ctx))


def cmd_calendar(args):
    from ttengine import content_calendar
    _print(content_calendar.overview(_ctx(args)))


def cmd_costs(args):
    from ttengine import finance
    ctx = _ctx(args)
    if args.add_revenue is not None:
        finance.add_revenue(ctx, amount_usd=args.add_revenue, category=args.category, period_start=args.start,
                            period_end=args.end, video_id=args.video, notes=args.notes)
    _print(finance.summary(ctx))


def cmd_audit(args):
    from ttengine.review import audit
    _print(audit(_ctx(args), args.video))


def cmd_status(args):
    ctx = _ctx(args)
    counts = ctx.db.query("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
    errors = ctx.db.query("SELECT stage, error_type, message, created_at FROM errors WHERE resolved = 0 "
                          "ORDER BY created_at DESC LIMIT 5")
    _print({"videos": {c["status"]: c["n"] for c in counts}, "recent_errors": errors, "DRY_RUN": ctx.cfg.dry_run,
            "AUTO_PUBLISH": ctx.cfg.auto_publish, "MANUAL_APPROVAL_REQUIRED": ctx.cfg.manual_approval,
            "voice": ctx.cfg.get("voice.provider"), "writer": ctx.cfg.get("content.llm_provider")})


def cmd_pipeline(args):
    from ttengine import pipeline
    ctx = _ctx(args)
    if args.resume:
        res = pipeline.resume(ctx, args.resume, from_stage=args.from_stage)
    elif args.trend_mode:
        from ttengine.ideas import trend_mode
        res = trend_mode(ctx)
    elif args.topic:
        res = pipeline.run(ctx, topic=args.topic, format_id=args.format, series_id=args.series, mode=args.mode)
    else:
        raise SystemExit("pipeline needs --topic, --trend-mode or --resume")
    _print(res)
    for v in ([res] if "video_id" in res else res.get("produced", [])):
        if v.get("status") == "REVIEW":
            print(f"\nReady for review: {v['review_page']}\n  python main.py review --video {v['video_id']}")


# -- parser ----------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    from ttengine.context import MODES
    from ttengine.pipeline import STAGES
    from ttengine.publish import PRIVACY_LEVELS
    p = argparse.ArgumentParser(prog="main.py", description="TikTok Engine")
    p.add_argument("--home", help="workspace root (default: TIKTOK_HOME or this directory)")
    p.add_argument("--debug", action="store_true", help="show tracebacks")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    n = sub.add_parser("niches")
    n.add_argument("--niches", help="comma-separated subset of config/niches.yaml")
    n.set_defaults(func=cmd_niches)
    t = sub.add_parser("trends")
    t.add_argument("--discover", action="store_true", help="run the configured trend providers")
    t.set_defaults(func=cmd_trends)
    f = sub.add_parser("formats")
    f.add_argument("--analyze", action="store_true", help="summarise recorded format observations")
    f.add_argument("--update-stats", action="store_true", help="per-template stats from our own analytics")
    f.set_defaults(func=cmd_formats)
    i = sub.add_parser("ideas")
    i.add_argument("--topic", action="append")
    i.add_argument("--from-trends", action="store_true")
    i.add_argument("--n", type=int)
    i.add_argument("--mode", choices=MODES, default="EVERGREEN")
    i.add_argument("--series")
    i.add_argument("--list", action="store_true")
    i.add_argument("--develop", metavar="IDEA_ID")
    i.add_argument("--produce", metavar="IDEA_ID")
    i.set_defaults(func=cmd_ideas)
    r = sub.add_parser("research")
    r.add_argument("--topic", required=True)
    r.set_defaults(func=cmd_research)
    s = sub.add_parser("sources")
    s.add_argument("--topic", required=True)
    s.add_argument("--query")
    s.set_defaults(func=cmd_sources)
    v = sub.add_parser("verify")
    v.add_argument("--approve", metavar="SOURCE_ID")
    v.add_argument("--reject", metavar="SOURCE_ID")
    v.add_argument("--license")
    v.add_argument("--reference")
    v.add_argument("--date")
    v.add_argument("--notes")
    v.add_argument("--reviewer")
    v.set_defaults(func=cmd_verify)
    sc = sub.add_parser("script")
    sc.add_argument("--topic", required=True)
    sc.add_argument("--format", default="unexpected_fact_reveal")
    sc.add_argument("--duration", type=int, help="target seconds (15, 20, 30, 45, 60, 90 or longer)")
    sc.set_defaults(func=cmd_script)
    vo = sub.add_parser("voice")
    vo.add_argument("--list", action="store_true")
    vo.add_argument("--download", action="store_true", help="fetch the Kokoro model files (Apache-2.0)")
    vo.add_argument("--calibrate", action="store_true", help="re-measure words per minute")
    vo.add_argument("--video")
    vo.set_defaults(func=cmd_voice)
    sb = sub.add_parser("storyboard")
    sb.add_argument("--video", required=True)
    sb.set_defaults(func=cmd_storyboard)
    rd = sub.add_parser("render")
    rd.add_argument("--video", required=True)
    rd.set_defaults(func=cmd_render)
    q = sub.add_parser("qc")
    q.add_argument("--video", required=True)
    q.set_defaults(func=cmd_qc)
    rv = sub.add_parser("review")
    rv.add_argument("--video")
    rv.add_argument("--reviewer")
    act = rv.add_mutually_exclusive_group()
    act.add_argument("--approve", action="store_true")
    act.add_argument("--reject", action="store_true")
    act.add_argument("--edit-caption")
    act.add_argument("--render-again", action="store_true")
    act.add_argument("--schedule", metavar="ISO_TIME")
    rv.add_argument("--allow-public", action="store_true", help="explicitly allow public posting")
    rv.add_argument("--notes")
    rv.set_defaults(func=cmd_review)
    au = sub.add_parser("auth")
    au.add_argument("--code")
    au.add_argument("--state")
    au.set_defaults(func=cmd_auth)
    pb = sub.add_parser("publish")
    pb.add_argument("--video", required=True)
    pb.add_argument("--privacy", choices=PRIVACY_LEVELS, help="required for direct posts; no default")
    pb.add_argument("--live", action="store_true", help="actually send (also requires DRY_RUN=false)")
    pb.add_argument("--disable-comment", action="store_true")
    pb.add_argument("--disable-duet", action="store_true")
    pb.add_argument("--disable-stitch", action="store_true")
    pb.set_defaults(func=cmd_publish)
    a = sub.add_parser("analytics")
    a.add_argument("--record", metavar="VIDEO_ID")
    for fld in ("views", "likes", "comments", "shares", "saves", "followers_gained"):
        a.add_argument(f"--{fld.replace('_', '-')}", dest=fld, type=int)
    a.add_argument("--avg-watch-time", dest="avg_watch_time", type=float, help="seconds")
    a.add_argument("--completion-rate", dest="completion_rate", type=float, help="share 0..1")
    a.add_argument("--retention", help="CSV or JSON of (second, share still watching) points")
    a.add_argument("--import-csv")
    a.add_argument("--fetch", action="store_true", help="Display API counts for published videos")
    a.add_argument("--compare", metavar="ATTR", help="hook_type | format_id | length | series_id | voice_id")
    a.set_defaults(func=cmd_analytics)
    e = sub.add_parser("experiments")
    e.add_argument("action", choices=["create", "list", "assign", "analyze"])
    e.add_argument("--name")
    e.add_argument("--variable")
    e.add_argument("--variants")
    e.add_argument("--hypothesis")
    e.add_argument("--metric", default="completion_rate")
    e.add_argument("--experiment")
    e.add_argument("--video")
    e.add_argument("--variant")
    e.set_defaults(func=cmd_experiments)
    sub.add_parser("calendar").set_defaults(func=cmd_calendar)
    c = sub.add_parser("costs")
    c.add_argument("--add-revenue", type=float, help="record revenue you actually received (USD)")
    c.add_argument("--category", default="other")
    c.add_argument("--start")
    c.add_argument("--end")
    c.add_argument("--video")
    c.add_argument("--notes")
    c.set_defaults(func=cmd_costs)
    ad = sub.add_parser("audit")
    ad.add_argument("--video", required=True)
    ad.set_defaults(func=cmd_audit)
    sub.add_parser("status").set_defaults(func=cmd_status)
    pl = sub.add_parser("pipeline")
    pl.add_argument("--topic")
    pl.add_argument("--trend-mode", action="store_true")
    pl.add_argument("--format")
    pl.add_argument("--series")
    pl.add_argument("--mode", choices=MODES, default="EVERGREEN")
    pl.add_argument("--resume", metavar="VIDEO_ID")
    pl.add_argument("--from-stage", choices=STAGES)
    pl.set_defaults(func=cmd_pipeline)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from studio.errors import StudioError
    try:
        args.func(args)
    except StudioError as exc:
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        hint = getattr(exc, "hint", None)
        if hint:
            print(f"hint: {hint}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
