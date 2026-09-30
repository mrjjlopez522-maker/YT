"""TikTok content calendar states."""
from __future__ import annotations

from studio.errors import StateTransitionError

ORDER = ["IDEA", "RESEARCH", "SOURCE", "SCRIPT", "VOICE", "EDIT", "QC", "REVIEW", "APPROVED", "SCHEDULED",
         "PUBLISHED", "ANALYTICS"]
SIDE = ["NEEDS_REVISION", "REJECTED", "FAILED"]
ALL = ORDER + SIDE
PRODUCTION = ["RESEARCH", "SOURCE", "SCRIPT", "VOICE", "EDIT", "QC"]

TRANSITIONS: dict[str, set[str]] = {
    "IDEA": {"RESEARCH"},
    "RESEARCH": {"SOURCE"},
    "SOURCE": {"SCRIPT"},
    "SCRIPT": {"VOICE"},
    "VOICE": {"EDIT"},
    "EDIT": {"QC"},
    "QC": {"REVIEW", "NEEDS_REVISION"},
    "REVIEW": {"APPROVED", "REJECTED", "NEEDS_REVISION", "SCRIPT", "VOICE", "EDIT", "SCHEDULED"},
    "APPROVED": {"SCHEDULED", "PUBLISHED", "REVIEW", "EDIT"},
    "SCHEDULED": {"PUBLISHED", "APPROVED", "REVIEW"},
    "PUBLISHED": {"ANALYTICS"},
    "ANALYTICS": {"ANALYTICS"},
    "NEEDS_REVISION": set(PRODUCTION) | {"REJECTED"},
    "FAILED": set(PRODUCTION) | {"REJECTED"},
    "REJECTED": set(),
}
for _s in ["IDEA", *PRODUCTION]:
    TRANSITIONS[_s].add("FAILED")


def transition(ctx, video_id: str, new: str, *, reason: str | None = None, extra: dict | None = None) -> None:
    current = ctx.db.scalar("SELECT status FROM videos WHERE video_id = ?", (video_id,))
    if new not in ALL:
        raise StateTransitionError(f"Unknown status {new!r}")
    if current is not None and new not in TRANSITIONS.get(current, set()):
        raise StateTransitionError(f"Cannot move {video_id} from {current} to {new}")
    ctx.db.set_status("videos", video_id, new, reason=reason, extra=extra)
