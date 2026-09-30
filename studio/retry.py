"""Retry with exponential backoff for operations that can transiently fail."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from .errors import StudioError
from .logging_setup import get_logger

T = TypeVar("T")
log = get_logger("retry")


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, StudioError):
        return bool(getattr(exc, "retryable", False))
    return isinstance(exc, (TimeoutError, ConnectionError))


def retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 1.0, max_delay: float = 30.0,
          what: str = "operation", sleep: Callable[[float], None] = time.sleep) -> T:
    """Call fn(); on a retryable error wait base_delay * 2**n (capped) and try again."""
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below when not retryable
            last = exc
            if not is_retryable(exc) or attempt == attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            log.warning("%s failed (attempt %d/%d): %s — retrying in %.1fs", what, attempt, attempts, exc, delay)
            sleep(delay)
    raise last  # pragma: no cover - loop always returns or raises
