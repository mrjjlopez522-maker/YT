"""Workspace layout and deterministic file naming."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

DATA_DIRS = (
    "config", "database", "research", "sources", "licenses", "scripts", "audio", "visuals",
    "captions", "projects", "renders", "thumbnails", "exports", "analytics", "logs",
)

_BASE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*_video-\d{3}$")


def video_base_name(date: dt.date, slug: str, seq: int) -> str:
    """e.g. 2026-09-28_topic-slug_video-001"""
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"slug {slug!r} is not a clean kebab-case slug")
    if not 1 <= seq <= 999:
        raise ValueError("seq must be 1..999")
    return f"{date.isoformat()}_{slug}_video-{seq:03d}"


def is_valid_base_name(name: str) -> bool:
    return bool(_BASE_RE.match(name))


class Workspace:
    def __init__(self, home: Path):
        self.home = Path(home)

    def ensure(self) -> "Workspace":
        for d in DATA_DIRS:
            (self.home / d).mkdir(parents=True, exist_ok=True)
        (self.home / "sources" / "library").mkdir(parents=True, exist_ok=True)
        (self.home / "research" / "notes").mkdir(parents=True, exist_ok=True)
        return self

    def dir(self, name: str) -> Path:
        if name not in DATA_DIRS:
            raise ValueError(f"unknown workspace dir {name}")
        return self.home / name

    @property
    def db_path(self) -> Path:
        return self.home / "database" / "studio.sqlite3"

    def source_dir(self, source_id: str) -> Path:
        return self.home / "sources" / source_id

    def license_evidence(self, source_id: str) -> Path:
        return self.home / "licenses" / f"{source_id}.json"

    # per-video artefacts share one deterministic base name
    def project_dir(self, base: str) -> Path:
        return self.home / "projects" / base

    def render_path(self, base: str) -> Path:
        return self.home / "renders" / f"{base}.mp4"

    def export_dir(self, base: str) -> Path:
        return self.home / "exports" / base

    def audio_dir(self, base: str) -> Path:
        return self.home / "audio" / base

    def captions_path(self, base: str, ext: str) -> Path:
        return self.home / "captions" / f"{base}.{ext}"

    def script_path(self, base: str) -> Path:
        return self.home / "scripts" / f"{base}.json"

    def visuals_dir(self, base: str) -> Path:
        return self.home / "visuals" / base

    def thumbnail_path(self, base: str, n: int) -> Path:
        return self.home / "thumbnails" / f"{base}_thumb-{n}.png"
