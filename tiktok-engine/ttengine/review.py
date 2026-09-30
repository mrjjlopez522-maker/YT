"""Human review (page + actions) and the per-video audit trail."""
from __future__ import annotations

import json
import os
from pathlib import Path

from studio.review import review as core_review
from studio.review.html import _e, _page
from studio.textutil import now_iso, new_id


def cost_of(ctx, video_id: str) -> dict:
    rows = ctx.db.query("SELECT category, provider, SUM(estimated_usd) AS usd FROM costs WHERE video_id = ? "
                        "GROUP BY category, provider", (video_id,))
    return {"total_usd": round(sum(r["usd"] for r in rows), 4),
            "lines": [{"category": r["category"], "provider": r["provider"], "usd": round(r["usd"], 4)} for r in rows]}


def audit(ctx, video_id: str) -> dict:
    """Answers: where did the information/footage come from, was it usable, what changed, what was added,
    what supports the claims, cost, approval, publication, performance."""
    db = ctx.db
    v = db.require("videos", video_id)
    script = db.get("scripts", v["script_id"]) if v.get("script_id") else {}
    claims = db.select("claims", {"script_id": v["script_id"]}) if v.get("script_id") else []
    research = db.select("research", {"topic_id": v["topic_id"]})
    scenes = db.select("scenes", {"video_id": video_id}, order_by="idx")
    used = sorted({s["visual_source"] for s in scenes if s["visual_source"]}
                  | {a["source_id"] for a in db.select("audio", {"video_id": video_id}) if a.get("source_id")})
    footage = []
    for sid in used:
        s = db.get("sources", sid)
        lic = (db.select("licenses", {"source_id": sid}) or [{}])[0]
        ev = lic.get("evidence_json") or {}
        footage.append({"source_id": sid, "title": s["title"], "platform": s["platform"], "creator": s["creator"],
                        "license": lic.get("license_type"), "verified": lic.get("verification_status"),
                        "confidence": lic.get("rights_confidence"), "evidence_file": lic.get("evidence_path"),
                        "generator": ev.get("generator"), "generator_params": ev.get("params"),
                        "used_in_scenes": [sc["idx"] for sc in scenes if sc["visual_source"] == sid]})
    third = [f for f in footage if f["platform"] != "generated"]
    original = [f for f in footage if f["platform"] == "generated"]
    approvals = db.select("approvals", {"video_id": video_id}, order_by="created_at")
    uploads = db.select("uploads", {"video_id": video_id}, order_by="created_at")
    snaps = db.select("analytics", {"video_id": video_id}, order_by="captured_at")
    return {
        "video_id": video_id, "status": v["status"], "generated_at": now_iso(),
        "1_information_sources": [{"title": r["title"], "url": r["url"], "reliability": r["reliability"],
                                   "provider": r["provider"], "retrieved_at": r["retrieved_at"]} for r in research],
        "2_footage_sources": footage,
        "3_footage_legally_usable": all(f["verified"] == "VERIFIED" for f in footage),
        "4_what_was_changed": [f"{f['title']}: reframed to 9:16, trimmed to scenes {f['used_in_scenes']}, original "
                               "narration and captions added, source audio not used" for f in third]
        or ["no third-party footage was used"],
        "5_original_material_added": {
            "narration": f"original script ({script.get('word_count')} words, writer {script.get('llm_provider')})",
            "visuals": [f"{f['generator']} {json.dumps(f['generator_params'])}" for f in original
                        if f["generator"] not in ("ambient_pad", "whoosh")],
            "music_sfx": [f["title"] for f in original if f["generator"] in ("ambient_pad", "whoosh")],
            "graphics_and_captions": "brand cards, series tag, end card, word-timed captions"},
        "6_claim_sources": [{"claim": c["claim"], "status": c["status"], "source": c["source"],
                             "url": c["source_url"]} for c in claims],
        "7_cost": cost_of(ctx, video_id),
        "8_approved": [{"decision": a["decision"], "by": a["reviewer"], "at": a["created_at"],
                        "public_allowed": bool(a["allow_public"])} for a in approvals] or "not yet reviewed",
        "9_published": [{"platform": u["platform"], "status": u["status"], "privacy": u["privacy_status"],
                         "publish_id": u.get("publish_id"), "at": u["created_at"]} for u in uploads] or "not published",
        "10_performance": [{k: s.get(k) for k in ("captured_at", "views", "likes", "comments", "shares", "saves",
                                                  "completion_rate", "avg_watch_time", "followers_gained")}
                           for s in snaps] or "no analytics yet",
    }


