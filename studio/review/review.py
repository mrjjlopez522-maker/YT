"""Human approval: APPROVE / REJECT / EDIT / RENDER_AGAIN / SCHEDULE.

Manual approval is the default and cannot be skipped for anything public.
"""
from __future__ import annotations

import datetime as dt
import json

import yaml

from ..content import factcheck
from ..content import style as style_mod
from ..content.metadata import load_style
from ..errors import ApprovalRequiredError, ValidationError
from ..research.topic_research import load_facts
from ..textutil import new_id, now_iso, word_count
from ..pipeline import states

DECISIONS = ("APPROVE", "REJECT", "EDIT", "RENDER_AGAIN", "SCHEDULE")


def pending(ctx) -> list[dict]:
    return ctx.db.select("videos", {"status": "REVIEW"}, order_by="created_at")


def summary(ctx, video_id: str) -> str:
    v = ctx.db.require("videos", video_id)
    script = ctx.db.get("scripts", v["script_id"]) if v.get("script_id") else {}
    claims = ctx.db.select("claims", {"script_id": v["script_id"]}) if v.get("script_id") else []
    qc = v.get("qc_report_json") or {}
    rights = ctx.db.query("SELECT * FROM source_rights WHERE source_id IN "
                          "(SELECT visual_source FROM scenes WHERE video_id = ?)", (video_id,))
    lines = [f"VIDEO      {video_id}  [{v['status']}]", f"PREVIEW    {v.get('render_path')}",
             f"TITLE      {v.get('selected_title')}", "", "DESCRIPTION", v.get("selected_description") or "", "",
             "SCRIPT"]
    for sec in script.get("sections_json") or []:
        lines.append(f"  [{sec['name']}]")
        lines += [f"    {x['text']}" for x in sec["sentences"]]
    lines += ["", "SOURCES / LICENSES"]
    lines += [f"  {r['source_id']}  {r['license_type']}  conf={r['rights_confidence']}  {r['title']} — {r['creator']}"
              for r in rights] or ["  (original graphics only)"]
    lines += ["", "FACT SOURCES"]
    lines += [f"  [{c['status']}] {c['claim'][:90]}  <- {c.get('source_url') or c.get('source')}" for c in claims]
    lines += ["", f"QC: {'PASSED' if qc.get('passed') else 'FAILED'}"]
    lines += [f"  FAIL {c['name']}: {c['details']}" for c in qc.get("failed", [])]
    lines += ["", "RISK FLAGS"] + [f"  - {r}" for r in qc.get("risk_flags", [])]
    return "\n".join(lines)


def _record(ctx, video_id, decision, reviewer, *, notes=None, allow_public=False, scheduled_for=None) -> str:
    aid = new_id("apr")
    ctx.db.insert("approvals", {"approval_id": aid, "video_id": video_id, "decision": decision, "reviewer": reviewer,
                                "allow_public": int(bool(allow_public)), "scheduled_for": scheduled_for,
                                "notes": notes, "created_at": now_iso()})
    return aid


def approve(ctx, video_id: str, reviewer: str, *, allow_public: bool = False, notes: str | None = None) -> str:
    v = ctx.db.require("videos", video_id)
    if v["status"] != "REVIEW":
        raise ApprovalRequiredError(f"{video_id} is {v['status']}; only videos in REVIEW can be approved")
    if v.get("qc_status") != "PASSED":
        raise ApprovalRequiredError("QC has not passed for this video")
    aid = _record(ctx, video_id, "APPROVE", reviewer, notes=notes, allow_public=allow_public)
    states.transition(ctx, video_id, "APPROVED", reason=f"approved by {reviewer}" + (" (public allowed)" if allow_public else ""))
    return aid


def reject(ctx, video_id: str, reviewer: str, *, notes: str | None = None) -> str:
    aid = _record(ctx, video_id, "REJECT", reviewer, notes=notes)
    states.transition(ctx, video_id, "REJECTED", reason=f"rejected by {reviewer}: {notes or ''}")
    return aid


def schedule(ctx, video_id: str, reviewer: str, when: str, *, allow_public: bool) -> str:
    """Scheduling means the video goes public at `when`, so it needs explicit public approval."""
    if not allow_public:
        raise ApprovalRequiredError("Scheduling publishes the video publicly; pass --allow-public to confirm")
    try:
        at = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Invalid schedule time {when!r}; use ISO 8601, e.g. 2026-10-02T15:00:00Z") from exc
    if at.tzinfo is None:
        raise ValidationError("Schedule time needs a timezone (e.g. ...Z)")
    if at <= dt.datetime.now(dt.timezone.utc):
        raise ValidationError("Schedule time must be in the future")
    v = ctx.db.require("videos", video_id)
    if v["status"] == "REVIEW":
        approve(ctx, video_id, reviewer, allow_public=True, notes=f"approved for scheduled release at {when}")
    elif v["status"] != "APPROVED":
        raise ApprovalRequiredError(f"{video_id} is {v['status']}; approve it first")
    aid = _record(ctx, video_id, "SCHEDULE", reviewer, allow_public=True, scheduled_for=at.isoformat())
    states.transition(ctx, video_id, "SCHEDULED", reason=f"scheduled for {at.isoformat()} by {reviewer}")
    return aid


