"""Logging: application.log, errors.log, render.log, api.log — with secret redaction.

Loggers:
  studio            -> application.log (all), errors.log (ERROR+), stderr (WARNING+)
  studio.render     -> additionally render.log
  studio.api        -> additionally api.log
"""
from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import SECRET_ENV_NAMES

# Each pattern: group 1 = the part to keep, group 2 = the secret value.
_PATTERNS = [
    re.compile(r"(?i)(\b(?:key|api_key|token|secret|password|access_token|refresh_token|client_secret)=)([^&\s\"']+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s\"']+)"),
    re.compile(r"(?i)(\"(?:api_key|access_token|refresh_token|client_secret)\"\s*:\s*\")([^\"]+)"),
    re.compile(r"(?i)((?:x-api-key|xi-api-key):\s*)([^\s\"']+)"),
]
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_HANDLER_TAG = "_studio_handler"


def redact(text: str) -> str:
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            text = text.replace(value, "***REDACTED***")
    for pat in _PATTERNS:
        text = pat.sub(r"\1***REDACTED***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed args: keep the raw message
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def _file_handler(path: Path, level: int) -> logging.Handler:
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(RedactingFilter())
    setattr(handler, _HANDLER_TAG, True)
    return handler


def setup_logging(log_dir: str | os.PathLike, level: str = "INFO", *, console: bool = True) -> None:
    """Idempotent: removes handlers installed by a previous call (tests switch workspaces)."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    names = ("studio", "studio.render", "studio.api")
    for name in names:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if getattr(h, _HANDLER_TAG, False):
                lg.removeHandler(h)
                h.close()

    root = logging.getLogger("studio")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.propagate = False
    root.addHandler(_file_handler(log_dir / "application.log", logging.DEBUG))
    root.addHandler(_file_handler(log_dir / "errors.log", logging.ERROR))
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        stream.addFilter(RedactingFilter())
        setattr(stream, _HANDLER_TAG, True)
        root.addHandler(stream)

    logging.getLogger("studio.render").addHandler(_file_handler(log_dir / "render.log", logging.DEBUG))
    logging.getLogger("studio.api").addHandler(_file_handler(log_dir / "api.log", logging.DEBUG))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("studio") else f"studio.{name}")
