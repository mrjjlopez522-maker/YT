"""StudioContext bundles config, database, workspace and shared clients."""
from __future__ import annotations

from pathlib import Path

from .config import Config, load_config
from .db.database import Database
from .http import HttpClient
from .logging_setup import get_logger, setup_logging
from .paths import Workspace
from .textutil import now_iso


class StudioContext:
    def __init__(self, cfg: Config, *, http: HttpClient | None = None, console_logging: bool = True,
                 extra_dirs: tuple[str, ...] = (), db_path: Path | None = None, extra_schema: Path | None = None,
                 extra_primary_keys: dict | None = None, extra_columns: dict | None = None):
        self.cfg = cfg
        self.ws = Workspace(cfg.home, extra_dirs).ensure()
        setup_logging(self.ws.dir("logs"), cfg.get("logging.level", "INFO"), console=console_logging)
        self.log = get_logger("studio")
        self.db = Database(db_path or self.ws.db_path, extra_schema=extra_schema,
                           extra_primary_keys=extra_primary_keys, extra_columns=extra_columns)
        self.http = http or HttpClient()
        self._ensure_channel()

    @classmethod
    def create(cls, home: str | Path | None = None, *, config_path=None, overrides: dict | None = None,
               http: HttpClient | None = None, console_logging: bool = True, load_env: bool = True) -> "StudioContext":
        cfg = load_config(home, config_path=config_path, overrides=overrides, load_env=load_env)
        return cls(cfg, http=http, console_logging=console_logging)

    def _ensure_channel(self) -> None:
        cid = self.cfg.channel_id
        if self.db.get("channels", cid) is None:
            self.db.insert("channels", {"channel_id": cid, "name": self.cfg.get("channel.name"),
                                        "niche": self.cfg.get("channel.niche"), "created_at": now_iso()})

    def close(self) -> None:
        self.db.close()
