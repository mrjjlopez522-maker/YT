"""Configuration loading and validation.

Sources, in increasing precedence:
  1. config/settings.yaml (user editable, committed)
  2. `overrides` passed by code/tests (dict merged deeply)
  3. environment variables for secrets and the two safety switches
     (DRY_RUN, AUTO_PUBLISH) — loaded from .env if present.

Safety invariants live here so every module reads them the same way:
  * dry_run is True unless explicitly disabled (env DRY_RUN=false or config).
  * auto_publish is False unless explicitly enabled in BOTH places that set it.
  * manual_approval defaults to True.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
_MISSING = object()

VALID_DURATIONS = {15, 20, 30, 45, 60}
VALID_FPS = {24, 25, 30, 50, 60}
VALID_PRIVACY = {"private", "unlisted"}
VALID_MUSIC_POLICIES = {"none", "licensed_library_only"}
VALID_LLM = {"offline", "anthropic"}
VALID_TTS = {"espeak", "elevenlabs"}
VALID_FREQUENCIES = {"daily", "weekdays", "3_per_week", "weekly"}

SECRET_ENV_NAMES = (
    "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_API_KEY",
    "ANTHROPIC_API_KEY", "TTS_API_KEY", "OTHER_API_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_CLIENT_KEY",
    "RESEARCH_API_KEY",
)

_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


def load_dotenv(path: Path) -> None:
    """Minimal .env reader. Never overrides variables already in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ and value != "":
            os.environ[key] = value


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _env_flag(name: str):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ConfigError(f"Environment variable {name}={value!r} is not a boolean",
                      hint="use true or false")


class Config:
    def __init__(self, data: dict, home: Path, search_roots: tuple[Path, ...] | None = None):
        self.data = data
        self.home = Path(home)
        # where relative config files are looked up, in order (applications may prepend their own root)
        self.search_roots = tuple(search_roots) if search_roots else (self.home, REPO_ROOT)

    # -- generic access -------------------------------------------------
    def get(self, dotted: str, default=_MISSING):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise ConfigError(f"Missing configuration key '{dotted}'",
                                      hint="compare config/settings.yaml with the documented keys")
                return default
            node = node[part]
        return node

    def path(self, rel: str | os.PathLike) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.home / p

    def config_file(self, rel: str) -> Path:
        """Resolve a config-referenced file: workspace first, then the repo."""
        p = Path(rel)
        if p.is_absolute():
            return p
        for base in self.search_roots:
            if (base / p).exists():
                return base / p
        return self.home / p

    def load_yaml(self, key: str) -> dict:
        path = self.config_file(self.get(key))
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    @staticmethod
    def secret(name: str) -> str | None:
        value = os.environ.get(name)
        return value if value else None

    # -- safety switches --------------------------------------------------
    @property
    def dry_run(self) -> bool:
        env = _env_flag("DRY_RUN")
        if env is not None:
            return env
        return self.get("publishing.dry_run", True) is not False

    @property
    def auto_publish(self) -> bool:
        # Requires an explicit `true` in config; env AUTO_PUBLISH=false vetoes it.
        env = _env_flag("AUTO_PUBLISH")
        return self.get("publishing.auto_publish", False) is True and env is not False

    @property
    def manual_approval(self) -> bool:
        return self.get("publishing.manual_approval", True) is not False

    @property
    def auto_upload(self) -> bool:
        return self.get("publishing.auto_upload", False) is True

    @property
    def resolution(self) -> tuple[int, int]:
        w, h = self.get("production.video_resolution")
        return int(w), int(h)

    @property
    def channel_id(self) -> str:
        return str(self.get("channel.id"))


def validate(cfg: Config) -> None:
    errors = []

    def check(cond, msg):
        if not cond:
            errors.append(msg)

    dur = cfg.get("production.target_duration", None)
    check(dur in VALID_DURATIONS, f"production.target_duration must be one of {sorted(VALID_DURATIONS)}, got {dur!r}")
    res = cfg.get("production.video_resolution", None)
    ok_res = isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(x, int) and x > 0 for x in res)
    check(ok_res, "production.video_resolution must be [width, height]")
    if ok_res:
        check(res[0] * 16 == res[1] * 9, f"production.video_resolution {res} is not 9:16")
    check(cfg.get("production.fps", None) in VALID_FPS, f"production.fps must be one of {sorted(VALID_FPS)}")
    mdv = cfg.get("production.max_daily_videos", None)
    check(isinstance(mdv, int) and mdv >= 1, "production.max_daily_videos must be an integer >= 1")
    check(cfg.get("production.posting_frequency", None) in VALID_FREQUENCIES,
          f"production.posting_frequency must be one of {sorted(VALID_FREQUENCIES)}")
    check(cfg.get("publishing.default_privacy", None) in VALID_PRIVACY,
          "publishing.default_privacy must be 'private' or 'unlisted' (public requires explicit approval)")
    check(cfg.get("music.policy", None) in VALID_MUSIC_POLICIES,
          f"music.policy must be one of {sorted(VALID_MUSIC_POLICIES)}")
    check(cfg.get("content.llm_provider", None) in VALID_LLM, f"content.llm_provider must be one of {sorted(VALID_LLM)}")
    check(cfg.get("voice.provider", None) in VALID_TTS, f"voice.provider must be one of {sorted(VALID_TTS)}")
    conf = cfg.get("source_policy.min_rights_confidence", None)
    check(isinstance(conf, (int, float)) and 0.5 <= conf <= 1.0,
          "source_policy.min_rights_confidence must be between 0.5 and 1.0")
    budget = cfg.get("costs.max_api_cost_per_video", None)
    check(isinstance(budget, (int, float)) and budget >= 0, "costs.max_api_cost_per_video must be >= 0")
    sim = cfg.get("qc.similarity_threshold", None)
    check(isinstance(sim, (int, float)) and 0 < sim <= 1, "qc.similarity_threshold must be in (0, 1]")
    for key in ("publishing.dry_run", "publishing.auto_publish", "publishing.manual_approval", "publishing.auto_upload"):
        check(isinstance(cfg.get(key, None), bool), f"{key} must be true or false")
    try:
        _env_flag("DRY_RUN")
        _env_flag("AUTO_PUBLISH")
    except ConfigError as exc:
        errors.append(str(exc))
    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))


def load_config(home: str | os.PathLike | None = None, *, config_path: str | os.PathLike | None = None,
                overrides: dict | None = None, load_env: bool = True, validator=None,
                search_roots: tuple[Path, ...] | None = None) -> Config:
    home_path = Path(home or os.environ.get("STUDIO_HOME") or REPO_ROOT).resolve()
    if load_env:
        load_dotenv(home_path / ".env")
    path = Path(config_path) if config_path else home_path / "config" / "settings.yaml"
    if not path.is_file():
        path = REPO_ROOT / "config" / "settings.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc
    cfg = Config(_deep_merge(data, overrides or {}), home_path,
                 search_roots=(home_path, *search_roots) if search_roots else None)
    (validator or validate)(cfg)
    return cfg