def write_page(ctx, video_id: str) -> Path:
    db = ctx.db
    v = db.require("videos", video_id)
    script = db.require("scripts", v["script_id"])
    md = v.get("metadata_json") or {}
    qc = v.get("qc_report_json") or {}
    a = audit(ctx, video_id)
    out = ctx.ws.export_dir(v["base_name"])
    out.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(v["render_path"], out) if v.get("render_path") else ""
    rows = "".join(f"<tr><td>{_e(c['name'])}</td><td class='{'ok' if c['passed'] else 'bad' if c['severity'] == 'blocking' else 'warn'}'>"
                   f"{'PASS' if c['passed'] else 'FAIL' if c['severity'] == 'blocking' else 'NOTE'}</td><td>{_e(c['details'])}</td></tr>"
                   for c in qc.get("checks", []))
    sections = "".join(f"<div class='sec'>{_e(s['name'])}</div>" + "".join(f"<p>{_e(x['text'])}</p>" for x in s["sentences"])
                       for s in script["sections_json"])
    caps = "".join(f"<li>{_e(c['caption'])}</li>" for c in md.get("captions", []))
    tags = "".join(f"<li>{_e(' '.join(t))}</li>" for t in md.get("hashtag_sets", []))
    prompts = "".join(f"<li>{_e(p['text'])}</li>" for p in md.get("comment_prompts", []))
    claims = "".join(f"<tr><td>{_e(c['claim'])}</td><td>{_e(c['status'])}</td><td>{_e(c['source'])}</td></tr>"
                     for c in a["6_claim_sources"])
    foot = "".join(f"<tr><td>{_e(f['title'])}</td><td>{_e(f['license'])} · {_e(f['verified'])} · {_e(f['confidence'])}</td>"
                   f"<td>{_e(f['generator'] or f['platform'])}</td></tr>" for f in a["2_footage_sources"])
    cost = a["7_cost"]
    risk = "".join(f"<li>{_e(r)}</li>" for r in qc.get("risk_flags", [])) or "<li>none</li>"
    vid = _e(video_id)
    body = f"""
<h1>{_e(md.get('selected_caption') or script['selected_hook'])}</h1>
<div class='muted'>{vid} · {_e(v['status'])} · format {_e(v.get('format_id'))} · series {_e(v.get('series_id'))} ·
QC <b class='{'ok' if qc.get('passed') else 'bad'}'>{'PASSED' if qc.get('passed') else 'FAILED'}</b> · cost ${cost['total_usd']:.4f}</div>
<div class='grid' style='margin-top:18px'>
 <div><video controls preload='metadata' src='{_e(rel)}'></video></div>
 <div>
  <div class='card'><b>Decide</b> — manual approval required; nothing is posted from this page
<pre>python main.py review --video {vid} --approve [--allow-public]
python main.py review --video {vid} --reject --notes "why"
python main.py review --video {vid} --edit-caption "..."
python main.py review --video {vid} --render-again
python main.py review --video {vid} --schedule 2026-10-02T18:00:00Z --allow-public
python main.py publish --video {vid} --privacy SELF_ONLY   # choose privacy explicitly</pre></div>
  <h2>Risk flags</h2><div class='card'><ul>{risk}</ul></div>
  <h2>Post text</h2><div class='card'><pre>{_e(v.get('caption'))}</pre></div>
  <h2>Caption options</h2><div class='card'><ol>{caps}</ol></div>
  <h2>Hashtag sets</h2><div class='card'><ul>{tags}</ul></div>
  <h2>Comment prompts (optional, never auto-posted)</h2><div class='card'><ul>{prompts}</ul></div>
 </div>
</div>
<h2>Script <span class='muted'>({script['word_count']} words · hook type {_e((script['blueprint_json'] or {}).get('hook_type'))})</span></h2>
<div class='card'>{sections}</div>
<h2>Description</h2><div class='card'><pre>{_e(v.get('selected_description'))}</pre></div>
<h2>Fact sources</h2><div class='card'><table><tr><th>claim</th><th>status</th><th>source</th></tr>{claims}</table></div>
<h2>Sources &amp; licenses</h2><div class='card'><table><tr><th>source</th><th>license</th><th>origin</th></tr>{foot}</table></div>
<h2>Cost</h2><div class='card'><pre>{_e(json.dumps(cost, indent=1))}</pre></div>
<h2>QC</h2><div class='card'><table>{rows}</table></div>
<h2>Audit trail</h2><div class='card'><pre>{_e(json.dumps(a, indent=1, default=str))}</pre></div>
"""
    path = out / "review.html"
    path.write_text(_page(f"Review {video_id}", body), encoding="utf-8")
    (out / "audit.json").write_text(json.dumps(a, indent=2, default=str), encoding="utf-8")
    db.delete("assets", {"video_id": video_id, "kind": "review_page"})
    db.insert("assets", {"asset_id": new_id("ast"), "video_id": video_id, "kind": "review_page", "path": str(path),
                         "created_at": now_iso()})
    return path


# actions: approval, rejection and scheduling are the core studio actions (shared rules)
approve = core_review.approve
reject = core_review.reject
schedule = core_review.schedule
latest_approval = core_review.latest_approval


def edit_caption(ctx, video_id: str, reviewer: str, caption: str) -> None:
    from .qc import run
    from .script import bait_issues, load_style
    from studio.errors import ValidationError
    if bait_issues([caption], load_style(ctx)):
        raise ValidationError("Caption contains engagement bait")
    v = ctx.db.require("videos", video_id)
    md = dict(v.get("metadata_json") or {})
    post = caption + (f"\n{md['disclosure']}" if md.get("disclosure") else "")
    ctx.db.update("videos", video_id, {"caption": post, "selected_title": caption, "updated_at": now_iso()})
    core_review._record(ctx, video_id, "EDIT", reviewer, notes=f"caption -> {caption}")
    report = run(ctx, video_id)
    from . import states
    if v["status"] == "APPROVED":
        states.transition(ctx, video_id, "REVIEW", reason="caption edited after approval")
    if not report["passed"]:
        states.transition(ctx, video_id, "NEEDS_REVISION", reason="QC failed after caption edit")


def render_again(ctx, video_id: str, reviewer: str, notes: str | None = None) -> dict:
    from .pipeline import run_stages
    core_review._record(ctx, video_id, "RENDER_AGAIN", reviewer, notes=notes)
    return run_stages(ctx, video_id, ["edit", "qc"])
