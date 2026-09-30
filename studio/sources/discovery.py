"""Source Discovery Engine: discover -> verify license -> record evidence -> ingest -> analyse."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..errors import ProviderError, RightsError
from ..logging_setup import get_logger
from ..textutil import now_iso, stable_id
from . import intelligence
from .ingest import ingest
from .providers import SourceCandidate, SourceProvider, build_providers
from .rights import LicenseInfo, evaluate

log = get_logger("sources.discovery")


@dataclass
class DiscoveryReport:
    approved: list[str] = field(default_factory=list)
    rejected: list[tuple[str, list[str]]] = field(default_factory=list)
    provider_errors: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"approved: {len(self.approved)}  rejected: {len(self.rejected)}"]
        for name, err in self.provider_errors.items():
            lines.append(f"provider {name} unavailable: {err}")
        return "\n".join(lines)


def _policy(ctx) -> dict:
    return {"allowed_licenses": ctx.cfg.get("source_policy.allowed_licenses"),
            "min_confidence": float(ctx.cfg.get("source_policy.min_rights_confidence")),
            "allow_share_alike": bool(ctx.cfg.get("source_policy.allow_share_alike"))}


def record_candidate(ctx, cand: SourceCandidate, *, topic_id: str | None) -> tuple[str, bool, list[str]]:
    """Upsert the source + license rows and decide. Returns (source_id, accepted, reasons)."""
    source_id = stable_id("src", cand.source_url)
    existing = ctx.db.get("sources", source_id)
    now = now_iso()
    if existing is None:
        ctx.db.insert("sources", {
            "source_id": source_id, "topic_id": topic_id, "source_url": cand.source_url, "platform": cand.platform,
            "creator": cand.creator, "title": cand.title, "date_found": now, "media_type": cand.media_type,
            "role": cand.role, "download_url": cand.download_url, "local_path": cand.local_path,
            "description": cand.description, "tags_json": cand.tags, "duration": cand.duration,
            "width": cand.width, "height": cand.height,
            "source_timestamps_json": cand.source_timestamps or None, "status": "DISCOVERED", "updated_at": now,
        })
    elif existing["status"] == "INGESTED":
        lic = ctx.db.select("licenses", {"source_id": source_id})
        if lic and lic[0]["verified_by"].startswith("human"):
            return source_id, True, ["previously verified by a human"]

    decision = evaluate(cand.license, **_policy(ctx))
    write_license(ctx, source_id, cand.license, decision, verified_by="auto")
    if decision.accepted:
        if (existing or {}).get("status") != "INGESTED":
            ctx.db.set_status("sources", source_id, "APPROVED", reason="rights verified", extra={"rejection_reason": None})
    else:
        ctx.db.set_status("sources", source_id, "REJECTED", reason="; ".join(decision.reasons),
                          extra={"rejection_reason": "; ".join(decision.reasons)})
    return source_id, decision.accepted, decision.reasons


def write_license(ctx, source_id: str, info: LicenseInfo, decision, *, verified_by: str) -> None:
    evidence_path = ctx.ws.license_evidence(source_id)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {"source_id": source_id, "recorded_at": now_iso(), "license_info": info.to_dict(),
                "decision": {"status": decision.status, "confidence": decision.rights_confidence,
                             "reasons": decision.reasons}, "verified_by": verified_by}
    evidence_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    ctx.db.delete("licenses", {"source_id": source_id})
    ctx.db.insert("licenses", {
        "license_id": stable_id("lic", source_id), "source_id": source_id, "license_type": decision.license_type,
        "license_url": info.license_url, "commercial_use_allowed": int(decision.commercial_use_allowed),
        "modification_allowed": int(decision.modification_allowed),
        "attribution_required": int(decision.attribution_required), "share_alike": int(decision.share_alike),
        "audio_reuse_allowed": int(bool(info.audio_reuse_allowed)), "attribution_text": info.attribution_text,
        "permission_reference": info.permission_reference, "permission_date": info.permission_date,
        "permission_notes": "; ".join(filter(None, [info.permission_notes, *info.risk_notes])) or None,
        "evidence_json": info.evidence, "evidence_path": str(evidence_path),
        "rights_confidence": decision.rights_confidence, "verification_status": decision.status,
        "verified_by": verified_by, "reasons_json": decision.reasons, "verified_at": now_iso(),
    })


def discover(ctx, *, queries: list[str], topic_id: str | None = None,
             providers: list[SourceProvider] | None = None, ingest_approved: bool = True,
             analyze_ingested: bool = True) -> DiscoveryReport:
    report = DiscoveryReport()
    limit = int(ctx.cfg.get("source_policy.max_results_per_provider"))
    providers = providers if providers is not None else build_providers(ctx)
    for provider in providers:
        seen: set[str] = set()
        for query in queries:
            try:
                candidates = provider.search(query, limit)
            except ProviderError as exc:
                log.warning("source provider %s failed for %r: %s", provider.name, query, exc)
                report.provider_errors[provider.name] = str(exc)
                ctx.db.record_error(stage="discover-sources", exc=exc, topic_id=topic_id)
                break
            for cand in candidates:
                if cand.source_url in seen:
                    continue
                seen.add(cand.source_url)
                sid, ok, reasons = record_candidate(ctx, cand, topic_id=topic_id)
                if not ok:
                    report.rejected.append((sid, reasons))
                    continue
                if ingest_approved:
                    try:
                        ingest(ctx, sid, provider=provider)
                        if analyze_ingested:
                            intelligence.analyze(ctx, sid)
                    except (ProviderError, RightsError) as exc:
                        log.warning("could not ingest %s: %s", sid, exc)
                        ctx.db.record_error(stage="ingest", exc=exc, topic_id=topic_id)
                        continue
                if sid not in report.approved:
                    report.approved.append(sid)
    if topic_id:
        count = ctx.db.scalar("SELECT COUNT(*) FROM sources WHERE topic_id = ? AND status IN ('APPROVED','INGESTED')",
                              (topic_id,))
        ctx.db.update("topics", topic_id, {"source_count": count, "updated_at": now_iso()})
    return report


def human_verify(ctx, source_id: str, *, reviewer: str, approve: bool, license_type: str | None = None,
                 permission_reference: str | None = None, permission_date: str | None = None,
                 notes: str | None = None) -> None:
    """Record a human rights decision. Approval still has to satisfy the license policy."""
    from .rights import normalize_license
    src = ctx.db.require("sources", source_id)
    lic_rows = ctx.db.select("licenses", {"source_id": source_id})
    prev = lic_rows[0] if lic_rows else {}
    info = LicenseInfo(
        license_type=normalize_license(license_type) if license_type else prev.get("license_type", "UNKNOWN"),
        license_url=prev.get("license_url"), creator=src.get("creator"),
        attribution_text=prev.get("attribution_text"),
        audio_reuse_allowed=bool(prev.get("audio_reuse_allowed")),
        permission_reference=permission_reference or prev.get("permission_reference"),
        permission_date=permission_date or prev.get("permission_date"),
        permission_notes=notes, evidence_kind="human_verified",
        evidence={"previous": prev.get("evidence_json"), "reviewer": reviewer, "notes": notes or ""},
    )
    if not approve:
        ctx.db.set_status("sources", source_id, "REJECTED", reason=f"rejected by {reviewer}: {notes or ''}",
                          extra={"rejection_reason": f"human: {notes or 'rejected'}"})
        return
    decision = evaluate(info, **_policy(ctx))
    write_license(ctx, source_id, info, decision, verified_by=f"human:{reviewer}")
    if not decision.accepted:
        ctx.db.set_status("sources", source_id, "REJECTED", reason="; ".join(decision.reasons),
                          extra={"rejection_reason": "; ".join(decision.reasons)})
        raise RightsError("Human approval recorded but the license still fails policy: " + "; ".join(decision.reasons))
    ctx.db.set_status("sources", source_id, "APPROVED", reason=f"verified by {reviewer}", extra={"rejection_reason": None})
