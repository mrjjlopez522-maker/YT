"""TikTokContext: the studio context plus the TikTok schema, directories, brand, series and formats."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from . import ENGINE_ROOT, REPO_ROOT
from studio.config import Config, load_config
from studio.context import StudioContext
from studio.errors import ConfigError
from studio.http import HttpClient
from studio.textutil import now_iso

SCHEMA = Path(__file__).with_name("schema_ext.sql")
EXTRA_DIRS = ("trends", "storyboards")
EXTRA_PK = {"trends": "trend_id", "formats": "format_id", "format_observations": "obs_id", "series": "series_id",
            "brands": "brand_id", "ideas": "idea_id", "research_packets": "packet_id", "audio": "audio_id",
            "comment_prompts": "prompt_id", "platform_exports": "export_id"}
EXTRA_COLUMNS = {
    "videos": {"idea_id": "TEXT", "series_id": "TEXT", "format_id": "TEXT", "mode": "TEXT",
               "platform": "TEXT DEFAULT 'tiktok'", "caption": "TEXT", "privacy_level": "TEXT"},
    "uploads": {"publish_id": "TEXT", "publish_time": "TEXT", "caption": "TEXT"},
    "analytics": {"saves": "INTEGER", "completion_rate": "REAL", "followers_gained": "INTEGER",
                  "avg_watch_time": "REAL", "engagement_rate": "REAL", "platform": "TEXT",
                  "retention_buckets_json": "TEXT"},
    "experiment_assignments": {"result": "REAL", "date": "TEXT"},
}
VALID_VOICE = {"kokoro", "espeak", "elevenlabs"}
MODES = ("TREND_RESPONSE", "EVERGREEN", "SERIES", "NEWS_EXPLAINER", "SOURCE_INSPIRED")


def validate_tiktok(cfg: Config) -> None:
    errors = []

    def check(cond, msg):
        if not cond:
            errors.append(msg)

    dur = cfg.get("production.target_duration", None)
    max_dur = cfg.get("production.max_duration", 180)
    check(isinstance(dur, int) and 10 <= dur <= max_dur, f"production.target_duration must be 10..{max_dur}")
    res = cfg.get("production.video_resolution", None)
    check(isinstance(res, list) and len(res) == 2 and res[0] * 16 == res[1] * 9, "video_resolution must be 9:16")
    check(cfg.get("production.fps", None) in (24, 25, 30, 50, 60), "production.fps must be 24/25/30/50/60")
    check(cfg.get("voice.provider", None) in VALID_VOICE, f"voice.provider must be one of {sorted(VALID_VOICE)}")
    check(cfg.get("publishing.tiktok_mode", None) in ("draft", "direct"), "publishing.tiktok_mode: draft or direct")
    for key in ("publishing.dry_run", "publishing.auto_publish", "publishing.manual_approval", "publishing.auto_upload"):
        check(isinstance(cfg.get(key, None), bool), f"{key} must be true or false")
    check(cfg.get("music.policy", None) in ("none", "licensed_library_only"), "music.policy invalid")
    check(cfg.get("content.llm_provider", None) in ("offline", "anthropic"), "content.llm_provider invalid")
    conf = cfg.get("source_policy.min_rights_confidence", None)
    check(isinstance(conf, (int, float)) and 0.5 <= conf <= 1.0, "min_rights_confidence must be 0.5..1.0")
    cal = cfg.get("calendar", {})
    check(1 <= int(cal.get("videos_per_day", 1)) <= 10 and 1 <= int(cal.get("days_per_week", 5)) <= 7,
          "calendar.videos_per_day 1..10 and days_per_week 1..7")
    if errors:
        raise ConfigError("Invalid TikTok configuration:\n  - " + "\n  - ".join(errors))


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    vals = tuple(int(c[i:i + 2], 16) for i in range(0, len(c), 2))
    return vals


class TikTokContext(StudioContext):
    def __init__(self, cfg: Config, *, http: HttpClient | None = None, console_logging: bool = True):
        super().__init__(cfg, http=http, console_logging=console_logging, extra_dirs=EXTRA_DIRS,
                         db_path=Path(cfg.home) / "database" / "tiktok.sqlite3", extra_schema=SCHEMA,
                         extra_primary_keys=EXTRA_PK, extra_columns=EXTRA_COLUMNS)
        self.brand = self._load_yaml("brand_file")
        self.series = {s["series_id"]: s for s in (self._load_yaml("series_file").get("series") or [])}
        self.formats = {f["format_id"]: f for f in (self._load_yaml("formats_file").get("formats") or [])}
        self._sync_reference_tables()

    @classmethod
    def create(cls, home: str | Path | None = None, *, config_path=None, overrides: dict | None = None,
               http: HttpClient | None = None, console_logging: bool = True, load_env: bool = True) -> "TikTokContext":
        home = Path(home or os.environ.get("TIKTOK_HOME") or ENGINE_ROOT).resolve()
        if config_path is None:
            local = home / "config" / "settings.yaml"
            config_path = local if local.is_file() else ENGINE_ROOT / "config" / "settings.yaml"
        cfg = load_config(home, config_path=config_path, overrides=overrides, load_env=load_env,
                          validator=validate_tiktok, search_roots=(ENGINE_ROOT, REPO_ROOT))
        return cls(cfg, http=http, console_logging=console_logging)

    def _load_yaml(self, key: str) -> dict:
        path = self.cfg.config_file(self.cfg.get(key))
        if not path.is_file():
            raise ConfigError(f"Missing config file {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _sync_reference_tables(self) -> None:
        """Mirror brand/series/formats config into the database (keeping learned format stats)."""
        now = now_iso()
        self.db.insert("brands", {"brand_id": self.cfg.channel_id, "channel_name": self.brand.get("channel_name", ""),
                                  "config_json": self.brand, "created_at": now}, or_replace=True)
        for s in self.series.values():
            self.db.insert("series", {"series_id": s["series_id"], "name": s["name"], "description": s.get("description"),
                                      "visual_identity_json": s.get("visual_identity"), "caption_style": s.get("caption_style"),
                                      "voice": s.get("voice"), "intro_style": s.get("intro_style"),
                                      "outro_style": s.get("outro_style"), "created_at": now}, or_replace=True)
        for f in self.formats.values():
            existing = self.db.get("formats", f["format_id"])
            self.db.insert("formats", {
                "format_id": f["format_id"], "name": f["name"], "content_format": f["content_format"],
                "hook_style": f.get("hook_style"), "target_length": f.get("target_length"),
                "cut_frequency": f.get("cut_frequency"), "text_density": f.get("text_density"),
                "narration_style": f.get("narration_style"), "visual_style": f.get("visual_style"),
                "story_structure_json": f["story_structure"], "comment_prompt_style": f.get("comment_prompt_style"),
                "payoff_type": f.get("payoff_type"), "cta_style": f.get("cta_style"),
                "why_it_works": f.get("why_it_works"),
                "evidence_label": (existing or {}).get("evidence_label") or f.get("evidence_label", "ASSUMPTION"),
                "stats_json": (existing or {}).get("stats_json"), "updated_at": now}, or_replace=True)

    # -- brand / series helpers -----------------------------------------------------
    def palette(self, series_id: str | None = None) -> dict:
        pal = {k: _hex(v) for k, v in (self.brand.get("palette") or {}).items()}
        s = self.series.get(series_id or "") or {}
        accent = (s.get("visual_identity") or {}).get("accent")
        if accent:
            pal["accent"] = _hex(accent)
        return pal
