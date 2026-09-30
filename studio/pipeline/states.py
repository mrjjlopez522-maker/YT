"""Content calendar state machine for videos."""
from __future__ import annotations

from ..errors import StateTransitionError

ORDER = ["IDEA", "RESEARCHING", "SOURCING", "SCRIPTING", "EDITING", "QC", "REVIEW", "APPROVED", "SCHEDULED",
         "PUBLISHED", "ANALYZING"]
SIDE = ["NEEDS_REVISION", "REJECTED", "FAILED"]
ALL = ORDER + SIDE

TRANSITIONS: dict[str, set[str]] = {
    "IDEA": {"RESEARCHING"},
    "RESEARCHING": {"SOURCING"},
    "SOURCING": {"SCRIPTING"},
    "SCRIPTING": {"EDITING", "NEEDS_REVISION"},
    "EDITING": {"QC"},
    "QC": {"REVIEW", "NEEDS_REVISION"},
    "REVIEW": {"APPROVED", "REJECTED", "NEEDS_REVISION", "EDITING", "SCHEDULED"},
    "APPROVED": {"SCHEDULED", "PUBLISHED", "REVIEW", "EDITING"},
    "SCHEDULED": {"PUBLISHED", "APPROVED", "REVIEW"},
    "PUBLISHED": {"ANALYZING"},
    "ANALYZING": {"ANALYZING"},
    "NEEDS_REVISION": {"SCRIPTING", "EDITING", "SOURCING", "RESEARCHING", "REJECTED"},
    "FAILED": {"RESEARCHING", "SOURCING", "SCRIPTING", "EDITING", "QC", "REJECTED"},
    "REJECTED": set(),
}
for _s in ORDER[:6]:
    TRANSITIONS[_s].add("FAILED")


def check(current: str | None, new: str) -> None:
    if new not in ALL:
        raise StateTransitionError(f"Unknown status {new!r}")
    if current is None:
        if new != "IDEA":
            raise StateTransitionError("A new video must start as IDEA")
        return
    if new not in TRANSITIONS.get(current, set()):
        raise StateTransitionError(f"Cannot move a video from {current} to {new}")


def transition(ctx, video_id: str, new: str, *, reason: str | None = None, extra: dict | None = None) -> None:
    current = ctx.db.scalar("SELECT status FROM videos WHERE video_id = ?", (video_id,))
    check(current, new)
    ctx.db.set_status("videos", video_id, new, reason=reason, extra=extra)