def edit_metadata(ctx, video_id: str, reviewer: str, *, title: str | None = None, description: str | None = None) -> str:
    v = ctx.db.require("videos", video_id)
    changes = {}
    style_cfg = load_style(ctx)
    if title:
        issues = style_mod.title_issues(title, style_cfg)
        if issues or len(title) > 100:
            raise ValidationError(f"Title rejected: {issues or 'longer than 100 characters'}")
        changes["selected_title"] = title
    if description:
        if len(description) > 5000:
            raise ValidationError("Description exceeds YouTube's 5000-character limit")
        changes["selected_description"] = description
    if not changes:
        raise ValidationError("Nothing to edit")
    changes["updated_at"] = now_iso()
    ctx.db.update("videos", video_id, changes)
    aid = _record(ctx, video_id, "EDIT", reviewer, notes=json.dumps({k: v for k, v in changes.items() if k != "updated_at"}))
    # an edited title/description must pass QC again before approval
    if v["status"] in ("REVIEW", "APPROVED"):
        from ..qc.checks import run_qc
        report = run_qc(ctx, video_id)
        if v["status"] == "APPROVED":
            states.transition(ctx, video_id, "REVIEW", reason="metadata edited after approval; re-approval required")
        if not report["passed"]:
            states.transition(ctx, video_id, "NEEDS_REVISION", reason="QC failed after edit")
    return aid


def edit_script(ctx, video_id: str, reviewer: str, sections_yaml: str) -> dict:
    """Replace the script with human-edited sections, re-fact-check, and re-render + re-QC."""
    v = ctx.db.require("videos", video_id)
    old = ctx.db.require("scripts", v["script_id"])
    data = yaml.safe_load(sections_yaml)
    sections = data.get("sections") if isinstance(data, dict) else data
    if not isinstance(sections, list) or not all("name" in s and "sentences" in s for s in sections):
        raise ValidationError("Edited script must be a list of {name, sentences:[{text, fact_ids}]}")
    names = [s["name"] for s in sections]
    if names[0] != "HOOK" or "PAYOFF" not in names:
        raise ValidationError("Edited script must start with HOOK and contain PAYOFF")
    facts = {f["fact_id"]: f for f in load_facts(ctx, v["topic_id"])}
    results = factcheck.check_sections(sections, facts, min_sources=int(ctx.cfg.get("factcheck.min_sources_for_verified")))
    summ = factcheck.summarize(results, allow_needs_review=bool(ctx.cfg.get("factcheck.allow_needs_review_claims")))
    full = " ".join(x["text"] for s in sections for x in s["sentences"])
    lint = style_mod.lint({s["name"]: [x["text"] for x in s["sentences"]] for s in sections}, load_style(ctx))
    sid = new_id("scr")
    row = {**{k: old[k] for k in ("topic_id", "format", "angle", "blueprint_json", "hooks_json", "target_duration")},
           "script_id": sid, "version": int(old["version"]) + 1,
           "selected_hook": sections[0]["sentences"][0]["text"], "sections_json": sections, "full_text": full,
           "word_count": word_count(full), "est_duration": old["est_duration"] * word_count(full) / max(1, old["word_count"]),
           "llm_provider": f"human:{reviewer}", "style_report_json": lint,
           "factcheck_status": "PASSED" if summ["passed"] else "FAILED", "created_at": now_iso()}
    ctx.db.insert("scripts", row)
    factcheck.store_claims(ctx, sid, results, facts)
    ctx.db.update("videos", video_id, {"script_id": sid, "updated_at": now_iso()})
    _record(ctx, video_id, "EDIT", reviewer, notes=f"script edited -> {sid}")
    if not summ["passed"]:
        states.transition(ctx, video_id, "NEEDS_REVISION", reason="edited script failed fact check")
        return {"status": "NEEDS_REVISION", "factcheck": summ, "claims": results}
    from ..pipeline.orchestrator import run_stages
    return run_stages(ctx, video_id, ["editing", "qc"])


def render_again(ctx, video_id: str, reviewer: str, *, notes: str | None = None) -> dict:
    _record(ctx, video_id, "RENDER_AGAIN", reviewer, notes=notes)
    from ..pipeline.orchestrator import run_stages
    return run_stages(ctx, video_id, ["editing", "qc"])


def latest_approval(ctx, video_id: str) -> dict | None:
    rows = ctx.db.query("SELECT * FROM approvals WHERE video_id = ? AND decision IN ('APPROVE','SCHEDULE') "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (video_id,))
    return rows[0] if rows else None
